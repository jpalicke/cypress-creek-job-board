# Documentation

Start with the [README](../README.md) for setup and the commands you can run today.

| Doc | What it covers |
| --- | --- |
| [codebase.md](codebase.md) | Start here if you are new: layout, how the pieces fit, ideas to know, how a card goes |
| [data-model.md](data-model.md) | The fact bank, Posting and Requirement, and the tag alias table (`config/aliases.yaml`) |
| [pipeline.md](pipeline.md) | Each pipeline stage and its rules: posting normalization, the support gate |
| [validators.md](validators.md) | The grounding validators V1 to V14: what each rejects and its known limits |
| [contributing.md](contributing.md) | How we work, quality gates, dependency audit, ABOUTME headers, docs checklist |

## Decision records
| ADR | Decision |
| --- | --- |
| [0001](adr/0001-fact-bank-enums-and-defaults.md) | Fact bank enums, defaults and the bank location |
| [0002](adr/0002-posting-whitespace-and-normalization-order.md) | Posting whitespace rules and normalization order |

## Configuration
- `config/aliases.yaml`: tag alias table, described in [data-model.md](data-model.md#tag-alias-table).
- `facts.private/bank.yaml` (gitignored) or the path in `CYPRESS_CREEK_BANK`: your fact bank.
