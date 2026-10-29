# ABOUTME: Loads posting fixture folders: posting.txt, meta.yaml and labels.yaml, checked together.
# ABOUTME: The fixture set hash goes in a run header so a changed posting changes the run identity.
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cypress_creek.ingest.hashing import text_hash
from evals.harness.labels import LabelError, Labels, load_labels

FIXTURE_FILES = ("posting.txt", "meta.yaml", "labels.yaml")
FIXTURE_NAME = re.compile(r"^(greenhouse|lever|ashby)-[A-Za-z0-9-]+$")
MAX_META_BYTES = 20_000
MAX_POSTING_BYTES = 200_000


class Replacement(BaseModel):
    """The approved posting this fixture stands in for, and why the original was not used."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class FixtureMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str = Field(min_length=1)
    ats: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    api_url: str = Field(pattern=r"^https://")
    retrieved: date
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replaces: Replacement | None = None


@dataclass(frozen=True)
class Fixture:
    directory: Path
    text: str
    meta: FixtureMeta
    labels: Labels

    @property
    def text_hash(self) -> str:
        return text_hash(self.text)


def discover_fixtures(root: Path) -> list[Path]:
    """Posting fixture directories under root, in name order. Other fixture kinds are skipped."""
    return sorted(
        path for path in root.iterdir() if path.is_dir() and FIXTURE_NAME.match(path.name)
    )


def _load_meta(path: Path) -> FixtureMeta:
    if path.stat().st_size > MAX_META_BYTES:
        raise LabelError([f"{path.name}: file is too large"])
    try:
        return FixtureMeta.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        fields = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
        raise LabelError([f"{path.name}: invalid fields {', '.join(fields)}"]) from None
    except (yaml.YAMLError, UnicodeDecodeError):
        raise LabelError([f"{path.name}: not readable as YAML text"]) from None


def load_fixture(directory: Path) -> Fixture:
    missing = [name for name in FIXTURE_FILES if not (directory / name).is_file()]
    if missing:
        raise LabelError([f"{directory.name}: missing {', '.join(missing)}"])
    posting = directory / "posting.txt"
    if posting.stat().st_size > MAX_POSTING_BYTES:
        raise LabelError([f"{directory.name}: posting.txt is too large"])
    text = posting.read_text(encoding="utf-8")
    meta = _load_meta(directory / "meta.yaml")
    if meta.normalized_sha256 != text_hash(text):
        raise LabelError([f"{directory.name}: meta hash does not match posting.txt"])
    return Fixture(directory, text, meta, load_labels(directory / "labels.yaml"))


def fixture_set_hash(fixtures: list[Fixture]) -> str:
    """Hash the ids and posting hashes in id order. Labels are judged separately, not hashed."""
    payload = [
        {"id": fixture.meta.fixture_id, "sha256": fixture.text_hash}
        for fixture in sorted(fixtures, key=lambda f: f.meta.fixture_id)
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
