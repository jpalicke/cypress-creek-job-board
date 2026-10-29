# ABOUTME: How sure the resolver is that a board belongs to a company: strong, weak or none.
# ABOUTME: Kept apart from the watchlist so code that proposes companies never imports a writer.
from enum import StrEnum


class IdentityEvidence(StrEnum):
    STRONG = "strong"
    WEAK = "weak"
    NONE = "none"
