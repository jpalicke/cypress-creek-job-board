# ABOUTME: Runs the openai_compatible adapter in a child Python process against a loopback server.
# ABOUTME: The child builds the provider from environment settings through the factory.
import json
import os
import subprocess
import sys

from chat_server import chat_server, json_reply

CONSUMER = """
import json
from pydantic import BaseModel
from cypress_creek.config import load_settings
from cypress_creek.providers import get_provider

class Greeting(BaseModel):
    text: str

result = get_provider(load_settings()).complete_structured("Reply in JSON.", "Say hi", Greeting, 40)
print(json.dumps({"text": result.parsed.text, "usage": result.usage.model_dump()}))
"""


def test_a_child_process_gets_a_structured_answer_with_usage_over_real_http() -> None:
    reply = json_reply(
        {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"text": "hello"}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
    )
    with chat_server(reply) as (base_url, log):
        env = {
            **os.environ,
            "CYPRESS_CREEK_PROVIDER": "openai_compatible",
            "CYPRESS_CREEK_MODEL": "local-model",
            "CYPRESS_CREEK_BASE_URL": base_url,
        }
        result = subprocess.run(
            [sys.executable, "-c", CONSUMER],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=env,
        )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "text": "hello",
        "usage": {"input_tokens": 12, "output_tokens": 3},
    }
    assert [entry.path for entry in log] == ["/v1/chat/completions"]
    assert "authorization" not in log[0].headers
