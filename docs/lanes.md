# Lanes and what can run in parallel

The issue board is the status. Each card names what it depends on in its "Depends on" section, and a closed issue is a finished card. This page explains how the lanes relate so two contributors (or assistants) can work at once without colliding. It records the shape of the dependencies, not which cards are done.

## Find the cards you can start now
A card is ready when every card in its "Depends on" section is closed. List the open cards and their dependencies:

```bash
gh issue list --state open --limit 100 --json number,title,labels,body
gh issue view 11 --json state,title     # check one dependency
```

## The lanes
| Lane | What it builds | Depends on other lanes? |
| --- | --- | --- |
| A | Foundations: package, hooks, CI, audits | No. Done first. |
| B | Data model and grounding core: fact bank, normalizer, support gate, score, storage | Only A. |
| C | Provider layer: interface, Ollama, budget guard, hosted adapters | B3 (the Posting and Requirement models) for C1. Then only inside lane C. |
| D | Pipeline stages: prompts, extraction, retrieval, entailment, report, draft help | B, and C2 for extraction. D5 is the hub the later lanes wait on. |
| E | Eval harness: sample bank, fixtures, runner, metrics, published run | B1 for E1. Then C2 and D5 for the runner. Mostly a chain inside E. |
| F | Ingestion: SSRF guard, link fetcher, HTML to text, PDF | A2 for F1. F4 waits on the hostile PDF fixtures in E6. |
| G | API and UI | D5, F2 and B6b. G1 to G5 are a chain, G5 also needs E8. |
| H | Discovery: listings, fetch policy, ATS adapters, scoring runs, suggestions | B6a and B6b for H1, F1 for H2. H7 needs D5, H8 needs C2. |

## Which lanes are independent
Independent means two people can work in them at the same time without waiting on each other.
- **Fully independent once lane B is done:** C (provider layer), F (ingestion, up to F3), the start of E (sample bank, E1) and D1 and D3 (prompt builder, candidate retrieval). They touch different packages.
- **Chains inside a lane:** C1 then C2, C3 then C4, C5. F1 then F2 then F3. H2 then H3, H4, H5 then H6 then H7. G1 then G2 then G3 then G4, G5. Inside a chain, take the cards in order.
- **Join points where lanes meet:**
  - C2 (Ollama adapter) is needed by D2, E2, E8 and H8.
  - D2 (extraction) needs C2 and D1, so lanes C and D meet there.
  - D5 (report assembly) is the hub: E2, G1, H7 and D7 all wait on it.
  - F2 (link fetcher) is needed by G2.
  - E6 (hostile PDF fixtures) is needed by F4, so lane F's last card waits on lane E.
  - B6b (storage) is needed by G2 and H1, the two cards that add database tables.
  - E8 (first published run) is needed by G5.

## Avoiding collisions
- Cards in different lanes rarely touch the same code. The files they do share are the doc indexes: `README.md`, `docs/README.md` and `docs/codebase.md`. Rebase on `main` before opening a PR so those merge cleanly.
- Migrations are numbered `.sql` files. Two cards that each add one may pick the same number. Whoever merges second renumbers (see [data-model.md](data-model.md#storage-sqlite-and-migrations)).
- ADR numbers are first come first served. Check `docs/adr/` on `main` just before you open the PR.
- Do not start a card whose dependencies are open, even if the code looks independent. The dependency is there for a reason, usually a type or a rule you would otherwise guess at.
- When a card turns out to depend on something its issue does not list, fix the "Depends on" section on the issue.

See [handoff.md](handoff.md) for the card routine.
