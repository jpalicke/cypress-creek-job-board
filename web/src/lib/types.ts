// ABOUTME: Types of the API answers, generated from the pydantic models. Do not edit.
// ABOUTME: Regenerate with `uv run python scripts/gen_api_types.py`; a unit test checks it.

export interface AnalyzeRequest {
  backend: string;
  confirm_hosted: boolean;
}

export interface AnalyzeResponse {
  report_id: string;
  report: GapReport;
}

export interface BackendHealth {
  provider: string;
  model: string;
  reachable: "reachable" | "unreachable" | "not_checked";
}

export interface CitedFact {
  id: string;
  claim: string;
}

export interface CostResponse {
  input: number;
  output: number;
}

export type DraftStatus = "drafted" | "no_support" | "not_run";

export type DropReason = "text_not_in_posting" | "duplicate_term" | "invalid_field";

export interface Dropped {
  text: string;
  reason: DropReason;
}

export type Entailment = "confirmed" | "downgraded" | "not_run" | "not_needed";

export interface EstimateResponse {
  covers: "extraction";
  requests: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
}

export interface Evidence {
  type: EvidenceType;
  pointer: string;
}

export type EvidenceType = "employer_doc" | "repo" | "certificate" | "public_url" | "self_attested";

export interface ExtractionWarning {
  kind: string;
  count: number;
}

export interface Fact {
  id: string;
  claim: string;
  kind: Kind;
  employer: string | null;
  issuer: string | null;
  role: string | null;
  start: string | null;
  end: string | null;
  tags: Tag[];
  verified_on: string | null;
  evidence: Evidence;
  share: Share;
}

export interface FactDraft {
  claim: string;
  kind: Kind;
  employer: string | null;
  issuer: string | null;
  role: string | null;
  start: string | null;
  end: string | null;
  tags: Tag[];
  evidence: Evidence;
}

export interface FactsResponse {
  facts: Fact[];
  unverified_ids: string[];
}

export interface GapReport {
  posting_id: string;
  status: ReportStatus;
  incomplete_reasons: string[];
  rows: ReportRow[];
  gaps: string[];
  not_assessed_count: number;
  not_assessed: NotAssessedSentence[];
  dropped: Dropped[];
  warnings: PostingWarning[];
  score: ScoreResult | null;
  score_disclaimer: string;
  rule_only_ids: string[];
  provenance: Provenance;
}

export type Gate = "no_candidate" | "familiar_level" | "no_dates" | "years_below" | "years_met" | "term_match";

export interface HealthResponse {
  status: "ok";
  backends: BackendHealth[];
}

export type Importance = "required" | "preferred" | "unspecified";

export type Kind = "employment" | "project" | "education" | "certification" | "achievement";

export type Level = "familiar" | "working" | "expert";

export interface NotAssessedSentence {
  reason: "cue_sentence_uncovered";
  text: string;
  span: [number, number];
}

export interface PostingRequest {
  source: "paste" | "link";
  text: string | null;
  url: string | null;
}

export interface PostingResponse {
  id: string;
  source: PostingSource;
  text: string;
  text_hash: string;
  origin_url: string | null;
  warnings: PostingWarning[];
  extraction_warnings: ExtractionWarning[];
  fetch_warnings: string[];
  created_at: string;
}

export type PostingSource = "paste" | "link" | "pdf" | "feed";

export interface PostingWarning {
  kind: WarningKind;
  count: number;
}

export interface Provenance {
  backend: string;
  model: string;
  run_id: string;
  prompt_hashes: Record<string, string>;
  usage: Usage;
}

export interface ProviderInfo {
  provider: string;
  model: string;
  local: boolean;
  strict_schema: boolean;
  context_tokens: number;
  cost_per_mtok: CostResponse;
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
}

export interface RemovedResponse {
  removed: boolean;
}

export interface ReportResponse {
  report_id: string;
  posting_id: string;
  created_at: string;
  report: GapReport;
  validator_verdicts: StoredVerdict[];
}

export interface ReportRow {
  requirement_id: string;
  text: string;
  importance: Importance;
  ceiling: Support;
  support: Support;
  gate: Gate;
  fact_ids: string[];
  rationale: string | null;
  entailment: Entailment;
  not_model_checked: boolean;
  failure: string | null;
  span: [number, number] | null;
  raise_attempted: boolean;
}

export type ReportStatus = "complete" | "incomplete";

export interface ScoreInputs {
  weights: Weights;
  lines: ScoreLine[];
}

export interface ScoreLine {
  requirement_id: string;
  importance: Importance;
  support: Support;
  weight: number;
  value: number;
}

export interface ScoreResult {
  score: number | null;
  supported: number;
  total: number;
  counts: Record<string, number>;
  inputs: ScoreInputs;
}

export interface SentenceOut {
  text: string;
  fact_ids: string[];
  passed: boolean;
  verdicts: VerdictOut[];
}

export interface SessionResponse {
  csrf_token: string;
}

export type Share = "shareable" | "local_only";

export interface ShareRequest {
  share: Share;
}

export interface StoredVerdict {
  stage: string;
  subject: string;
  validator: string;
  passed: boolean;
  reason: string;
}

export interface SuggestionRequest {
  requirement_id: string;
  backend: string;
  confirm_hosted: boolean;
}

export interface SuggestionResponse {
  requirement_id: string;
  requirement_text: string;
  status: DraftStatus;
  failure: string | null;
  needs_human_review: boolean;
  sentences: SentenceOut[];
  facts: CitedFact[];
}

export type Support = "none" | "partial" | "strong";

export interface Tag {
  name: string;
  level: Level;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
}

export interface VerdictOut {
  validator: string;
  passed: boolean;
  reason: string;
}

export type WarningKind = "control_chars_stripped";

export interface Weights {
  required: number;
  unspecified: number;
  preferred: number;
  strong: number;
  partial: number;
  none: number;
}
