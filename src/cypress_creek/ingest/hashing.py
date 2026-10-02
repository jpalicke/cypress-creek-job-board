# ABOUTME: The one definition of the posting text hash, sha256 over the normalized text.
# ABOUTME: Shared by the normalizer and the Posting model so they cannot disagree.
import hashlib


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()
