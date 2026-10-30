# ABOUTME: Builds a normalized Posting from raw text, so every source shares one hash and id rule.
# ABOUTME: Normalization errors (empty, too long) propagate as their typed ingest errors.
import secrets
from datetime import UTC, datetime

from cypress_creek.ingest.hashing import text_hash
from cypress_creek.ingest.models import Extractor, Posting, PostingSource
from cypress_creek.ingest.normalize import normalize

ID_HEX_CHARS = 16


def new_posting_id() -> str:
    return f"post-{secrets.token_hex(ID_HEX_CHARS // 2)}"


def build_posting(
    raw_text: str,
    source: PostingSource,
    extractor: Extractor,
    *,
    origin_url: str | None = None,
    posting_id: str | None = None,
    now: datetime | None = None,
) -> Posting:
    text, warnings = normalize(raw_text)
    return Posting(
        id=posting_id or new_posting_id(),
        source=source,
        text=text,
        text_hash=text_hash(text),
        origin_url=origin_url,
        extractor=extractor,
        warnings=warnings,
        created_at=now or datetime.now(UTC),
    )
