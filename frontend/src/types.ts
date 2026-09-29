// Data model mirrors architecture-decisions-A-B.md — do not rename fields
// here without updating that doc first (backend/models/* is the other side
// of this contract).

export type RiskLevel = 'High' | 'Medium' | 'Low';
export type Confidence = '高' | '中' | '低';
export type ChangeType = '新增' | '刪除' | '修改';
export type DataOrigin = 'computed' | 'ai_inferred' | 'demo_seed';
export type StorageTag = '本機' | '未同步' | '已同步';
export type HumanVerdict = 'CONFIRMED' | 'TRACK' | 'REJECTED' | 'FALSE_POSITIVE';
// P3's ReviewBar only ever offers these three — §6's "誤報" (FALSE_POSITIVE)
// is P8 visual-diff's third verdict option, not available here.
export type ReviewVerdict = Exclude<HumanVerdict, 'FALSE_POSITIVE'>;
export type EventType = 'AI_INITIAL' | 'HUMAN_REVIEW' | 'RISK_OVERRIDE' | 'EXPORT_SIGNOFF' | 'CHAIN_REVIEW';

// §22: dual page numbers — never guessed. label_source stays 'unknown' (not
// a fabricated page label) when PDF PageLabels can't be resolved.
export interface PageRef {
  pdf_page: number | null;
  print_label: string | null;
  label_source: 'page_labels' | 'inferred' | 'unknown';
}

export interface SourceSpan {
  page: PageRef;
  text: string;
}

// P5 W7a — the model's proposed reading of a `default`-rule residual,
// attached only via POST /{id}/semantic-preview (never persisted to
// differences.json). Never authoritative: ai_risk/rule_id are untouched by
// whatever this says.
export type SemanticChangeType =
  | 'clarification'
  | 'scope_narrowing'
  | 'scope_widening'
  | 'procedure_change'
  | 'responsibility_shift'
  | 'no_semantic_change'
  | 'unclear';

export interface AiSemanticSuggestion {
  semantic_change_type: SemanticChangeType;
  suggest_escalate: boolean;
  suggested_risk: RiskLevel | null;
  rationale: string;
}

// P5 §26 — one pixel-diff region on an engineering-drawing page. bbox is in
// the rasterized page image's own pixel coordinates (backend.services.
// drawing_diff), not PDF points.
export interface DrawingRegion {
  bbox: [number, number, number, number];
  old_crop_png_b64: string | null;
  new_crop_png_b64: string | null;
  component_label: string | null;
  change_summary: string | null;
  confidence: number | null;
}

// One row of differences.json (immutable once written by the compare step).
// `kind` discriminates text differences (comparison.py) from P5 §26
// engineering-drawing differences (drawing_diff.py) — a difference missing
// `kind` entirely (sessions created before P5) is always a text difference.
export interface DifferenceRecord {
  id: string;
  kind?: 'text' | 'drawing';
  change_type: ChangeType;
  ai_risk: RiskLevel;
  ai_confidence: Confidence;
  explanation: string;
  affected: string;
  recommended_action: string;
  old: SourceSpan | null;
  new: SourceSpan | null;
  ruleset_version: string | null;
  rule_id: string | null;
  component_ref?: string | null; // §28 — best-effort AI-read label for `kind: "drawing"`, still reserved for a real taxonomy otherwise
  data_origin: DataOrigin;
  ai_semantic_suggestion?: AiSemanticSuggestion | null;
  // `kind: "drawing"` only:
  page_alignment?: 'matched' | 'unmatched_old' | 'unmatched_new' | 'size_mismatch';
  regions?: DrawingRegion[];
}

// Fold of review_events.jsonl for one difference_id — NEVER a mutable field
// on DifferenceRecord itself (architecture-decisions-A-B.md §21).
export interface ReviewState {
  difference_id: string;
  ai_risk_at_time: RiskLevel | null;
  ruleset_version: string | null;
  human_verdict: HumanVerdict | null;
  risk_override: RiskLevel | null;
  reviewer_name: string | null;
  approval_role_code: string | null;
  approval_role_label_snapshot: string | null;
  reviewer_note: string | null;
  last_event_id: string | null;
  last_event_type: EventType | null;
}

// What the client actually sends to POST /api/sessions/{id}/review-events —
// event_type/approval_role_label_snapshot are server-determined, never
// client-supplied (backend/api/sessions.py::ReviewEventRequest).
export interface ReviewEventSubmission {
  difference_id: string;
  human_verdict: ReviewVerdict;
  reviewer_name: string;
  approval_role_code: string;
  reviewer_note?: string;
  risk_override?: RiskLevel | null;
}

// 覆核 Agent (plimsoll-review-agent-spec.md §4). Everything here has already
// been verified server-side (backend/services/agent/verify.py): citations
// match the page text verbatim, numbers match their quotes, glossary entries
// come from the reviewed glossary. Anything that failed is in `pending`.
export interface AgentCitation {
  // null = the comparison on screen; otherwise an earlier chain version or a
  // historical case — not jumpable in the current viewer.
  session_id: string | null;
  version_label: string | null;
  difference_id: string | null;
  side: 'old' | 'new';
  pdf_page: number;
  print_label: string | null;
  quote: string;
}

export type AgentAction = '重新檢查' | '補充測試' | '停用舊版' | '更新文件' | '僅存檔';

export interface AgentWarning {
  kind: 'missing_metadata' | 'low_confidence' | 'unsupported' | 'suspicious_instruction';
  message: string;
  citations: AgentCitation[];
  source: 'system' | 'agent';
}

export interface AgentPriority {
  difference_id: string;
  reason: string;
  citations: AgentCitation[];
}

export interface AgentItem {
  difference_ids: string[];
  impact: { equipment: string[]; parts: string[]; procedures: string[]; inspections: string[] };
  action: AgentAction;
  action_detail: string;
  confidence: 'high' | 'medium' | 'low';
  citations: AgentCitation[];
}

export interface AgentSuggestion {
  difference_id: string;
  verdict: 'CONFIRMED' | 'TRACK' | 'REJECTED';
  reason: string;
  citations: AgentCitation[];
}

export interface AgentCauseTrace {
  parameter: string;
  changed_in_version: string;
  reason: string; // 「文件未載明」 when the documents don't say
  citations: AgentCitation[];
}

export interface AgentHistoryCase {
  session_id: string;
  difference_id: string;
  title: string | null;
  versions: string;
  note: string;
  citations: AgentCitation[];
}

export interface AgentPending {
  topic: string;
  reason: string;
}

export interface AgentGlossaryEntry {
  term: string;
  definition: string;
}

export interface AgentBriefing {
  summary: string;
  warnings: AgentWarning[];
  priority: AgentPriority[];
  items: AgentItem[];
  suggestions: AgentSuggestion[];
  cause_trace: AgentCauseTrace[];
  history: AgentHistoryCase[];
  pending: AgentPending[];
  glossary: AgentGlossaryEntry[];
  verification: Record<string, number>;
}

export interface AgentAnswer {
  answer_type: 'answer' | 'not_in_documents' | 'out_of_scope';
  text: string;
  citations: AgentCitation[];
  pending: AgentPending[];
  glossary: AgentGlossaryEntry[];
  verification: Record<string, number>;
}

export interface AgentStep {
  label: string;
  tool: string;
  ok: boolean;
}

export interface AgentRun<R = AgentBriefing | AgentAnswer> {
  run_id: string;
  kind: 'briefing' | 'question';
  question: string | null;
  status: 'running' | 'done' | 'failed';
  steps: AgentStep[];
  result: R | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AgentStatus {
  available: boolean;
  reason: string | null;
  model: string;
}

export interface AgentLatest {
  briefing: AgentRun<AgentBriefing> | null;
  answers: AgentRun<AgentAnswer>[];
  running: AgentRun[];
}

// data/store/config/glossary/v{N}.json as served by GET /api/config/glossary
// (repo `sources` stripped server-side). `status` is per term (pending =
// 待確認) and per table (draft until a human approves it).
export interface GlossaryTerm {
  term: string;
  aliases: string[];
  category: string;
  definition: string;
  status: 'draft' | 'pending' | 'approved';
}

export interface Glossary {
  version: string | null;
  status: 'draft' | 'approved' | null;
  reviewed_at: string | null;
  terms: GlossaryTerm[];
}

export interface ApprovalRole {
  code: string;
  label_zh: string;
  label_en: string;
  is_active: boolean;
  sort_order: number;
  is_system_seed: boolean;
  custom_role_label?: string | null;
}

export interface DocMetadata {
  title: string | null;
  version: string | null;
  date: string | null;
  applicable_equipment: string | null;
  page_count: number;
  size_bytes: number;
  is_complete: boolean;
  missing_fields: string[];
}

// Response shape of POST /api/sessions — same endpoint for both the
// "just dropped two files" inspection step and the "info complete, go"
// creation step (backend/services/session_store.py::process_upload).
export interface SessionInspection {
  status: 'needs_info';
  old_meta: DocMetadata;
  new_meta: DocMetadata;
  old_filename: string;
  new_filename: string;
  scanned_old: number[];
  scanned_new: number[];
  data_origin: DataOrigin;
}

// P5 — session-level LLM-involvement knob (docs §25), frozen at creation
// time. Never changes what the deterministic rule engine decided; only how
// widely the semantic layer's `POST /{id}/semantic-preview` casts its net.
export type AnalysisMode = 'rules_first' | 'model_heavy' | 'model_only';

export interface SessionSummary {
  session_id: string;
  title: string;
  old_meta: DocMetadata;
  new_meta: DocMetadata;
  old_filename: string;
  new_filename: string;
  scanned_old: number[];
  scanned_new: number[];
  ruleset_version: string;
  analysis_mode?: AnalysisMode;
  created_at: string;
  status: string;
  differences: DifferenceRecord[];
  review_state: Record<string, ReviewState>;
  storage_tag: StorageTag;
  data_origin: DataOrigin;
}

// P5 term_aliases 核准流程 — one LLM-proposed candidate awaiting approval.
export interface PendingAlias {
  id: string;
  canonical: string;
  variant: string;
  rationale: string;
  source_session_id: string | null;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
}

export type SessionUploadResult = SessionInspection | { status: 'created'; session: SessionSummary };

// Backs the TopBar gear status dot + Settings → 資料來源 → 資料庫同步 (§24).
export interface DataSourceStatus {
  status: 'connected' | 'disconnected' | 'connecting' | 'error';
  target: string | null;
  pending_count: number;
  quarantined_sessions: { session_id: string; reason: string | null }[];
}

export type ThemeMode = 'light' | 'dark' | 'system';
export type HighlightPalette = 'classic' | 'colorblind';

// P3: a DiffCard's page-ref pill ("舊 p.3 → 新 p.3") asks the 原文 tab to jump
// there (ui-spec §3.3).
export interface FocusRequest {
  side: 'old' | 'new';
  pdfPage: number;
}

// P4 — export (ui-spec §3.2 `export` message type + §7 AC4/情境四).
export type ExportFormat = 'html' | 'docx' | 'pdf';

export interface ExportSubmission {
  format: ExportFormat;
  reviewer_name: string;
  approval_role_code: string;
  report_no?: string;
  dept?: string;
  acknowledge_draft?: boolean;
}

// backend/api/sessions.py's 428 body — the exact unreviewed-High list the
// UnreviewedExportGuard modal must show (情境四: 逐項列出).
export interface ExportGuardInfo {
  message: string;
  unreviewed_high: { id: string; explanation: string }[];
}

export type ExportResult = { status: 'guard'; info: ExportGuardInfo } | { status: 'downloaded'; filename: string };

// --------------------------------------------------------------------------
// W5/W6/W8 — chain (multi-version) comparison
// mirrors backend/models/chain.py; see docs/redesign/plimsoll-improvement-
// plan.html §02/§03 for why a chain is adjacent+anchor sessions plus a
// parameter series/drift report, not a re-implementation of comparison.
// --------------------------------------------------------------------------

export interface ChainManifest {
  chain_id: string;
  ordered_versions: string[];
  adjacent_session_ids: string[];
  anchor_session_ids: string[]; // v1→v2 shared with adjacent_session_ids[0]
  ruleset_version: string;
  term_aliases_version: string;
  created_at: string;
}

export interface ParameterPoint {
  version: string;
  value: number;
  unit: string;
  pdf_page: number | null;
  source_text: string; // original wording — never the W4 canonicalized view
}

export interface DriftFinding {
  canonical_param: string;
  series: ParameterPoint[];
  series_length: number;
  direction_consistent: boolean;
  total_delta: number;
  total_delta_ratio: number;
  is_drift: boolean;
  risk: RiskLevel;
  confidence: Confidence;
  rationale: string;
  recommended_action: string;
  rule_id: string;
  first_version: string;
  last_version: string;
}

// Response shape of POST /api/chains and POST /api/chains/demo.
export interface ChainCreateResult {
  chain_id: string;
  manifest: ChainManifest;
  parameter_series: Record<string, ParameterPoint[]>;
  drift_report: DriftFinding[];
}

// Response shape of GET /api/chains/{id} — adds review state, same fold
// shape as a session's (CHAIN_REVIEW is always excluded from it, so this is
// either {} or a single "*" row is never present — see backend/storage/events.py).
export interface ChainSummary extends ChainManifest {
  parameter_series: Record<string, ParameterPoint[]>;
  drift_report: DriftFinding[];
  review_events: Record<string, unknown>[];
  review_state: Record<string, ReviewState>;
}

export interface ChainReviewSubmission {
  human_verdict: ReviewVerdict;
  reviewer_name: string;
  approval_role_code: string;
  reviewer_note?: string;
}
