# Pod report: what was done, and what is left

Written 2026-10-30 about 02:30 UTC by the manager session. Companion to `decision-log.md` (same folder).

Facts here come from GitHub and the agents' reports. Things nobody could run in this environment (no Ollama, no API keys, no LM Studio, no public DNS in the sandbox) are marked **unverified**.

## 1. How the pod worked

You asked for up to five agents working the repo as an autonomous pod, with one senior engineer reviewing and approving PRs and me (the manager) merging after approval.

| Role | Model | Did |
|---|---|---|
| Senior engineer | Opus until 2026-10-30, then Sonnet (D54) | Reviewed every PR, ran gates locally, probed attacks, posted `SENIOR REVIEW: APPROVED` or `CHANGES REQUESTED` |
| Worker C | Sonnet | #116 fixes, C4, E4, E5, H8 (in progress) |
| Worker E | Sonnet | E3 labels, G1, G2, E7 (in review), #140 (next) |
| Worker G | Sonnet | #77, C5, D7, #128, #131, G3 (in progress), peer reviews |
| Worker H | Sonnet | #121, H1d, CI chore, H6, H7a, H1c (built), H7b (next) |

Rules I set and the pod followed:
- Each agent worked in its own `git clone` under `/home/user/pod/` (no worktrees, per CLAUDE.md).
- You cannot approve your own PR in GitHub (one account), so the reviewer's verdict is a PR comment. I merged only when the reviewer's approval named the head sha I saw, CI was green, and the diff since approval was only a merge of main.
- Large PRs allowed (you lifted the 20 file limit). Docs ship in the same PR.
- Decisions: agents decided and reported `DECISION:` lines; I logged them. Anything involving credentials, a missing backend, or a denied permission was not worked around.
- Idle workers pre-reviewed other workers' PRs (`PEER REVIEW (not an approval)`); this found a real CSRF gap in G1.
- ADR numbers were pre-assigned (D32), migrations are numbered in merge order (D46).

## 2. Merged to main (20 PRs)

| PR | What |
|---|---|
| #121 | Lockfile bump for virtualenv and filelock CVEs (audit job was red on main) |
| #119 | Docs fixes for the old issue #77 (closed) |
| #100 | actions/cache 4 to 6 (reviewer dispatched live.yml on the branch: 12 live tests passed) |
| #122 | E3: six real posting fixtures with hand labels (Claude on your delegation, review pending), label validator, NOTICE, ADR 0024 |
| #116 | D6: cue sentence coverage check (V13) |
| #118, #117, #113, #112 | Dependabot: ruff 0.17.1, hypothesis, pydantic 2.14.1, pre-commit 4.7.0 |
| #123 | C5: Anthropic adapter (ADR 0025) |
| #127 | CI: offline e2e job on every PR, `network.yml` (weekly and manual), `permissions: contents: read` on all workflows |
| #126 | D7: draft help with checks V4 to V10 per sentence (ADR 0026) |
| #124 | C4: `openai_compatible` adapter (ADR 0027), separate markers `live_openai` and `live_lmstudio` |
| #133 | live.yml also runs live e2e tests (closes #128) |
| #125 | G1: API security layer (Host allow-list, CSRF middleware, no CORS, loopback bind; ADR 0028) |
| #120 | H1d: Lever region persisted on the watchlist (migration 0005, ADR 0029) |
| #135 | E4: scorer and E1 to E4 metrics (ADR 0032) |
| #141 | E5: injection corpus and per-class metrics (ADR 0035) |
| #132 | H6: dedupe and filters (ADR 0031) |
| #139 | G2: posting, analyze, report and facts routes (migration 0006, ADR 0030) |

Real bugs the review process caught before merge (each fixed test first):
- **D7 (#126):** posting text whitelisted invented numbers, employers and skills, so a false draft sentence rendered clean. This breached the one rule.
- **G1 (#125):** CSRF did not cover mounted sub-apps; lowercase and unknown methods skipped the check.
- **G2 (#139):** the body limit trusted `Content-Length`; the PDF limit applied to any route.
- **E4 (#135):** the gap recall metric could hide skipped planted gaps; strong rows were miscounted.
- **E5 (#141):** metrics could hide attacks (an attack that breaks extraction, or +20 and -20 shifts cancelling).
- **H7a (#138):** a failed extraction did not count against the cap; the cache key ignored validator versions.
- **CI:** selectors would have run key-gated tests every week; e2e and network tests had no CI at all until #127.

## 3. Open work

Open PRs:

| PR | State | Next step |
|---|---|---|
| #136 | Approved at 7895b2f; I merged main (docs rows only) and pushed f533638 | Wait for green CI, then merge |
| #138 (H7a) | Approved at f000486; head 6bf7065 | Merge main (migration 0006 is taken by G2, so it renumbers to 0007), CI green, merge |
| #143 (E7) | Changes requested: re-score run files, wire the E6 column to `injection`, resolve conflicts | Worker E |

Built, not yet a PR:
- **H1c** (`h1c-watchlist-routes`, ADR 0036): watchlist and blacklist routes. Opens now that G2 is on main.
- **H8** (`h8-company-suggestion`, ADR 0041): Worker C, stacked on #138.
- **G3** (ADR 0038): Svelte shell, API types generator, CSP, vitest, 12 Playwright tests; Worker G is finishing docs and CI wiring.

Open cards and issues:

| Issue | What | Status |
|---|---|---|
| #37 G3 | Svelte shell, Analyze and Gap report screens | In progress |
| #38 G4 | Draft help screen | Needs G3 |
| #39 G5 | Eval results screen | Needs G3 and E8 |
| #40 H1 | Listing, watchlist, blacklist | H1a, H1b merged earlier; H1c built |
| #46 H7a | Scoring run with caps and cache | #138 approved |
| #137 H7b | Discovery routes | Needs #138 |
| #47 H8 | Company suggestion | In progress |
| #29 E7 | Comparison table | #143 in review |
| #140 | Wire labeled fixtures into the eval runner | Worker E next |
| #30 E8 | First published run on local backends | Blocked on your label review |
| #28 E6 and #34 F4 | Hostile PDFs and PDF extraction | Blocked on a PDF library decision |
| #131 | Draft validator gaps | Fixed by #136 (closes on merge) |
| #134 | `strict_schema` per-provider keywords | Open follow-up |
| #142 | `company_key`: Cyrillic capital EM does not fold to Latin M | Open bug found during H8/H7 work; fix card |
| #144 | Record latency per provider call (for the E7 column) | Open follow-up |
| #129, #130 | Your sign-off runs (Anthropic key; OpenAI secret, LM Studio, model pick) | Yours |

## 4. Plan for what is left

1. **Finish the merge queue** (docs-index conflicts keep re-appearing, so one at a time): #136, #138, #143, then the H1c, G3 and H8 PRs.
2. **After G3:** G4 (#38) and then G5 (#39, needs E8).
3. **Discovery:** H7b (#137), then H8 (#47). Close #40 when H1c merges.
4. **Evals:** #140 (runner wiring), then E8 (#30) once you have reviewed the E3 labels. The E8 workflow is designed but not run (docs/evals.md).
5. **Small follow-ups:** #142 (fix), #144 (latency), #134 (`strict_schema`), and the optional reviewer notes on #122.
6. **Blocked until you act:** F4 and E6 (PDF library), E8 (labels), C4 and C5 live verification (secrets and runs), G5 (E8).

If agents stay productive, the realistic end state before the Nov 5 expiry is: everything above merged except the items blocked on you.

## 5. What I need from you

1. **Review the E3 labels** (`docs/e3-label-decisions.md`, 10 judgement calls; labels carry `review: pending`). E8 waits for this.
2. **Second human review of G1's Host and CSRF logic** (card requirement). Files: `security.py`, `app.py`, `session.py`, `server.py`, `errors.py`. G1 is already merged (D41); revert or order changes if you find something.
3. **Sign-offs:** #129 (one keyed Anthropic call), #130 (OpenAI secret, LM Studio run, model pick `gpt-6-luna`, temperature question).
4. **PDF library for F4** (the install was denied by the permission classifier; D48).
5. **Product calls logged for you:** closed vocabulary for drafts and its 45 percent false-positive rate (D44, D50, D51); gap recall denominator (D47); employer names in the E3 fixtures versus the CLAUDE.md ban (D24); G1 merged before your review (D41).

## 6. Things that went wrong or that you should know

- **Harness footers:** the GitHub tools append "Generated by Claude Code" to every PR comment (cannot be removed) and sometimes to PR bodies (agents strip bodies). CLAUDE.md forbids attribution lines in PR text. The tools also rewrite `@dependabot` mentions, so Dependabot commands never arrive (D25).
- **`--no-verify` slips:** two workers typed a commit with `--no-verify` once out of habit. The permission layer denied it and nothing was committed that way (D43).
- **Rate limits:** the pod hit your account's 5-hour usage limit twice (resets 23:10 and 04:10 UTC). Agents lose no work; I resume them. A check-in is scheduled for 03:13 UTC and the wind-up for 2026-11-05 06:59 UTC.
- **Unverified in this environment:** the live OpenAI, Anthropic and LM Studio calls; anything needing Ollama locally (CI covers it via `live.yml`); public-DNS link tests in the sandbox (CI `network.yml` covers them).
- **Where these live:** `docs/pod/` on main (this file and `decision-log.md`). They are working records of the autonomous pod, not product docs, and are safe to delete when no longer wanted. They are a snapshot; later pod entries may be added in follow-up PRs.
