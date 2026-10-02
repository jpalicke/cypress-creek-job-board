# ABOUTME: Typed errors raised while normalizing an untrusted posting.
# ABOUTME: Text is never silently cut or accepted empty, it is rejected with one of these.


class PostingTooLong(Exception):
    """The posting is longer than the character cap."""

    def __init__(self, length: int, limit: int) -> None:
        super().__init__(f"posting is {length} characters, the limit is {limit}")
        self.length = length
        self.limit = limit


class EmptyPosting(Exception):
    """Nothing is left of the posting after normalization."""

    def __init__(self) -> None:
        super().__init__("posting is empty after normalization")
