# Codebase guide

For a developer new to the project. Read the [README](../README.md) first, then this page, then pick up a card from the issue board.

## What the project does, in one paragraph
You give it a job posting. It pulls out the requirements, looks each one up in your personal fact bank (a YAML file of verified claims about your own work), reports honestly where you have no support, and only then helps draft an application. Every claim in the output must cite a verified fact. That is enforced by deterministic code (validators), never by prompting a model to behave. A human reviews every draft and nothing is ever sent automatically.

## The rule that shapes every decision
Nothing the tool outputs may assert a claim that is not backed by a verified fact ID in the fact bank. When you are unsure whether a change is allowed, ask whether it could let an unverified claim through. If so, it is not allowed. Model output is untrusted data until a validator passes it. All external input (postings, PDFs, feeds, model output) is hostile.

## Layout
```
config/                  Data that behaves like code but is edited by hand
  aliases.yaml           Tag alias table (requirement term to canonical tag)
  weights.yaml           Score weights and support values
docs/                    Documentation, indexed in docs/README.md
  adr/                   Decision records, one per design decision
scripts/                 Repo tooling run by hooks and CI (ABOUTME check, license check)
src/cypress_creek/       The library
  terms.py               normalize_term: the one term normalizer
  facts/                 The fact bank
    models.py            Fact, Tag, Evidence, Bank and their enums
    loader.py            Safe YAML loading, parse_bank, load_bank
    dates.py             Date sanity rules
    errors.py            BankLoadError, FactValidationError
  ingest/                Untrusted posting text in, clean models out
    models.py            Posting, Requirement, typed warnings
    normalize.py         normalize(), text_hash()
    hashing.py           The one definition of the text hash
    errors.py            PostingTooLong, EmptyPosting
  validators/            Grounding validators V1 to V14, pure functions returning Verdicts
    verdict.py           Verdict, ok(), fail()
    cues.py              The one list of importance cue words, sentence splitting
    extraction.py        V1 schema, V2 verbatim span, V3 importance cues
    citations.py         V4 fact exists, V5 fact verified, V6 fact shareable
    consistency.py       V7 entity consistency, V8 numeric consistency
    claims.py            V9 citation required, V10 novel term flag
    requirements.py      V11 cap and dedupe, V13 cue sentence coverage
    fact_dates.py        V12 date sanity (wraps facts/dates.py)
    names.py             V14 company name shape
    registry.py          REGISTRY: id, name, rule and function for each validator
  scoring/               Deterministic scoring, no model calls
    aliases.py           AliasTable, load_aliases
    support.py           candidate_facts, merged_years, support_ceiling
    score.py             Weights, load_weights, Match, downgrade, score, ScoreResult
tests/
  unit/                  Pure functions and models, no I/O beyond tmp files
  component/             Real files and real environment, several modules together
  integration/           Real services (empty so far)
  e2e/                   Whole flows (empty so far)
  fixtures/              Recorded or hand written inputs
    hostile_outputs/     One bad model output per validator, plus a small bank (see validators.md)
  conftest.py            Fails the run if any test is skipped
```
`facts.private/` is where your own bank lives. It is gitignored and never committed.

## How the pieces fit today
```mermaid
flowchart LR
    raw[Raw posting text] --> norm["ingest.normalize()"]
    norm --> posting[Posting]
    posting -. later cards .-> reqs[Requirements]
    bank[(facts.private/bank.yaml)] --> load["facts.load_bank()"]
    load --> verified["Bank.verified_facts()"]
    aliases[(config/aliases.yaml)] --> table[AliasTable]
    reqs --> gate["scoring.support_ceiling()"]
    verified --> gate
    table --> gate
    gate --> ceiling["support + deciding gate"]
    ceiling --> score["scoring.score()"]
    score --> result["score, supported of total, inputs"]
    reqs -. model output .-> val["validators (V1 to V14)"]
```
Dotted means not built yet. Extraction, model verdicts, validators, gap reports and drafting arrive in later cards (see the issue board and the spec). The pieces that exist are libraries with no app around them yet.

## Ideas to know
- **One source of truth.** The bank file is the only record of facts. Verification is derived from `verified_on` and is never stored as a separate flag. The pipeline only ever sees `Bank.verified_facts()`.
- **Pure and deterministic.** Scoring functions take everything as arguments, including `today`. Nothing reads the clock or the network.
- **Data, not code.** Things a person should tune (the alias table, the score weights) are YAML in `config/`, loaded and validated, never hard coded.
- **Typed errors.** Failures are specific exception classes (`PostingTooLong`, `FactValidationError`), so callers and tests can tell them apart. Text is rejected, never silently cut or repaired.
- **Frozen models.** Pydantic models are frozen and reject unknown fields, so a typo or smuggled field is an error.
- **Shared normalization.** `terms.normalize_term` is used for bank tags, requirement terms and the alias table, so they always compare under the same rules.

## Working in the repo
Setup and the quality gates are in [contributing.md](contributing.md). In short:

```bash
uv sync
uv run pre-commit install
uv run pytest                      # all tests
uv run pre-commit run --all-files  # lint, format, strict types, tests with the 80% coverage gate
```

How a card goes:
1. Branch from main, one branch per card. No worktrees.
2. Write a failing test first and watch it fail. Then write the minimum code to pass, then refactor.
3. Keep each phase to at most five files and each PR to about 10 (hard cap 20), run the gates, then continue.
4. Update docs in the same PR (see the checklist in contributing.md).
5. Open a PR, get CI green, merge only after review.

Conventions you will trip over if you do not know them:
- Every code file starts with two comment lines beginning `ABOUTME: `. A hook checks it.
- No mocks, fake providers or stubbed HTTP. Use real files and real services, or recorded real outputs as inputs. An unreachable service fails the test, it never skips.
- Test output must be clean. Warnings are errors, and a skipped test fails the run.
- Names are evergreen: never "new", "improved" or "enhanced".
- No em dashes anywhere, including comments and commit messages.
- Do not mention any employer or industry in the repo.
- Never bypass hooks with `--no-verify`.
- Ports: API 5309, Vite dev server 5150. Infrastructure keeps its defaults.

## Adding a new thing, by example
- **Different score weights:** edit `config/weights.yaml`. `tests/component/test_weights_loader.py` shows the rules, and `docs/pipeline.md#score` must match if you change the defaults.
- **A new tag alias:** add it to `config/aliases.yaml`. The tests in `tests/unit/test_aliases.py` show the rules (an alias belongs to one canonical tag).
- **A new fact field:** change `facts/models.py`, add a failing test in `tests/unit/test_fact_models.py` first, write an ADR if it is a design decision, and update `docs/data-model.md`.
- **A new pipeline stage:** a new module under the right package, typed errors beside it, tests in all relevant tiers, and a section in `docs/pipeline.md`.

## Where to look when something is unclear
The spec (linked from the issue board) is the design. The card's issue is the task. `CLAUDE.md` is the binding rules. `gotchas.md` is the list of past mistakes turned into rules. `docs/adr/` explains why things are the way they are.
