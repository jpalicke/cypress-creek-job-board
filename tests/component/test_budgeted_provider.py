# ABOUTME: Tests BudgetedProvider around a real Ollama adapter and loopback HTTP responses.
# ABOUTME: Proves preflight refusals and sent attempts have distinct budget accounting.
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import BaseModel

from cypress_creek.config import parse_settings
from cypress_creek.pipeline.extract import ExtractionStatus, extract_requirements
from cypress_creek.pipeline.trace import PipelineTrace
from cypress_creek.providers import (
    BudgetExceeded,
    ContextTruncated,
    ProviderUnavailable,
    RateLimited,
    SchemaViolation,
)
from cypress_creek.providers.base import estimate_input_tokens
from cypress_creek.providers.budget import Budget, BudgetedProvider, BudgetTracker
from cypress_creek.providers.errors import ProviderError
from cypress_creek.providers.ollama import OllamaProvider

# Nothing listens on the discard port. A call that reached the network is ProviderUnavailable.
NOTHING_LISTENING = "http://127.0.0.1:9"


class Answer(BaseModel):
    text: str


def _inner(base_url: str = NOTHING_LISTENING, *, context_tokens: int = 2048) -> OllamaProvider:
    settings = parse_settings(
        {
            "provider": "ollama",
            "model": "qwen3.5:0.8b",
            "base_url": base_url,
            "context_tokens": context_tokens,
        }
    )
    return OllamaProvider(settings)


def _wrapped(
    base_url: str = NOTHING_LISTENING, **limits: int
) -> tuple[BudgetedProvider, BudgetTracker]:
    inner = _inner(base_url)
    tracker = BudgetTracker(Budget(**limits), inner.capabilities.cost_per_mtok)
    return BudgetedProvider(inner, tracker), tracker


@contextmanager
def _ollama_response(
    body: dict[str, object] | list[tuple[int, dict[str, object]]],
) -> Iterator[str]:
    responses = [(200, body)] if isinstance(body, dict) else body
    served = [0]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            status, response_body = responses[min(served[0], len(responses) - 1)]
            served[0] += 1
            payload = json.dumps(response_body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_the_estimate_counts_system_data_and_schema_text() -> None:
    inner = _inner()
    schema_text = json.dumps(Answer.model_json_schema())
    expected = sum(inner.count_tokens_estimate(t) for t in ("sys", "data", schema_text))
    assert estimate_input_tokens(inner, "sys", "data", Answer) == expected


def test_a_call_over_the_budget_is_refused_before_any_connection() -> None:
    provider, tracker = _wrapped(max_input_tokens=10)
    with pytest.raises(BudgetExceeded) as caught:
        provider.complete_structured("system text", "data " * 100, Answer, max_output_tokens=10)
    assert caught.value.limit_name == "input_tokens"
    assert tracker.requests == 0


def test_a_call_inside_the_budget_reaches_the_inner_provider() -> None:
    provider, tracker = _wrapped()
    with pytest.raises(ProviderUnavailable) as caught:
        provider.complete_structured("system text", "data", Answer, max_output_tokens=10)
    assert caught.value.request_attempted is True
    assert caught.value.usage is None
    assert tracker.requests == 1
    assert tracker.unknown_usage_requests == 1
    assert tracker.input_tokens == 0
    assert tracker.output_tokens == 0


def test_unknown_usage_blocks_later_calls_in_the_same_budget() -> None:
    provider, tracker = _wrapped()
    with pytest.raises(ProviderUnavailable):
        provider.complete_structured("system text", "data", Answer, max_output_tokens=10)
    with pytest.raises(BudgetExceeded) as caught:
        provider.complete_structured("system text", "data", Answer, max_output_tokens=10)
    assert caught.value.limit_name == "unknown_usage"
    assert tracker.requests == 1


@pytest.mark.parametrize(
    ("prompt_tokens", "content", "error_type"),
    [
        (1026, '{"text":"ok"}', ContextTruncated),
        (17, '{"wrong":"shape"}', SchemaViolation),
    ],
)
def test_failed_server_responses_preserve_reported_usage(
    prompt_tokens: int, content: str, error_type: type[ProviderError]
) -> None:
    body = {
        "prompt_eval_count": prompt_tokens,
        "eval_count": 7,
        "message": {"content": content},
    }
    with _ollama_response(body) as base_url:
        provider, tracker = _wrapped(base_url)
        with pytest.raises(error_type) as caught:
            provider.complete_structured("system text", "data", Answer, max_output_tokens=10)
    assert caught.value.request_attempted is True
    assert caught.value.usage is not None
    assert caught.value.usage.input_tokens == prompt_tokens
    assert caught.value.usage.output_tokens == 7
    assert tracker.requests == 1
    assert tracker.unknown_usage_requests == 0
    assert tracker.input_tokens == prompt_tokens
    assert tracker.output_tokens == 7


def test_malformed_message_preserves_usage_in_a_typed_failure() -> None:
    body: dict[str, object] = {
        "prompt_eval_count": 17,
        "eval_count": 7,
        "message": None,
    }
    with _ollama_response(body) as base_url:
        provider, tracker = _wrapped(base_url)
        with pytest.raises(ProviderUnavailable) as caught:
            provider.complete_structured("system text", "data", Answer, max_output_tokens=10)
    assert caught.value.request_attempted is True
    assert caught.value.usage is not None
    assert caught.value.usage.input_tokens == 17
    assert caught.value.usage.output_tokens == 7
    assert tracker.requests == 1


def test_the_wrapper_reports_the_inner_capabilities_and_estimate() -> None:
    provider, _ = _wrapped()
    inner = _inner()
    assert provider.capabilities == inner.capabilities
    assert provider.count_tokens_estimate("a" * 30) == inner.count_tokens_estimate("a" * 30)


def test_rate_limit_counts_an_attempt_with_unknown_usage() -> None:
    with _ollama_response([(429, {})]) as base_url:
        provider, tracker = _wrapped(base_url)
        with pytest.raises(RateLimited) as caught:
            provider.complete_structured("system text", "data", Answer, max_output_tokens=10)

    assert caught.value.request_attempted
    assert caught.value.usage is None
    assert tracker.requests == 1
    assert tracker.unknown_usage_requests == 1


def test_rate_limit_retry_has_separate_trace_records() -> None:
    valid = {
        "prompt_eval_count": 18,
        "eval_count": 4,
        "message": {"content": '{"schema_version":1,"requirements":[]}'},
    }
    with _ollama_response([(429, {}), (200, valid)]) as base_url:
        trace = PipelineTrace()
        result = extract_requirements(
            "Needs Python.",
            _inner(base_url, context_tokens=4096),
            sleep=lambda _: None,
            trace=trace,
        )

    assert result.status is ExtractionStatus.OK
    assert [(call.outcome, call.error_type) for call in trace.calls] == [
        ("error", "RateLimited"),
        ("success", None),
    ]
    assert trace.calls[0].usage is None and trace.calls[0].cost_usd is None
    assert trace.calls[1].usage is not None
    assert trace.calls[1].usage.input_tokens == 18


def test_schema_retry_counts_both_reported_attempts() -> None:
    invalid = {"prompt_eval_count": 17, "eval_count": 3, "message": {"content": "{}"}}
    valid = {
        "prompt_eval_count": 19,
        "eval_count": 4,
        "message": {"content": '{"schema_version":1,"requirements":[]}'},
    }
    with _ollama_response([(200, invalid), (200, valid)]) as base_url:
        provider, tracker = _wrapped(base_url)
        trace = PipelineTrace()
        result = extract_requirements("Needs Python.", provider, sleep=lambda _: None, trace=trace)

    assert result.status is ExtractionStatus.OK
    assert tracker.requests == 2
    assert (tracker.input_tokens, tracker.output_tokens) == (36, 7)
    assert [(call.outcome, call.error_type) for call in trace.calls] == [
        ("error", "SchemaViolation"),
        ("success", None),
    ]
    assert [call.usage.input_tokens if call.usage else None for call in trace.calls] == [17, 19]
