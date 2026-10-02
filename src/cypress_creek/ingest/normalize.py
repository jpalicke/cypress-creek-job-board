# ABOUTME: Normalizes untrusted posting text: strips hostile characters, NFKC, whitespace, cap.
# ABOUTME: Pure functions. Over-long or empty text raises a typed error, it is never cut.
import re
import unicodedata

from cypress_creek.ingest.errors import EmptyPosting, PostingTooLong
from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import PostingWarning, WarningKind

__all__ = ["MAX_CHARS", "normalize", "text_hash"]

MAX_CHARS = 30_000
# Raw input far beyond the cap is refused before any per-character work happens.
MAX_RAW_CHARS = MAX_CHARS * 10

_LINE_BREAKS = re.compile(r"\r\n|\r| | ")
_SPACE_RUNS = re.compile(r"[^\S\n]+")
_BLANK_LINE_RUNS = re.compile(r"\n{3,}")


def _is_stripped(char: str) -> bool:
    """Control characters (except newline and tab) and format characters such as zero-width
    and bidi marks. Line breaks and tabs are handled as whitespace instead."""
    if char in "\n\t\r  ":
        return False
    return unicodedata.category(char) in {"Cc", "Cf"}


def normalize(raw_text: str) -> tuple[str, list[PostingWarning]]:
    if len(raw_text) > MAX_RAW_CHARS:
        raise PostingTooLong(len(raw_text), MAX_CHARS)
    unified = _LINE_BREAKS.sub("\n", raw_text)
    kept = [char for char in unified if not _is_stripped(char)]
    stripped_count = len(unified) - len(kept)
    folded = unicodedata.normalize("NFKC", "".join(kept))
    lines = [_SPACE_RUNS.sub(" ", line).strip() for line in folded.split("\n")]
    text = _BLANK_LINE_RUNS.sub("\n\n", "\n".join(lines)).strip()
    if len(text) > MAX_CHARS:
        raise PostingTooLong(len(text), MAX_CHARS)
    if not text:
        raise EmptyPosting
    warnings: list[PostingWarning] = []
    if stripped_count:
        warnings.append(
            PostingWarning(kind=WarningKind.CONTROL_CHARS_STRIPPED, count=stripped_count)
        )
    return text, warnings
