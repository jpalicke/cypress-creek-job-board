-- ABOUTME: Creates the discovery tables: listings, the watchlist and company suggestions.
-- ABOUTME: A denied suggestion is the permanent tombstone that keeps a company off the watchlist.
CREATE TABLE listing (
    id TEXT PRIMARY KEY,
    ats TEXT NOT NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT NOT NULL,
    posted_at TEXT,
    fetched_at TEXT NOT NULL,
    content_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('new', 'seen', 'closed'))
);

CREATE TABLE watchlist_entry (
    company_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    ats TEXT NOT NULL,
    slug TEXT NOT NULL,
    identity_evidence TEXT NOT NULL CHECK (identity_evidence IN ('strong', 'weak', 'none')),
    approved_at TEXT NOT NULL,
    CHECK (ats <> '' AND slug <> ''),
    UNIQUE (ats, slug)
);

CREATE TABLE suggestion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company_key TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    ats TEXT,
    slug TEXT,
    resolver_result TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'denied')),
    decided_at TEXT,
    CHECK (
        (ats IS NULL AND slug IS NULL)
        OR (ats IS NOT NULL AND slug IS NOT NULL AND ats <> '' AND slug <> '')
    )
);

-- One denied row per company and board. A company denied on two boards has two rows, so both
-- boards stay blocked. The board lookup is not unique: two names may share a board.
CREATE UNIQUE INDEX suggestion_denied_company_board
    ON suggestion (company_key, COALESCE(ats, ''), COALESCE(slug, '')) WHERE state = 'denied';
CREATE INDEX suggestion_denied_company ON suggestion (company_key) WHERE state = 'denied';
CREATE INDEX suggestion_denied_board ON suggestion (ats, slug) WHERE state = 'denied';
