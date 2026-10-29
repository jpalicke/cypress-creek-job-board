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
