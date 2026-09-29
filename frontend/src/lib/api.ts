import { llmHeaders } from './llmProviders';
import type {
  AgentLatest,
  AgentRun,
  AgentStatus,
  AiSemanticSuggestion,
  AnalysisMode,
  ApprovalRole,
  ChainCreateResult,
  ChainReviewSubmission,
  ChainSummary,
  DataSourceStatus,
  DifferenceRecord,
  ExportResult,
  ExportSubmission,
  Glossary,
  PendingAlias,
  ReviewEventSubmission,
  SessionSummary,
  SessionUploadResult,
} from '../types';

// Thin fetch wrappers. Every call is non-blocking for app boot — P0 startup
// must render immediately in local-only mode (architecture-decisions-A-B.md
// §24(a)); callers treat a failed fetch as "disconnected/未知", never as a
// reason to halt.

async function extractErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.clone().json();
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    // not JSON — fall through to raw text
  }
  return res.text().catch(() => '');
}

async function getJson<T>(path: string, headers?: HeadersInit): Promise<T> {
  const res = await fetch(path, { headers });
  if (!res.ok) throw new Error(await extractErrorDetail(res));
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const res = await fetch(path, { method: 'POST', body, headers });
  if (!res.ok) throw new Error(await extractErrorDetail(res));
  return (await res.json()) as T;
}

export async function getHealth(): Promise<{ status: string }> {
  return getJson('/api/health');
}

export async function getDataSourceStatus(): Promise<DataSourceStatus> {
  return getJson('/api/system/data-source');
}

// Settings → 資料來源 → 完整性告警. The download is a plain link (the demo
// password gate's Basic auth rides along like any same-origin request);
// acknowledging returns the refreshed status so the TopBar dot updates too.
export function quarantinedEventsUrl(sessionId: string): string {
  return `/api/system/quarantine/${encodeURIComponent(sessionId)}/events`;
}

export async function acknowledgeQuarantine(sessionId: string): Promise<DataSourceStatus> {
  return postJson(`/api/system/quarantine/${encodeURIComponent(sessionId)}/acknowledge`);
}

export async function getApprovalRoles(): Promise<ApprovalRole[]> {
  const body = await getJson<{ roles: ApprovalRole[] }>('/api/config/approval-roles');
  return body.roles;
}

export async function getGlossary(): Promise<Glossary> {
  return getJson<Glossary>('/api/config/glossary');
}

// 覆核 Agent — runs are started, then polled (Cloudflare Quick Tunnel can't
// carry SSE). Claude-only: the BYOK headers decide which key the server
// uses, and a non-Claude provider makes the agent unavailable.
export async function getAgentStatus(): Promise<AgentStatus> {
  return getJson('/api/agent/status', llmHeaders());
}

export async function startAgentBriefing(sessionId: string): Promise<AgentRun> {
  return postJson(`/api/sessions/${sessionId}/agent/briefing`, undefined, llmHeaders());
}

export async function askAgent(sessionId: string, question: string): Promise<AgentRun> {
  const headers = new Headers(llmHeaders());
  headers.set('Content-Type', 'application/json');
  return postJson(`/api/sessions/${sessionId}/agent/questions`, JSON.stringify({ question }), headers);
}

export async function getAgentRun(sessionId: string, runId: string): Promise<AgentRun> {
  return getJson(`/api/sessions/${sessionId}/agent/runs/${runId}`);
}

export async function getAgentLatest(sessionId: string): Promise<AgentLatest> {
  return getJson(`/api/sessions/${sessionId}/agent/latest`);
}

export interface VersionOverrides {
  old_version?: string;
  new_version?: string;
  old_date?: string;
  new_date?: string;
}

// Same endpoint for the initial drop-two-files inspection AND the
// fill-in-the-missing-version resubmit — see SessionInspection/
// SessionUploadResult in types.ts.
export async function uploadSession(
  oldFile: File,
  newFile: File,
  overrides: VersionOverrides = {},
  analysisMode: AnalysisMode = 'rules_first',
): Promise<SessionUploadResult> {
  const form = new FormData();
  form.set('old_file', oldFile);
  form.set('new_file', newFile);
  if (overrides.old_version) form.set('old_version', overrides.old_version);
  if (overrides.new_version) form.set('new_version', overrides.new_version);
  if (overrides.old_date) form.set('old_date', overrides.old_date);
  if (overrides.new_date) form.set('new_date', overrides.new_date);
  form.set('analysis_mode', analysisMode);
  // P5 multi-provider BYOK — Stage -1 OCR runs during this call (opt-in,
  // see resolve_ocr_provider()), so the chosen provider/key travels along
  // even though this endpoint's own JSON body has no room for them.
  return postJson('/api/sessions', form, llmHeaders());
}

export interface DemoFixture {
  id: string;
  label: string;
  available: boolean;
}

export async function getDemoFixtures(): Promise<{ fixtures: DemoFixture[] }> {
  return getJson('/api/sessions/demo-fixtures');
}

export async function createDemoSession(
  analysisMode: AnalysisMode = 'rules_first',
  demoId: string = 'main_engine_cooling',
): Promise<SessionUploadResult> {
  const form = new FormData();
  form.set('analysis_mode', analysisMode);
  form.set('demo_id', demoId);
  return postJson('/api/sessions/demo', form, llmHeaders());
}

export interface SessionPages {
  old: { pdf_page: number; print_label: string | null; label_source: string; text: string }[];
  new: { pdf_page: number; print_label: string | null; label_source: string; text: string }[];
}

export async function getSessionPages(sessionId: string): Promise<SessionPages> {
  return getJson(`/api/sessions/${sessionId}/pages`);
}

// P6 成本試算, real-document version — read-only, no LLM call (see
// backend/services/llm/cost_estimate.py's module docstring). One entry per
// AnalysisMode, so the caller can show the full low(rules_first)-high
// (model_only) range regardless of which mode the session is actually set
// to.
export interface CostEstimateModeResult {
  qualifying_count: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
}

export interface CostEstimateResult {
  modes: Record<AnalysisMode, CostEstimateModeResult>;
}

export async function getSessionCostEstimate(sessionId: string): Promise<CostEstimateResult> {
  return getJson(`/api/sessions/${sessionId}/cost-estimate`);
}

/** URL for `<embed>`/`<iframe>` — 原始 PDF 原文模式 (ui-spec §3.3). */
export function sessionPdfUrl(sessionId: string, side: 'old' | 'new'): string {
  return `/api/sessions/${sessionId}/pdf/${side}`;
}

// DiffCard ReviewBar's "確認並前往下一筆" — a denied approval throws with the
// backend's exact 403 message (e.g. "船隊經理 無權核准 High 風險等級的變更").
export async function submitReviewEvent(
  sessionId: string,
  submission: ReviewEventSubmission,
): Promise<{ session: SessionSummary }> {
  return postJson(`/api/sessions/${sessionId}/review-events`, JSON.stringify(submission), {
    'Content-Type': 'application/json',
  });
}

// P5 W7a — opt-in, never called automatically. `semantic_layer_available:
// false` means no LLM key is configured server-side; the caller merges
// `differences` (an ENRICHED COPY, differences.json itself never changes)
// into local UI state, it doesn't replace the session.
export interface SemanticPreviewResult {
  semantic_layer_available: boolean;
  differences: DifferenceRecord[];
}

export async function previewSemanticSuggestions(sessionId: string): Promise<SemanticPreviewResult> {
  return postJson(`/api/sessions/${sessionId}/semantic-preview`, undefined, llmHeaders());
}

// P5 term_aliases 核准流程 — propose candidates from one session's
// clarification-type residuals (queues them; approval happens separately).
export async function suggestAliases(
  sessionId: string,
): Promise<{ semantic_layer_available: boolean; candidates: PendingAlias[] }> {
  return postJson(`/api/sessions/${sessionId}/suggest-aliases`, undefined, llmHeaders());
}

export async function listPendingAliases(
  status: 'pending' | 'approved' | 'rejected' | 'all' = 'pending',
): Promise<PendingAlias[]> {
  const body = await getJson<{ candidates: PendingAlias[] }>(`/api/term-aliases/pending?status=${status}`);
  return body.candidates;
}

export async function approvePendingAlias(pendingId: string, approvedBy: string): Promise<PendingAlias> {
  const body = await postJson<{ candidate: PendingAlias }>(
    `/api/term-aliases/pending/${pendingId}/approve`,
    JSON.stringify({ approved_by: approvedBy }),
    { 'Content-Type': 'application/json' },
  );
  return body.candidate;
}

// P5 Message Batches — chain-level bulk residual re-analysis. Scoped to
// chains (not the single-session semantic-preview button) since the Batch
// API has no fast-turnaround guarantee; see backend/services/llm/
// batch_jobs.py's module docstring.
export interface SubmitBatchResult {
  semantic_layer_available: boolean;
  batch_id?: string | null;
  session_count?: number;
  difference_count?: number;
}

export async function submitSemanticBatch(chainId: string): Promise<SubmitBatchResult> {
  return postJson(`/api/chains/${chainId}/semantic-preview/batch`, undefined, llmHeaders());
}

export interface BatchPollResult {
  status: 'in_progress' | 'completed';
  results?: Record<string, AiSemanticSuggestion | null>;
}

export async function getSemanticBatch(chainId: string, batchId: string): Promise<BatchPollResult> {
  // Polling needs the SAME provider/key the batch was submitted with —
  // Anthropic/Gemini/OpenAI's retrieve/results calls all need a real
  // authenticated client, so this resends the currently-selected
  // credentials every tick rather than relying on anything persisted
  // server-side (nothing is — see resolve_llm_provider()'s docstring).
  return getJson(`/api/chains/${chainId}/semantic-preview/batch/${batchId}`, llmHeaders());
}

export async function rejectPendingAlias(pendingId: string): Promise<PendingAlias> {
  const body = await postJson<{ candidate: PendingAlias }>(`/api/term-aliases/pending/${pendingId}/reject`);
  return body.candidate;
}

// P4 export — 428 means "some High items are unreviewed, show the
// UnreviewedExportGuard modal and resubmit with acknowledge_draft:true";
// any other non-2xx is a real error. On success this triggers a real
// browser download (blob + temporary <a download>) — this is the user's own
// local app, not a sandboxed Artifact, so a plain download link is normal.
export async function exportSession(sessionId: string, submission: ExportSubmission): Promise<ExportResult> {
  const res = await fetch(`/api/sessions/${sessionId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(submission),
  });

  if (res.status === 428) {
    const body = await res.json();
    return { status: 'guard', info: body.detail };
  }
  if (!res.ok) {
    throw new Error(await extractErrorDetail(res));
  }

  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') ?? '';
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const filename = match ? match[1] : `plimsoll-export.${submission.format}`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);

  return { status: 'downloaded', filename };
}

// --------------------------------------------------------------------------
// W5/W6/W8 — chain endpoints
// --------------------------------------------------------------------------

// `files` must be in version order (v1 first) — backend/api/chains.py never
// guesses order, same "never guess" rule as a pairwise session's version field.
export async function createChain(files: File[]): Promise<ChainCreateResult> {
  const form = new FormData();
  for (const file of files) form.append('files', file);
  return postJson('/api/chains', form);
}

export async function createDemoChain(): Promise<ChainCreateResult> {
  return postJson('/api/chains/demo');
}

export async function getChain(chainId: string): Promise<ChainSummary> {
  return getJson(`/api/chains/${chainId}`);
}

export async function submitChainReview(
  chainId: string,
  submission: ChainReviewSubmission,
): Promise<{ event: Record<string, unknown>; chain: ChainSummary }> {
  return postJson(`/api/chains/${chainId}/review-events`, JSON.stringify(submission), {
    'Content-Type': 'application/json',
  });
}
