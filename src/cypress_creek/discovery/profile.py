# ABOUTME: Derives the tag profile that company suggestion sends to a model: tag names and levels.
# ABOUTME: No claim text, employer, issuer, role or fact id is ever part of it.
from collections.abc import Mapping
from dataclasses import dataclass

from cypress_creek.facts.models import Bank, Level
from cypress_creek.pipeline.prompt import prompt_facts
from cypress_creek.providers.base import Capabilities

_RANK = {Level.FAMILIAR: 0, Level.WORKING: 1, Level.EXPERT: 2}
HEADING = "SKILL PROFILE"


@dataclass(frozen=True)
class TagProfile:
    """Each tag name with the highest level any usable fact gives it, in name order."""

    levels: Mapping[str, Level]

    def render(self) -> str:
        if not self.levels:
            return f"{HEADING}\n(none)"
        lines = [f"{name}: {level.value}" for name, level in self.levels.items()]
        return HEADING + "\n" + "\n".join(lines)


def tag_profile(bank: Bank, capabilities: Capabilities) -> TagProfile:
    """The profile from verified facts, and only shareable ones for a backend that is not local."""
    best: dict[str, Level] = {}
    for fact in prompt_facts(bank.facts, capabilities):
        for tag in fact.tags:
            if tag.name not in best or _RANK[tag.level] > _RANK[best[tag.name]]:
                best[tag.name] = tag.level
    return TagProfile(levels=dict(sorted(best.items())))
