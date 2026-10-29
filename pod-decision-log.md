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
