-- ABOUTME: Adds the Lever region to a watchlist entry so a fresh process asks only the right host.
-- ABOUTME: The region is null until a board has been found, and only a Lever board may carry one.
ALTER TABLE watchlist_entry ADD COLUMN region TEXT
    CHECK (region IS NULL OR (ats = 'lever' AND region IN ('us', 'eu')));
