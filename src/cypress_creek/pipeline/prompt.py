# ABOUTME: Builds the three part prompt: trusted system text, untrusted data block, trusted facts.
# ABOUTME: The posting sits inside a boundary with a random token, never in the system message.
import hashlib
import json
import secrets
from collections.abc import Callable, Sequence
from enum import StrEnum
from importlib import resources

from pydantic import BaseModel, ConfigDict

from cypress_creek.facts.models import Fact, Share
from cypress_creek.providers.base import Capabilities

TOKEN_BYTES = 16
MAX_TOKEN_ATTEMPTS = 5


class PromptError(Exception):
    """The posting could not be placed safely inside a data block."""


class Stage(StrEnum):
    EXTRACT = "extract"
    ENTAIL = "entail"


TEMPLATES = {Stage.EXTRACT: "extract_v2.txt", Stage.ENTAIL: "entail_v1.txt"}
STAGES_SHOWING_FACTS = {Stage.ENTAIL}


class Prompt(BaseModel):
    """What a provider call needs. The system text is static, only the data block is untrusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    system: str
    data_block: str
    facts_block: str
    boundary_token: str
    prompt_hash: str

    @property
    def user_message(self) -> str:
        """The untrusted data block, then the trusted facts when the stage shows any."""
        if not self.facts_block:
            return self.data_block
        return f"{self.data_block}\n\n{self.facts_block}"


def _new_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def _system_text(stage: Stage) -> str:
    return (
        resources.files("cypress_creek.pipeline.prompts")
        .joinpath(TEMPLATES[stage])
        .read_text(encoding="utf-8")
    )


def prompt_facts(facts: Sequence[Fact], capabilities: Capabilities) -> list[Fact]:
    """Only verified facts, and only shareable ones when the backend is not local."""
    return [
        fact
        for fact in facts
        if fact.is_verified and (capabilities.local or fact.share is Share.SHAREABLE)
    ]


def _facts_block(facts: Sequence[Fact]) -> str:
    lines = [f"{fact.id}: {fact.claim}" for fact in facts]
    return "VERIFIED FACTS\n" + "\n".join(lines)


def _prompt_hash(system: str, output_schema: type[BaseModel]) -> str:
    schema_text = json.dumps(output_schema.model_json_schema(), sort_keys=True)
    return hashlib.sha256((system + "\n" + schema_text).encode("utf-8")).hexdigest()


def build_prompt(
    stage: Stage,
    posting_text: str,
    facts: Sequence[Fact],
    capabilities: Capabilities,
    output_schema: type[BaseModel],
    token_source: Callable[[], str] = _new_token,
    retry_feedback: str | None = None,
) -> Prompt:
    """Wrap the posting in a fresh boundary and keep it out of the system message.

    Every stage shares one signature, so `facts` is accepted always. The extraction stage shows
    the model no facts and ignores it. Stages that do show facts list only `prompt_facts` of them,
    after the data block, so a fact never sits inside the boundary and never reaches the system
    message. The "posting text" of such a stage is the untrusted requirement text.
    `retry_feedback` is the schema error text from a failed first try. It joins the trusted system
    message, never the data block, and it does not change the prompt hash.
    """
    for _ in range(MAX_TOKEN_ATTEMPTS):
        token = token_source()
        if token not in posting_text:
            break
    else:
        raise PromptError("the posting kept containing the boundary token")
    system = _system_text(stage)
    hashed_system = system
    if retry_feedback:
        system = f"{system}\n\nYour previous answer was rejected. Fix this: {retry_feedback}"
    return Prompt(
        system=system,
        data_block=f"<<<POSTING {token}>>>\n{posting_text}\n<<<END POSTING {token}>>>",
        facts_block=_facts_block(prompt_facts(facts, capabilities))
        if stage in STAGES_SHOWING_FACTS
        else "",
        boundary_token=token,
        prompt_hash=_prompt_hash(hashed_system, output_schema),
    )
