# ABOUTME: Helpers shared by the ATS feed adapters: the strict feed model base and text cleanup.
# ABOUTME: Feed text is hostile, so error paths name only locations and text becomes plain lines.
from pydantic import BaseModel, ConfigDict

from cypress_creek.ingest.errors import EmptyPosting
from cypress_creek.ingest.normalize import normalize


class FeedModel(BaseModel):
    """The base of every model of a feed shape: strict, immutable, unknown fields ignored."""

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


def field_path(location: tuple[int | str, ...]) -> str:
    """A path such as jobs[3].title. An error on the whole value is named $."""
    path = ""
    for part in location:
        path += f"[{part}]" if isinstance(part, int) else f"{'.' if path else ''}{part}"
    return path or "$"


def plain_line(raw: str) -> str:
    """Hostile text as one plain line: control characters stripped, whitespace collapsed."""
    try:
        text, _ = normalize(raw)
    except EmptyPosting:
        return ""
    return " ".join(text.split())
