# Documentation

Start with the [README](../README.md) for setup and the commands you can run today.

| Doc | What it covers |
| --- | --- |
| [codebase.md](codebase.md) | Start here if you are new: layout, how the pieces fit, ideas to know, how a card goes |
| [data-model.md](data-model.md) | The fact bank, Posting and Requirement, and the tag alias table (`config/aliases.yaml`) the company name key (`company_key`) and the SQLite storage and migrations |
| [pipeline.md](pipeline.md) | Each pipeline stage and its rules: posting normalization, the prompt builder (extraction and entailment prompts), accepting extraction output, stage 1 extraction, stage 2 retrieval, stage 3 entailment, stages 4 and 5 score and report, running the pipeline and the derived run id, the support gate, the score |
| [validators.md](validators.md) | The grounding validators V1 to V14: what each rejects and its known limits |
| [providers.md](providers.md) | The provider interface, typed errors, retry policy, backend config, the loopback rule, the Ollama adapter and the budget guard |
| [threat-model.md](threat-model.md) | The prompt structure (T1 to T4), URL target validation, SSRF rules and test coverage, compatibility limits and the pending HTTP transport |
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
| [0007](adr/0007-provider-config-toml-and-loopback.md) | Provider config as TOML plus environment overrides, remote hosts are opt in |
| [0008](adr/0008-ollama-truncation-signature-and-window-floor.md) | How the Ollama adapter detects silent truncation, and the 2048 window floor |
| [0009](adr/0009-url-target-validation.md) | Public URL targets, strict hostname syntax and validation of every resolved address |
| [0010](adr/0010-extraction-stage-design.md) | How stage 1 extraction trusts the model: code sets spans and importance, failures are incomplete |
| [0011](adr/0011-entailment-can-only-lower-support.md) | How stage 3 entailment can change support: the lower of ceiling and verdict, citations required, rationale display only |
| [0012](adr/0012-report-fails-closed-and-cites.md) | How the gap report is built: fails closed, incomplete when a stage failed, every claim cites or the report is refused |
| [0013](adr/0013-run-id-is-derived-from-the-inputs.md) | The run id is a hash of the posting, the fact bank, the backend and the model |

## Configuration
- `config/aliases.yaml`: tag alias table, described in [data-model.md](data-model.md#tag-alias-table).
- `config/weights.yaml`: score weights and support values, described in [pipeline.md](pipeline.md#score).
- `config/confusables.txt`: Unicode confusables data (do not hand edit), used for company names and described in [data-model.md](data-model.md#company-names-company_key).
- `CYPRESS_CREEK_DATA_DIR` (default `data/`, gitignored): where the SQLite database lives, described in [data-model.md](data-model.md#storage-sqlite-and-migrations).
- `config/provider.toml` (or the file named by `CYPRESS_CREEK_CONFIG`) and `CYPRESS_CREEK_<FIELD>` variables: which model backend to use and the run budget limits, described in [providers.md](providers.md#configuration). API keys are read only from the environment variable the file names.
- `facts.private/bank.yaml` (gitignored) or the path in `CYPRESS_CREEK_BANK`: your fact bank.

URL target validation has no configuration or environment override. In particular, the provider's `allow_remote` setting does not relax the URL guard's public-address rule.
