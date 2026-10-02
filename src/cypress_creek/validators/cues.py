# ABOUTME: The one list of importance cue words and section headings, plus sentence splitting.
# ABOUTME: Shared by the importance check (V3) and the cue sentence coverage check (V13).
import re

from cypress_creek.ingest.models import Importance

REQUIRED_CUES = ("required", "must", "must have", "mandatory", "essential", "minimum")
PREFERRED_CUES = ("preferred", "nice to have", "a plus", "bonus", "desirable", "ideally")

REQUIRED_HEADINGS = frozenset(
    {
        "requirements",
        "required",
        "required qualifications",
        "minimum qualifications",
        "basic qualifications",
        "must have",
        "what you need",
    }
)
PREFERRED_HEADINGS = frozenset(
    {
        "preferred",
        "preferred qualifications",
        "nice to have",
        "nice to haves",
        "bonus",
        "bonus points",
        "desirable",
    }
)

_MAX_HEADING_WORDS = 5
_LINE = re.compile(r"[^\n]+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def _cue_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(word) for word in words)
    return re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)


_REQUIRED_PATTERN = _cue_pattern(REQUIRED_CUES)
_PREFERRED_PATTERN = _cue_pattern(PREFERRED_CUES)


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Spans of sentences. Every line is its own sentence, and lines split after . ! or ?."""
    spans: list[tuple[int, int]] = []
    for line in _LINE.finditer(text):
        position = line.start()
        for piece in _SENTENCE_BREAK.split(line.group()):
            start = text.index(piece, position)
            position = start + len(piece)
            if piece.strip():
                spans.append((start, position))
    return spans


def has_cue(sentence: str) -> bool:
    return bool(_REQUIRED_PATTERN.search(sentence) or _PREFERRED_PATTERN.search(sentence))


def _sentence_importance(sentence: str) -> Importance | None:
    required = bool(_REQUIRED_PATTERN.search(sentence))
    preferred = bool(_PREFERRED_PATTERN.search(sentence))
    if required and preferred:
        return Importance.UNSPECIFIED
    if required:
        return Importance.REQUIRED
    if preferred:
        return Importance.PREFERRED
    return None


def _heading_importance(line: str) -> Importance | None:
    """The importance a heading line sets for its section, or None if the line is no heading."""
    stripped = line.strip()
    label = stripped.lstrip("#").strip().rstrip(":").strip().casefold()
    if not label:
        return None
    if label in REQUIRED_HEADINGS:
        return Importance.REQUIRED
    if label in PREFERRED_HEADINGS:
        return Importance.PREFERRED
    looks_like_heading = stripped.endswith(":") or stripped.startswith("#")
    if looks_like_heading and len(label.split()) <= _MAX_HEADING_WORDS:
        return Importance.UNSPECIFIED
    return None


def cue_importance(text: str, span: tuple[int, int]) -> Importance:
    """What the cue words say about the span. A cue in its own sentence beats the section
    heading above it. With no cue anywhere the answer is unspecified."""
    start = min(max(span[0], 0), len(text))
    end = max(min(span[1], len(text)), start + 1)
    found = {
        importance
        for s, e in split_sentences(text)
        if s < end and e > start and (importance := _sentence_importance(text[s:e])) is not None
    }
    if len(found) == 1:
        return found.pop()
    if found:
        return Importance.UNSPECIFIED
    for line in reversed(text[:start].splitlines()):
        heading = _heading_importance(line)
        if heading is not None:
            return heading
    return Importance.UNSPECIFIED


def is_importance_heading(sentence: str) -> bool:
    """True for a line that only labels a required or preferred section."""
    return _heading_importance(sentence) in (Importance.REQUIRED, Importance.PREFERRED)
