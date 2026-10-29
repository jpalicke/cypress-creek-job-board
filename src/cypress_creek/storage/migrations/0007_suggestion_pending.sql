-- ABOUTME: One pending company suggestion per company, so a repeated proposal is not queued twice.
-- ABOUTME: The suggestion table itself is from 0002. This adds only the pending uniqueness.
CREATE UNIQUE INDEX suggestion_pending_company ON suggestion (company_key) WHERE state = 'pending';
