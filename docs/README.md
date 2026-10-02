# Documentation

Start with the [README](../README.md) for setup and the commands you can run today.

| Doc | What it covers |
| --- | --- |
| [codebase.md](codebase.md) | Start here if you are new: layout, how the pieces fit, ideas to know, how a card goes |
| [data-model.md](data-model.md) | The fact bank, Posting and Requirement, and the tag alias table (`config/aliases.yaml`) the company name key (`company_key`) and the SQLite storage and migrations |
| [pipeline.md](pipeline.md) | Each pipeline stage and its rules: posting normalization, the support gate, the score |
| [validators.md](validators.md) | The grounding validators V1 to V14: what each rejects and its known limits |
| [providers.md](providers.md) | The provider interface, the six typed errors and the retry policy |
| [spec.md](spec.md) | The full design spec: goals, architecture, data model, pipeline, providers, validators, evals, threat model, discovery, ingestion, UI, testing and the card plan |
| [lanes.md](lanes.md) | How the lanes depend on each other and which can be worked in parallel |
| [handoff.md](handoff.md) | The card routine step by step, for a new contributor or assistant picking up a card |
| [contributing.md](contributing.md) | How we work, quality gates, dependency audit, ABOUTME headers, docs checklist |

## Decision records
| ADR | Decision |
| --- | --- |
| [0001](adr/0001-fact-bank-enums-and-defaults.md) | Fact bank enums, defaults and the bank location |
| [0002](adr/0002-posting-whitespace-and-normalization-order.md) | Posting whitespace rules and normalization order |
| [0003](adr/0003-score-formula-and-downgrade-only.md) | Score formula, what supported means, downgrade only |
| [0004](adr/0004-company-key-rules.md) | Company key rules, Unicode confusables data, spaces removed |
| [0005](adr/0005-sqlite-and-migrations.md) | SQLite for mutable state, numbered SQL migrations, data directory |
| [0006](adr/0006-issuer-field-and-issuer-matching.md) | Optional issuer on facts and requirements, matched with company_key |

## Configuration
- `config/aliases.yaml`: tag alias table, described in [data-model.md](data-model.md#tag-alias-table).
- `config/weights.yaml`: score weights and support values, described in [pipeline.md](pipeline.md#score).
- `config/confusables.txt`: Unicode confusables data (do not hand edit), used for company names and described in [data-model.md](data-model.md#company-names-company_key).
- `CYPRESS_CREEK_DATA_DIR` (default `data/`, gitignored): where the SQLite database lives, described in [data-model.md](data-model.md#storage-sqlite-and-migrations).
- `facts.private/bank.yaml` (gitignored) or the path in `CYPRESS_CREEK_BANK`: your fact bank.
