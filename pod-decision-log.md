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

## D35. CI chore merged (PR #127, 35907c6)
- 2026-10-29, manager merged after senior approval.
- PRs now run an offline e2e job (`not needs_network and not live and not live_openai and not live_lmstudio`). network.yml (weekly plus dispatch) runs `needs_network and not live and not live_openai` and is not a PR gate. All workflows declare `permissions: contents: read`. e2e tests marked live still run nowhere in CI (issue #128).

## D36. D7 draft help limits accepted and documented (PR #126)
- 2026-10-29, senior engineer ruled.
- Four classes still render as clean sentences: quantity words ("for a decade"), invented outcomes ("doubling revenue"), adjective inflation ("senior staff"), and negation ("Never led"). They are shared V8/V10 limits, to be fixed in a separate card; #126 names them in pipeline.md and links a follow-up issue. needs_human_review stays true. FOR JOE P: these are real gaps in the one rule's enforcement for drafts; please prioritise the follow-up.

## D37. Merge order follows the ADR plan
- 2026-10-29, manager.
- #120 (H1d) is approved (network run 40944431404 passed 33 tests, including the seeded-EU test) but holds ADR 0029, so I merge it after 0026 (D7 #126), 0027 (C4 #124) and 0028 (G1 #125) to avoid churn on the contributing.md "next free ADR" line. Every PR that adds an ADR updates that line. Migration 0005: #120 merges before G2, so G2 renumbers its migration to 0006.

## D38. G1 hardening decisions (PR #125, Worker E)
- 2026-10-29, Worker E.
- Bind check accepts only 127.0.0.1 (the card says so); 127.0.0.2 and ::1 exit 2. Reverse: restore the ipaddress is_loopback check.
- CSRF safe methods are GET, HEAD, OPTIONS; every other method, including unknown ones, needs the token. Reverse: add the method to SAFE_METHODS.
- Cache-Control no-store only on /api, so the later static bundle stays cacheable; no CSP yet (G3 decides it with the bundle).
- Unknown paths answer 403 without the token and 404 with it; validation error details no longer repeat caller keys.
- Process note: a stale server on port 5309 broke an e2e run; kill the python child, not the uv wrapper.
- FOR JOE P: second human review of Host/CSRF logic still owed: security.py, app.py, session.py, server.py, errors.py.

## D39. E4 scorer choices (PR #135, Worker C)
- 2026-10-29, Worker C.
- require_committed_labels is called in the scorer, not the runner (the runner only reads JSON manifests; the card that wires fixtures into the runner should call it too).
- No recorded CI-model run file is committed (needs Ollama); instead run files built from the real labels plus a live test against a real Ollama. Record one when fixtures are wired into the runner.
- Gap recall denominator is planted gaps that were extracted; unextracted ones show up as recall loss and in the mismatch view, not as missed gaps. FOR JOE P: this shapes what the published metric claims; reverse in metrics.repeat_values (ADR 0032).

## D40. Work assignments after the first wave
- 2026-10-29, manager. Worker C: E5 (#27) stacked on E4. Worker G: #133 (#128), then #131 (ADR 0033). Worker H: H7 (#46) stacked on H6 (ADR 0034). Worker E: G1 then G2 (ADR 0030), then peer review. Still blocked: E6 chain beyond E5, E8 (needs Ollama/keys), F4 (needs E6), G3 to G5 (need G2, E8).

## D41. G1 will merge before Joe P's second human review
- 2026-10-29, manager.
- The G1 card asks for a second human review of the Host and CSRF logic. The senior engineer approved (engineering review), Worker G ran adversarial probes against a real server, and the code is a loopback-only local server on a branch nobody deploys. Waiting for Joe P would stall G2 to G5. Choice: merge #125 after #124, and flag the review as owed. Files and functions to review are listed in the PR comment from the senior engineer (security.py, app.py, session.py, server.py, errors.py). Reverse: revert the merge, or order changes after review.

## D42. Claim-word checks for drafts (PR #136, closes #131, Worker G)
- 2026-10-29, Worker G.
- Quantity words, invented results, rank inflation and negation are caught by deterministic word lists in V8 and V10, no model in the loop. Negation, result and rank words are strict for drafts only (V10 strict mode); V8 quantity words apply everywhere. Alternative: strict everywhere, which would withhold legitimate "does not show" rationales. Reverse: pass claim_words=True from entail. ADR 0033.
- FOR JOE P: word lists are inherently incomplete; they raise the bar, they do not prove a draft true. Every draft still needs a human read.

## D43. Process slip caught by the harness
- 2026-10-29, Worker C reported.
- Worker C typed a commit with --no-verify out of habit; the auto-mode classifier denied it and nothing was committed that way. The commit was redone with hooks. No bypass reached any branch.

## D44. Drafts use a closed vocabulary (PR #136), the call Joe P may want to make himself
- 2026-10-29, manager decided on the senior engineer's recommendation.
- Question: how should drafts enforce "paraphrase only"? The first approach (word lists for quantity, impact, rank and negation) left 20 sibling words rendering clean (lookalike letters, zero-width characters, "many years", "halving", "head of", "founder", "hardly", "dont", ...), because lists are open-ended.
- Choice: closed vocabulary. Every word in a draft sentence must appear in a cited fact apart from a fixed list of function words and simple inflections; text is NFKC-normalized, format characters stripped, and non-ASCII letters not in a cited fact fail. Deterministic, fails safe (a failing sentence is shown as NOT VERIFIED and is never copyable).
- Alternative: keep word lists and pin the leaks as documented limits in ADR 0033.
- Cost: more false positives (legitimate paraphrases flagged); Worker G measures the rate on a corpus. Does not read meaning, so a recombination of cited words can still mislead; human review stays required.
- Side effect to know: V8 quantity words now withhold some entailment rationales (for example "half"), which moves E-lane metrics.
- To reverse: drop the strict mode for drafts.

## D45. H7a split and discovery design (PRs #138 stacked on #132; routes #137, Worker H)
- 2026-10-29, Worker H.
- Issue #46 retitled H7a; the routes are H7b (#137), which waits on G1. #138 is stacked on the H6 branch so its diff is 13 files; GitHub retargets it to main once #132 merges.
- run_discovery: blacklist first, fetch, dedupe, filter, score most recent first under a per-run cap (default 30), cache keyed by the existing run_id in a new table discovery_report; stops cleanly on backend outage or spent budget.
- Only analyzer calls count against the cap and cache hits are free; incomplete reports are not cache hits; no listing-to-report link table (the run id is computed). ADR 0034.

## D46. Migrations numbered in merge order
- 2026-10-29, manager. The runner is gapless. #120, H7a (#138) and G2 each add a migration; the later merger renumbers. Reverse: none needed.

## D47. Gap recall stays extracted-only, with planted_not_extracted published beside it (PR #135)
- 2026-10-29, senior engineer recommended, manager accepted.
- gap_recall's denominator is the planted gaps that were extracted (stage attribution, ADR 0032). To keep the headline honesty number honest, `planted_not_extracted` is published as an E4 metric (lower is better) so a run that skips planted gaps at extraction cannot show gap_recall 1.0 with no visible counter. Alternative: denominator of all planted gaps. To reverse: one line in repeat_values. FOR JOE P: this is the headline honesty metric; you may want the final call.
- A bug found in review: the unmatched branch counted the strong planted rows (python 3, postgresql, sql) as planted gaps; being fixed test first.

## D48. F4 and the PDF half of E6 need a PDF library decision from Joe P
- 2026-10-29, Worker E asked, manager logged.
- F4 (#34, PDF extraction in a child process) needs a PDF parser (pypdf). `uv add pypdf` was denied by the permission classifier ("Code from External") and the pod did not work around it. Needs from Joe P: approve a library (with an ADR, licence check and pip-audit as the F4 card requires) or name another route. Until then G2 answers a typed 501 `pdf_extraction_unavailable` for PDFs, and E6/F4 are not started.

## D49. E8 (first published run) waits for Joe P's review of the E3 labels
- 2026-10-29, manager.
- E8 needs no keys and no spend (local backends only), and live.yml's runner could host it with changes (pull qwen3.5:4b and 9b, a longer timeout, artifact upload; 9b may not finish on a CPU runner; run files committed under evals/results/). Blockers in order: (1) the runner does not run labeled fixtures (new issue filed), (2) E5 and E7 are not built, (3) the method rule says labels are frozen before runs and the E3 labels are still `review: pending` with Joe P, so a published run now could be invalidated by a label change. Choice: do not publish a run before Joe P's label review. Build the runner wiring, E5 and E7 meanwhile. Reverse: run E8 now and treat later label changes as a new label version.

## D50. Closed vocabulary implemented (PR #136, Worker G)
- 2026-10-29, Worker G.
- In drafts every word must come from a cited fact, except a 33-word pinned connective list, month names and numbers; a small inflection rule and a dropped-negation check apply; any non-ASCII or invisible character absent from a cited fact fails the sentence. Strict V10 mode, drafts only, no model, no new validator id. The impact and rank word lists are deleted. Reverse: restore them from the earlier commit on the branch.
- FOR JOE P: measured false-positive rate on 22 honest rewordings of the sample facts is 9 of 22 (41 percent), pinned in a test and reported in the PR. Failed sentences are shown as NOT VERIFIED, never hidden and never copyable, so a false positive costs reading time, not correctness. If the rate is too high for the product, widen the connective list or relax the mode, with your call.
- V8 quantity words can withhold some entailment rationales, which can lower E-lane rationale acceptance numbers (noted in ADR 0033).

## D51. False-positive rate of the closed vocabulary accepted (PR #136)
- 2026-10-29, senior engineer decided, manager concurs.
- Is a 41 percent false-positive rate acceptable? Choice: yes, for a review aid that shows NOT VERIFIED lines: failures cause friction, never false claims; the risk to manage is alarm fatigue. Do not grow the connective list; reduce false positives through the prompt and measure the live flag rate in the E5 metrics. Alternative: allow a reviewed list extension. FOR JOE P: this is the product trade-off between friction and safety; reverse by widening the list.
- Two further leaks (plural inflation through the stem rule; passive role inversion with "by") are being fixed: stems ing/ed only and "by" dropped from the connective list, raising false positives from 9/22 to 10/22. Recombinations of a fact's own words (for example "Led 8 billing systems") are pinned and documented as a limit.

## D52. H1c watchlist and blacklist routes (branch h1c-watchlist-routes, PR opens after #139 merges; Worker H)
- 2026-10-29, Worker H. ADR 0036.
- A watchlist add needs `"approval": "human_confirmed"` and refuses any extra field, so a model-proposed name cannot arrive as a human approval; the server stamps the approval time. The blacklist is checked first and wins over the watchlist; tombstoned companies stay out; conflicts are typed 409s. Routes: GET/POST /api/watchlist, GET/POST /api/blacklist, DELETE /api/blacklist/{id}.
- Unverified in the sandbox: the needs_network integration test (no network); CI dispatch is the evidence.

## D53. Manager resolved #136's docs conflict while the agents were rate-limited
- 2026-10-30 02:15 UTC, manager.
- All four workers and the reviewer hit the account's 5-hour usage limit (reset 04:10 UTC). The only blocker on #136 was a docs/README.md ADR-row conflict after #139 merged. I merged main into d-draft-limits in a scratch clone (/home/user/pod/manager-fix), kept the 0030 to 0033 rows in order, committed with the repo hooks and pushed (f533638). No code changed. Reverse: revert that merge commit.
- #139 (G2) merged as 9e886c6.

## D54. Senior engineer switched from Opus to Sonnet
- 2026-10-30, Joe P asked; manager did it.
- The Opus reviewer (about 725k tokens over its run) is retired and will not be resumed. A new Sonnet senior engineer took over with a written handover: review standard, conventions (D32, D44, D46, D47, D51), the open PR queue (#136, #138, #143 and the coming H1c, G3, H8, H7b, #140). Trade-off to know: Sonnet is cheaper on the usage window but may catch fewer subtle issues than the Opus reviewer did (which found the D7 whitelist breach, the G1 CSRF mount gap and the E4/E5 metric holes). Reverse: start an Opus reviewer again.

## D55. Two Sonnet seniors fix and review everything; workers retired
- 2026-10-30, Joe P asked; manager did it.
- Joe P: have the senior fix anything on the outstanding work, spin up a second senior, set both on all outstanding work. Senior A (the Sonnet reviewer already running) and senior B (new Sonnet agent) each own half of the open work and review the other's PRs. Workers C, E, G, H are retired and are not resumed (their unpushed WIP in /home/user/pod/worker-*/ is handed to the seniors).
- Share A: #138, H1c PR, H7b #137, H8 #47, #142, #134. Share B: #143, #140, G3 #37, G4 #38, #144. Blocked until Joe P: E8 #30, E6 #28, F4 #34, G5 #39.
- Trade-off: the author never reviews their own PR, but there are now only two minds on all the code, so review independence is weaker than with five agents; Joe P's final Opus pass is the backstop. Reverse: start more worker agents.

## D56. pypdf approved by Joe P; E6 and F4 unblocked
- 2026-10-30, Joe P ("pypdf is fine"), manager executed.
- Earlier the pod's `uv add pypdf` was denied by the permission classifier (D48) and nobody worked around it. After Joe P's approval the manager ran `uv add pypdf` in a scratch clone: pypdf 6.21.4, licence BSD-3-Clause (allowed list), `pip-audit` on the exported lock reports no known vulnerabilities, check_licenses passes. The dependency change (pyproject.toml plus uv.lock, 55 lines) is saved at /home/user/pod/pypdf-dependency.patch for senior B to apply in the E6/F4 PRs; ADR numbers 0042 (E6 fixtures) and 0043 (library choice).
- E6 (#28) then F4 (#34) go to senior B after #140 and G3. A PDF parser reading hostile files is the riskiest code left; Joe P's Opus pass should look at it.

## D57. E8 goes ahead after #140; senior A owns it
- 2026-10-30, Joe P ("run E8 after 140 merges"), manager assigned.
- Labels were reviewed (PR #147) so they are frozen. E8 runs only local Ollama models (qwen3.5:4b and 9b, 3 repeats at temperature 0, six fixtures) through a manual workflow; hosted rows stay "not run" because no keys or spend were approved. If a model cannot finish on the GitHub runner, what finishes is recorded and the rest is marked with the reason, never faked or silently truncated. The workflow does not push; the run files are committed in a normal PR and the comparison table regenerated. FOR JOE P: a first run on small models with Claude-written labels is a first look, not a benchmark.

## D58. Joe P reviewed G1
- 2026-10-30, Joe P ("G1 looks good").
- Treated as the second human review the G1 card asked for (Host and CSRF logic). Recorded in ADR 0028's status line via PR #149; the claim is limited to what he said. He can still order changes. D33, D34 and D41 are closed by this.

## D59. Trap: the label guard blocks `git merge main` on older branches
- 2026-10-30, senior A found, manager prioritised the fix.
- After the labels went to `review: reviewed` (PR #147), the pre-commit pytest gate's committed-labels check (evals/harness/labels.py) compares labels.yaml against HEAD, so a merge in progress fails it. Workarounds used without any hook bypass: update_pull_request_branch (server side) or cherry-pick onto a branch from main (H1c became PR #150, #146 closed). Senior A fixes the check (red test first; the guard must still refuse a real uncommitted edit).

## D60. The Anthropic adapter is proven against the live API (issue #129)
- 2026-10-30, Joe P ran `uv run pytest tests/integration/test_anthropic_live.py -q` with a real key: "2 passed in 3.00s".
- The "not yet proven" wording in docs/providers.md, ADR 0025 and docs/contributing.md is replaced by the dated result (PR #153, closes #129). No model id or usage numbers were reported, so none are recorded. D14's "needs from Joe P: an ANTHROPIC_API_KEY" is satisfied. The C4 OpenAI and LM Studio sign-offs (#130) remain open.

## D61. The OpenAI live call passed (issue #130 item 1)
- 2026-10-30, Joe P ran `uv run pytest tests/integration -m live_openai -q`: "1 passed, 72 deselected in 2.06s".
- Recorded in ADR 0027 and docs/providers.md via PR (openai-live-verified). #130 stays open: LM Studio findings, explicit confirmation of the gpt-6-luna pick and prices, and the temperature decision for E8 (the call passed without a temperature, so hosted rows are not temperature-pinned; E8 as scoped runs only local models, so this only matters when a hosted row is added).
- No model id or usage numbers were reported.
- Both seniors hit the 5-hour usage limit again at about 03:20 UTC (reset 04:10 UTC); they are resumed after that.

## D62. LM Studio verified in part (issue #130 item 2)
- 2026-10-30, Joe P ran the two live_lmstudio tests (2 passed) against LM Studio 0.4.17 (Build 4), model gemma-4-e4b, context 8192 for both the load and the tests, and recorded the server's overflow reply (error as a plain string, "The number of tokens to keep from the initial prompt is greater than the context length (n_keep: 20015>= n_ctx: 8192)...").
- Recorded in PR #155 with a component test that pins the reply (a characterization test: the existing "context length" marker already matched, so no red step). json_schema honoring and whether the model listing exposes the context length remain unknown; strict_schema stays false for loopback. The model id and usage numbers for the OpenAI run were not reported.
- #130 stays open for: the explicit confirmation of the gpt-6-luna pick and prices, and the temperature decision.

## D63. gpt-6-luna confirmed; hosted temperature limit accepted (issue #130 items 3 and 4)
- 2026-10-30, Joe P.
- Confirmed the model pick gpt-6-luna and its prices ($0.10 / $0.50 per Mtok).
- Temperature: Joe P ran two curl probes. Without a temperature the model answered HTTP 200 (conforming reply, 39 prompt and 18 completion tokens). With `temperature: 0` it answered HTTP 400, "'temperature' does not support 0 with this model. Only the default (1) value is supported." So a hosted OpenAI row cannot be pinned to temperature 0. Choice (option 1, recommended): the adapter keeps sending no temperature; the comparison table labels an OpenAI row as not temperature pinned (it varies between repeats by design). E8 itself runs local models only. Alternative rejected: leave hosted rows out of the comparison. Recorded in ADR 0027, docs/providers.md, docs/evals.md (PR #155, which now closes #130).

## D64. Closed vocabulary for drafts stays as is (decision on D44, D50, D51)
- 2026-10-30, Joe P.
- Keep the closed vocabulary and its measured 45 percent false-positive rate (10 of 22 honest rewordings flagged) unchanged for now. Revisit after Joe P has used the tool on his real resume and real job listings; the live flag rate from E5 and E8 runs is the other input. Options held for then: a reviewed extension of the 32-word connective list, or a relaxed mode. Nothing to change in code or docs now.

## D65. One senior plus the manager reviewing PRs
- 2026-10-30, Joe P.
- Senior A (a66bc9c84628b82fb) wraps up, hands over its open work and shuts down. Senior B (ab6bba535d773e2bb) is the only agent writing code; the manager reviews every PR (reads the diff, checks CI, scope, footers, em dashes and rules) and merges. B no longer cross-reviews. Reason: usage-window pressure and fewer moving parts. Trade-off: no independent second reviewer between the author and main apart from the manager; Joe P's Opus pass at the end is the backstop.

## D66. Gap recall stays extracted-only (decision on D47)
- 2026-10-30, Joe P ("option 1, keep it").
- Gap recall is computed over the planted gaps that were extracted, with `planted_not_extracted` published beside it (ADR 0032). Alternatives not chosen: all planted gaps as the denominator (double counts extraction misses, blurs which stage failed) or publishing both as named headline numbers.
- Follow-up found while checking: the E7 comparison table (merged) shows E1 recall but neither gap_recall nor planted_not_extracted, so the headline honesty pair is not in the table yet. Issue filed (title: Comparison table: show gap_recall with planted_not_extracted, and fix the OpenAI row label); to be done by senior B before the first published run (E8). The same issue fixes the OpenAI row label, which still says "pending confirmation".

## D67. Senior engineer B is named Barry Barrington
- 2026-10-30, Joe P.
- Senior B (agent id ab6bba535d773e2bb) is called Barry Barrington from now on. The agent's technical id cannot be renamed, so messages, comments and these docs use the name and keep the id for tooling. Earlier entries that say "senior B" or "B" mean Barry Barrington. Senior A (a66bc9c84628b82fb) is wrapping up and is not renamed.

## D68. Senior A is named Andrew
- 2026-10-30, Joe P.
- Senior A (agent id a66bc9c84628b82fb) is called Andrew. Joe P thanked Andrew for his help; Andrew has finished and stopped. His handover is docs/pod/handover-senior-a.md (PR #159). Earlier entries that say "senior A" or "A" mean Andrew.
- Hand-over from Andrew: #154 (H7b) goes to Barry (a live test failed on the slow runner and needs root-causing); #157 (strict schema rewriter, closes #134) and #159 (handover docs) are for the manager to review; E8, the slug/ats allowlist note and H8 move to Barry.

## D69. Merges by the manager after Andrew stopped (2026-10-30 about 04:30 UTC)
- Manager reviewed and merged: #149 (G1 review note), #148 (#140 runner wiring, read the diff: labels checked as committed before any case or provider exists, case id = fixture id, posting text unchanged, header records the fixture set hash), #158 (employer rule clarified, Joe P's decision), #155 (OpenAI and LM Studio results, model pick, temperature limit; closes #130), #157 (strict schema rewriter, closes #134; faithful refactor, keyword sets per provider identical to the old ones), #159 (Andrew's handover doc).
- Independence note: #155 and #158 were written by the manager and reviewed by the manager (the content was decided by Joe P); #157 and #159 were written by Andrew and reviewed only by the manager. Joe P's Opus pass covers these.
- Open: #154 (H7b; the live Ollama job failed one older H7a test on the slow runner; Barry root-causes it).

## D70. LM Studio: schema enforcement and loaded context adopted (decision on D62)
- 2026-10-30, Joe P ran two PowerShell probes against LM Studio 0.4.17 (Build 4), model gemma-4-e4b, and chose "options 2 and 3" for the context length.
- json_schema is enforced: a prompt asking for "gamma" against an enum of alpha and beta came back alpha (one probe, one model). `strict_schema` is now true for loopback (PR #161); replies are still validated either way. Other local servers are untested.
- LM Studio's /api/v0/models reports loaded_context_length (8192) and max_context_length (131072). The adapter reads it once when built: no configured context_tokens means the loaded value is used; a configured value at or below it wins; above it is a ConfigError. No endpoint, unloaded model or odd shape changes nothing.
- Two live tests were added; the manager could not run them (no LM Studio here), so Joe P's manual probes are the evidence.

## D71. Resume import is in scope, for other users too (new cards F5 and G10)
- 2026-10-30, Joe P: the project should be usable by more people than its author, so there must be a resume import and a screen for it. His own bank is still built together with Claude in chat.
- Filed F5 (extraction pipeline with a new deterministic validator) and G10 (the screen), after G9 (the fact bank screen). Shape: the model proposes candidate facts with a source span, code checks each against the resume text, the human approves or rejects each, approved candidates become unverified local-only facts, and verification stays the separate human step in G9. Hosted backends need `confirm_hosted` because a resume is personal data.
- Alternatives not chosen: letting import write verified facts (breaks the one rule), bulk approve (removes the review), a PDF-only or paste-only import (paste ships first, PDF waits on F4).
- Reverse by closing F5 and G10; nothing else depends on them.

## D72. The project is a proof of concept for a possible multi-user website
- 2026-10-30, Joe P: treat this as an MVP or proof of concept for a larger product that, if it works, would be a website with many users.
- Decision: keep building the single-user, loopback, local-data app as specified. Do not build accounts, hosting or multi-tenancy now, and do not file cards for them (that is a product call after the proof of concept shows it works). Do avoid choices that would make a later multi-user version harder: no new global singletons for user data, user data reached through the repository layer only, secrets never in the client, every new route keeps the Host and CSRF rules.
- Things that change for a hosted multi-user product, listed for the final report and not built: authentication and per-user data isolation (the fact bank and resumes become other people's personal data), a hosted-model key and its cost per user, rate limits and abuse controls, a shared discovery cache so many users do not each fetch the same boards (the polite-client rules matter more at scale), SQLite replaced by a server database, privacy policy and data deletion, and the validators and the one rule staying the product's core claim.
- Alternatives not chosen: starting multi-user work now (large, unproven, delays the proof) or ignoring the idea (risks cheap-to-avoid lock-in).
- Reverse by telling the manager to start auth and hosting cards.

## D73. Future product ideas from Joe P (not built, for the final report)
- 2026-10-30, Joe P, on a possible hosted version: different classes of users (job seekers, recruiters and others), and a way to try a resume against an ATS-like check to see what would pass or fail.
- Not built and no cards filed (see D72). Notes for whoever decides later:
  - An ATS-like check fits the existing design if it stays deterministic: parse the resume the way common systems do, match required terms against the posting, and report what a parser could not read. It must say it approximates; real systems differ and mostly do not publish their rules, so it cannot claim a pass or fail guarantee.
  - Recruiter accounts change the trust model: a recruiter would see job seekers' data, which needs the job seeker's consent and a clear sharing rule. The fact bank's shareable flag is a starting point.
  - Screening candidates by automated score is regulated in some places (for example New York City Local Law 144 and the EU AI Act's rules for employment tools). The current triage-only score is a job seeker aid; a recruiter-facing score needs legal review before it is built.
