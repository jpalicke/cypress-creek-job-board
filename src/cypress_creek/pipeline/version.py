# ABOUTME: The pipeline version: a digest of the code, prompts and config that judge a report.
# ABOUTME: A cached score is only reused under the same version, so it never outlives its judges.
import hashlib
from collections.abc import Sequence
from functools import cache
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = Path(__file__).resolve().parents[3]
# What decides a report: prompts and stages, validators, scoring and the weights and aliases.
JUDGES = ("pipeline", "validators", "scoring")
CONFIG_DIRS = ("config",)


def fingerprint(root: Path, directories: Sequence[str]) -> str:
    """A sha256 over the relative path and bytes of every file under the named directories.

    Raises FileNotFoundError for a directory that is not there, so a moved folder cannot quietly
    leave the version unchanged. The order of the names does not matter."""
    digest = hashlib.sha256()
    for name in sorted(directories):
        folder = root / name
        if not folder.is_dir():
            raise FileNotFoundError(f"pipeline version folder not found: {folder}")
        for path in sorted(item for item in folder.rglob("*") if _counts(item)):
            relative = path.relative_to(root).as_posix().encode("utf8")
            digest.update(len(relative).to_bytes(4, "big") + relative)
            content = path.read_bytes()
            digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


@cache
def pipeline_version() -> str:
    """The version of the code and config in this checkout."""
    code = fingerprint(PACKAGE_ROOT, JUDGES)
    config = fingerprint(CONFIG_ROOT, CONFIG_DIRS)
    return hashlib.sha256(f"{code}\n{config}".encode()).hexdigest()


def _counts(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts
