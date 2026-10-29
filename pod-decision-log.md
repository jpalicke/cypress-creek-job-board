# Pod decision log

Decisions the manager (or a pod agent) made that would otherwise have been Joe P's call. Joe P reviews these later and orders changes; a reversal is a product decision, not a mistake.

Each entry: date (UTC), who decided, the question, the choice, the alternatives, the reasoning, how to reverse.

## D1. PR size limit lifted for the pod
- 2026-10-29, Joe P (direct instruction).
- The roughly 20 file PR limit no longer binds, as long as the senior engineer is willing to review large PRs. Docs still ship in the same PR. Split only when a card truly separates.

## D2. E3 hand labels written by Claude
- 2026-10-29, Joe P delegated, Worker E executes.
- Card #25 says Joe P writes the labels. Joe P delegated them to the pod with a decision document, to be reviewed by him. Labels carry provenance (written by Claude on delegation, pending review). Changing a label is his product call.
- To reverse: edit the labels and re-run anything downstream of E3.

## D3. G1 test client without the FastAPI TestClient
- 2026-10-29, manager.
- Question: Starlette 1.10 raises a deprecation warning on `fastapi.testclient` (it wants `httpx2`), and the repo turns warnings into errors.
- Choice: do not add `httpx2`. Test the app with `httpx.ASGITransport` (async tests) for component tier, and a real uvicorn process on loopback for e2e. No warning filters.
- Alternatives: (1) add `httpx2` as a dev dependency (the permission classifier denied the install as "Code from External", and the manager did not override that); (2) ignore the warning in pytest config (hides a warning the pristine-output rule forbids).
- Reasoning: avoids a new third party dependency and the supply chain review it needs, keeps output pristine, and still exercises the real ASGI app with no mocks.
- To reverse: `uv add --dev httpx2`, switch the component tests to `fastapi.testclient`, and run `pip-audit` and `check_licenses.py`.
- Departs from the card text ("FastAPI's real test client").

## D4. Region held on the watchlist entry (H1d, PR #120)
- 2026-10-29, Worker H.
- Choice: `WatchlistEntry.region`, `Watchlist.set_region` and `LeverAdapter.remember_region`, with migration 0005.
- Alternatives: put region on `ExistenceResult`; have the adapter read the database.
- Reasoning: keeps adapters pure and avoids widening the shared contract.
- To reverse: drop the migration 0005 column and the two methods.

## D5. H1d naming for the #109 PR
- 2026-10-29, Worker H.
- #109 PR is titled "H1d" because the issue belongs with H1. Alternative: a separate id. Retitle to reverse.

## D6. Dependency audit fix as its own PR
- 2026-10-29, manager.
- The `audit` CI job fails on virtualenv 21.14.3 CVEs (fixed in 21.14.9), a dev dependency unrelated to any card. Worker H fixes it in a separate minimal lockfile PR so cards stay focused. Reverse by reverting that PR.

## D7. Audit fix bumps to latest virtualenv and filelock (PR #121)
- 2026-10-29, Worker H.
- Chose virtualenv 21.15.1 (from `uv lock --upgrade-package`) over pinning 21.14.9, and also bumped filelock 4.0.9 to 4.2.4 in the same PR, because the audit stays red without it.
- To reverse: revert the lock commit.

## D8. C5 reassigned from Worker C to Worker G
- 2026-10-29, manager. Worker G had idle capacity. Worker C keeps #116 fixes, C4 and D7.

## D9. Dependabot PRs with an inherited red audit
- 2026-10-29, senior engineer proposed, manager adjusted.
- Reviewer approved #118 and #117 on a local merged-tree audit. Manager choice: do not merge on a stale red check. Ask Dependabot to rebase (`@dependabot rebase`), wait for fresh green CI, then merge one lockfile PR at a time. Each merge makes the others conflict, so they are rebased in turn.
- To reverse: merge on the reviewer's local verification alone.

## D10. actions/cache v4 to v6 merged (PR #100)
- 2026-10-29, manager merged after senior approval. The reviewer dispatched the live workflow on the branch (Ollama cache restored, 12 live tests passed) because PRs never run `live.yml`.

## D11. E3 labelling decisions (PR #122, Worker E)
- 2026-10-29, Worker E on Joe P's delegation. Full list in docs/e3-label-decisions.md in the PR (10 judgement calls for Joe P).
- Importance labelled as a human reads the posting, not by the V3 cue rule (otherwise most labels would be unspecified). Reverse: set required/preferred under non-cued headings to unspecified.
- Fixture folders named evals/fixtures/<ats>-<job id>, so E5/E6 injection and pdf folders are not mistaken for postings. Reverse: rename and relax FIXTURE_NAME.
- Fixture hash lines carry "# pragma: allowlist secret" instead of .secrets.baseline entries. Reverse: swap for baseline entries.
- One fixture keeps a verbatim em dash in third party salary text. Reverse: normalize and update the hash. Reviewer asked to decide.
- Four of six originally chosen postings were 404 at fetch; same-board replacements are recorded in meta.yaml.

## D12. PR #116 live test and C4 parking (Worker C)
- 2026-10-29, Worker C.
- Live test gets spans from report row text via text.index and compares with uncovered_cue_spans, because report rows carry no spans and the review asked for the path through analyze. Safe because the sample posting has no duplicate requirement texts. Reverse: call extract_requirements then assess in the test.
- C4 WIP is committed on branch c4-openai-compatible (docs and ADR pending) while #116 had priority. C4 live tests need LM Studio and an OPENAI_API_KEY, which this container lacks; they fail loudly, and unverified LM Studio behaviour will be documented as unverified.

## D13. Credentialed live tests get their own markers and workflow (C4)
- 2026-10-29, manager.
- live.yml runs everything marked `live` under tests/integration, so C4's OpenAI and LM Studio live files would break it. Choice: separate markers (live_openai, live_lmstudio) excluded from live.yml; a workflow_dispatch only OpenAI workflow reading the OPENAI_API_KEY repo secret that fails loudly if absent; LM Studio is local only with documented command and findings marked unverified.
- Alternatives: change live.yml to supply credentials (none available); skip when absent (forbidden by the repo rules).
- Needs from Joe P: add the OPENAI_API_KEY repository secret, run the LM Studio live test locally, confirm the OpenAI model pick (gpt-6-luna from a model page fetched 2026-10-29) in the ADR.
- To reverse: merge the markers back into `live` and drop the new workflow.

## D14. C5 Anthropic adapter choices (PR #123, Worker G)
- 2026-10-29, Worker G.
- Native structured output (`output_config.format`), no tools offered, because the docs say claude-sonnet-5-5 rejects forced tool use.
- The paid live Anthropic test is excluded from live.yml via `live and not needs_network`. Alternative: a repo secret and a separate job. Reverse by adding the job.
- Models without documented prices need `input_usd_per_mtok` and `output_usd_per_mtok`; the adapter refuses to start without them rather than guessing. Reverse: add a default in KNOWN_PRICES.
- Needs from Joe P: an ANTHROPIC_API_KEY to run the live test; until then the real request body is not verified against the real API (a wrong key live run did get a real 401).

## D15. ADR numbers assigned in merge order; D7 moved to Worker G
- 2026-10-29, manager.
- ADR 0024 is claimed by #120 and #122, 0025 by #123. The reviewer states the next free number at approval and authors renumber before merge.
- D7 (#22) moved from Worker C to Worker G (idle), stacked on the #116 branch until it merges.

## D16. C4 adapter choices (PR #124, Worker C)
- 2026-10-29, Worker C.
- Price setting names input_usd_per_mtok / output_usd_per_mtok, matching C5, one source of truth. Reverse: rename the settings fields and docs.
- strict_schema is False for loopback LM Studio until verified on a real instance (claiming enforcement unverified would overstate it). Flip after the live_lmstudio run.
- Hosted requests use max_completion_tokens and no temperature; loopback uses max_tokens and temperature 0. Unproven; adjust build_request after live_openai runs.
- Needs from Joe P: OPENAI_API_KEY repo secret, an LM Studio live run, confirmation of the model pick. ADR 0026.

## D17. E4 moved to Worker C
- 2026-10-29, manager. Worker C idle; E4 (#26) stacked on the #122 branch. Worker E keeps G1/G2.

## D18. D7 draft help choices (Worker G, PR pending #116 merge)
- 2026-10-29, Worker G.
- Sentences that fail validators are shown with a visible "! NOT VERIFIED (rule: ...)" warning, never in clean_sentences (the only copyable output). Alternative: drop them. Reverse: filter in render_draft.
- V4 is checked against the facts supplied to the model, not the whole bank. Reverse: pass the full bank to check_fact_exists.
- ADR number provisional (0026) until the reviewer states the next free number at approval.

## D19. Peer review role for idle workers
- 2026-10-29, manager. To relieve the single senior reviewer, idle workers pre-review other workers' PRs and post `PEER REVIEW (not an approval)` comments. The senior engineer's verdict remains the only go-ahead.

## D20. Recording spy in H1d integration test (PR #120, Worker H)
- 2026-10-29, Worker H.
- The integration test records requested URLs with a thin spy (_RecordingFetch) wrapping the real fetch_url, passing through to the real transport. Alternative: none without changing the client. Reverse: delete the class. Senior engineer asked to rule on whether this fits the no-stubbed-HTTP rule.
- Sandbox cannot run needs_network tests (3 existing Lever network tests fail identically); CI is the evidence.

## D21. H6 dedupe and filter rules (Worker H, branch h6-dedupe-filters, PR not yet open)
- 2026-10-29, Worker H. Recorded in its ADR; each is reversible there.
- Dedupe merges only across different sources, only on an exact company, title and location match, and never when one source appears twice in the group.
- A listing with no `posted_at` passes the age filter.
- A closed listing that returns becomes `seen`.
- A skipped job with no id stops closing for that fetch.

## D22. CI does not run e2e or needs_network tests; fix via CI PR
- 2026-10-29, Worker H found it, manager decided.
- deterministic.yml runs only tests/unit and tests/component; live.yml runs only `integration -m live`. Nothing runs tests/e2e or needs_network. Choice: Worker H adds an e2e job to deterministic.yml (offline, a fair PR gate) and a separate network.yml (dispatch plus weekly) for needs_network (real third party services, so not a PR gate, to avoid flaky merges).
- Alternative: run needs_network on every PR. Reverse by moving that job into deterministic.yml.
- Until merged, green CI is evidence for unit and component only.

## D23. G1 API design choices (PR #125, Worker E)
- 2026-10-29, Worker E.
- CSRF token is delivered by GET /api/session, not embedded in the HTML shell or a cookie (works without a bundle, no ambient cookie authority). Reverse: serve it in the shell and drop the route.
- Docs, redoc and openapi routes are off so the route table is exactly the written routes. G3 may want the schema for types; reverse by dropping the three None arguments in create_app.
- Reachability probing lives in providers/ollama.py (is_reachable) because the import guard allows httpx only there; other backends report not_checked. Reverse: widen the guard test's allowed set.
- The server requires provider settings to start (exit 2 otherwise); create_app(None) exists for tests. Reverse: allow starting with no backends.
- Owed to Joe P: the card's second human review of the Host and CSRF logic.

## D24. E3 merged (PR #122, 4c7b7d5) with these rulings
- 2026-10-29, senior engineer ruled, manager merged.
- Em dashes in verbatim third party fixture text are accepted unnormalized: the rule governs text we author, the posting SHA-256 is its provenance record, no hook checks it, and main has a precedent (tests/fixtures/lever/palantir_page.json). Reverse: normalize and re-hash.
- Inline `# pragma: allowlist secret` is the repo convention (the .secrets.baseline results map is empty). Reverse: move entries into .secrets.baseline.
- ADR 0024 went to E3; #120 renumbers to 0025.
- FOR JOE P'S ATTENTION: CLAUDE.md says do not mention any specific employer or industry in the repo. The E3 fixtures, NOTICE and meta.yaml name publishers (the posting text itself names them), following the card's approved posting list and the palantir_page.json precedent. The reviewer did not treat it as a finding but flagged that this widens the exception. Please confirm or order the fixtures reworked.
- Optional reviewer items on #122 not yet done: assert the span message in the check_labels test; check fixture id vs directory name in load_fixture; document the intentional echo in _check_cues; a contributing.md sentence exempting verbatim third party fixtures; a note on E4/E8 that the runner must call require_committed_labels.

## D25. Harness behaviours found, and how Dependabot PRs are refreshed
- 2026-10-29, senior engineer found, manager accepted.
- FOR JOE P: every PR comment posted through the GitHub tools gets an appended "Generated by Claude Code" footer (including all SENIOR REVIEW comments). CLAUDE.md forbids attribution lines in PR text. PR bodies can be edited clean; comments cannot be, as the footer is added after posting. This is harness behaviour the pod cannot change.
- FOR JOE P: the harness rewrites "@dependabot rebase" in comments so the command is never delivered. My comments on #118 and #112 had no effect.
- Choice: refresh stale Dependabot CI by merging main into the branch (update_pull_request_branch) instead of the comment command. Dependabot stops managing a branch once it is altered, which is acceptable. To reverse: comment `@dependabot recreate` by hand.
- Dependabot PRs are refreshed and merged one at a time, since each lockfile merge makes the next stale.

## D26. Plain httpx allowed for hosted adapters (PR #123)
- 2026-10-29, senior engineer ruled.
- Hosted, operator-configured endpoints may use plain httpx instead of the guarded safe_http transport: the URL is config, not hostile input, redirects are off and the key is scrubbed. To reverse: route hosted adapters through safe_http.
- Merging C5 with the live gap is accepted once the docs say plainly that the real structured call has never been accepted by the live API; a follow-up issue tracks Joe P's single keyed run.
- ADR numbers follow merge order: #123 likely 0025, then #120, #124.

## D27. Follow-up issue filed: e2e tests marked live run nowhere in CI (#128)
- 2026-10-29, manager, on Worker H's finding while adding the e2e CI job (PR #127).

## D28. C4 follow-ups (PR #124, Worker C)
- 2026-10-29, Worker C.
- HTTP path tested with a new stdlib helper tests/chat_server.py (ThreadingHTTPServer) because tests/http_support.py http_server does not read POST bodies. Reverse: extend http_support and delete the helper.
- 400 context errors map to ContextTruncated carrying the estimate and the window, no new error class.
- Remote base_url must be https; a refusal without usage maps to Refusal; no hosted default for context_tokens.
- Harness note: the PR tool re-adds the attribution footer on create (and possibly on update), so authors check the body after every edit.

## D29. Caught before merge: D7 draft validators whitelisted posting text (PR #126)
- 2026-10-29, senior engineer found, Worker G fixing.
- The first D7 version passed requirement.text to V7, V8 and V10, so numbers, employers and skills from the posting counted as allowed. Repro: "Led 10 engineers using Python and Kubernetes at Google for 10 years [F-0001]" rendered as a clean sentence although the fact says 8 engineers, a different employer and no Kubernetes. This breaches the one rule. Fix: the allow-list is the cited facts only, tests first. Nothing merged. Consider a Joe P review of the final D7 validator wiring, since it is the heart of the product.

## D30. G2 design choices (branch G2-posting-analyze-routes, PR opens after #125 merges; Worker E)
- 2026-10-29, Worker E. Reversal notes in the PR and ADR 0027 (provisional number).
- Migration 0005 (posting and report tables) matches main today; #120 also adds 0005_watchlist_region.sql. db.py refuses gaps, so whichever merges second renumbers.
- PDF input (raw application/pdf body or a link returning a PDF) is size-capped and `%PDF-` checked, then answers a typed 501 `pdf_extraction_unavailable` because the F4 extractor is not built. Reverse when F4 lands: call it.
- Request bodies are limited by declared Content-Length in a middleware (1 MiB, 10 MiB for PDF); chunked bodies get 411.
- The budget is per analysis request from the provider settings; nothing is saved across requests (a run-wide ledger would need a table). The estimate route covers the extraction call only.
- Stored and returned verdicts omit the `offending` text since it can hold posting or model text.
- Database created and migrated on first use; to also be done at server startup (test first). Bank file read on every request.
- POST /api/facts/validate always answers 200 with `valid` and a short `problem`, never echoing the YAML.
- No GET /api/postings/{id} yet, because no card needs it.
- A down backend gives a 200 with an incomplete report, stored and returned.
- Unverified here: the needs_network link test returns 502 in this sandbox (no public DNS through the guard); the live test needs Ollama.

## D31. Open questions for Joe P from the C4 peer review (PR #124)
- 2026-10-29, Worker E peer review, manager logging.
- Hosted OpenAI calls send no temperature, which affects the temperature-0 rule that the E8 first published run assumes. Needs a decision once the OpenAI live test has run.
- The gpt-6-luna model pick comes from a web page and needs confirmation.
- A successful reply with a high reported prompt count is discarded (conservative truncation guard).
- Two near-duplicate schema rewriters (Anthropic and OpenAI adapters) and different context_tokens defaults remain as optional cleanups.

## D32. ADR numbers pre-assigned instead of merge order
- 2026-10-29, senior engineer proposed, manager accepted.
- Plan: #126 = 0026 (core promise fix), #124 = 0027, #125 = 0028, #120 = 0029, G2 = 0030, H6 = 0031, later PRs 0032+. Gaps are fine if a PR is dropped. Reverse: renumber at merge time.

## D33. G1 security review status (PR #125)
- 2026-10-29, senior engineer probed the Host and CSRF logic (duplicate Host, trailing dot, padded port, no Host, IPv6, lookalikes all 403; compare_digest on every write; no CORS). Joe P's own second human review of the Host and CSRF logic is still owed; exact files and functions are listed in the PR comment.

## D34. G1 CSRF gap found by peer review (PR #125)
- 2026-10-29, Worker G found, reproduced against a real server on 5309; Worker E fixing.
- The app-wide CSRF dependency did not cover mounted sub-apps (POST /sub/x without a token returned 200), contradicting ADR and docs. Fix: pure ASGI middleware after the Host check, with a mount test and a route-walk test. Optional items taken test first: custom methods, duplicate token headers, request body limit (a 50 MB body was accepted), hardening headers.
- Joe P's second human review of the Host and CSRF logic is still owed.
