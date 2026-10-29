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
