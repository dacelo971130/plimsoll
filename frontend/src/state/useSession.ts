import { useEffect, useState } from 'react';
import { createDemoSession, getApprovalRoles, getDataSourceStatus, uploadSession } from '../lib/api';
import type {
  AnalysisMode,
  ApprovalRole,
  DataSourceStatus,
  FocusRequest,
  SessionInspection,
  SessionSummary,
  SessionUploadResult,
} from '../types';

const RAIL_STORAGE_KEY = 'plimsoll.rails.v1';

export const RIGHT_WIDTH_RANGE = { min: 320, max: 640 };

interface RailState {
  rightCollapsed: boolean;
  rightWidth: number;
}

const DEFAULT_RAIL_STATE: RailState = {
  // Starts collapsed — before any comparison exists there is nothing for it
  // to show (KPI/差異清單/匯出 all need a session), so a default-open panel
  // just reads as "why is this here" (user feedback). It auto-opens itself
  // the moment a session actually lands — see the effect below — so this
  // only affects the very first render / a reset localStorage.
  rightCollapsed: true,
  rightWidth: 420,
};

function clamp(value: number, range: { min: number; max: number }): number {
  return Math.min(range.max, Math.max(range.min, value));
}

function loadRailState(): RailState {
  try {
    const raw = localStorage.getItem(RAIL_STORAGE_KEY);
    if (!raw) return DEFAULT_RAIL_STATE;
    const parsed = { ...DEFAULT_RAIL_STATE, ...(JSON.parse(raw) as Partial<RailState>) };
    parsed.rightWidth = clamp(parsed.rightWidth, RIGHT_WIDTH_RANGE);
    return parsed;
  } catch {
    return DEFAULT_RAIL_STATE;
  }
}

const DISCONNECTED_STATUS: DataSourceStatus = {
  status: 'disconnected',
  target: null,
  pending_count: 0,
  quarantined_sessions: [],
};

export type UploadStatus = 'empty' | 'busy' | 'needs_info' | 'created' | 'error';

export interface VersionOverrideFields {
  old_version: string;
  new_version: string;
  old_date: string;
  new_date: string;
}

const EMPTY_OVERRIDES: VersionOverrideFields = { old_version: '', new_version: '', old_date: '', new_date: '' };

/** P1: file staging + upload/inspect/create flow, plus the P0 session
 * container (rails, DB status, approval roles). One hook because "session"
 * and "the thing that produces a session" are the same lifecycle. */
export function useSession() {
  const [rails, setRails] = useState<RailState>(() => loadRailState());
  const [dataSourceStatus, setDataSourceStatus] = useState<DataSourceStatus>(DISCONNECTED_STATUS);
  const [approvalRoles, setApprovalRoles] = useState<ApprovalRole[]>([]);

  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [overrides, setOverrides] = useState<VersionOverrideFields>(EMPTY_OVERRIDES);
  const [inspection, setInspection] = useState<SessionInspection | null>(null);
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>('empty');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<FocusRequest | null>(null);
  const [activeDifferenceId, setActiveDifferenceId] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(RAIL_STORAGE_KEY, JSON.stringify(rails));
  }, [rails]);

  // Auto-reveal the right panel the moment a session actually appears.
  // Keyed on session_id (not `session` itself) so an in-place update to the
  // SAME session (e.g. RightPanel's onSessionUpdate after a review event)
  // never fights a right-panel collapse the user made deliberately mid-review.
  useEffect(() => {
    if (session) setRails((prev) => (prev.rightCollapsed ? { ...prev, rightCollapsed: false } : prev));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.session_id]);

  useEffect(() => {
    // Background, non-blocking probes — a failed fetch just leaves the
    // grey/disconnected default in place (§24(a): never block the shell).
    getDataSourceStatus().then(setDataSourceStatus).catch(() => undefined);
    getApprovalRoles().then(setApprovalRoles).catch(() => undefined);
  }, []);

  // Exposed so AppShell can also reveal the right panel when a CHAIN loads
  // (chain state lives in useChain, a separate hook — this hook only knows
  // about its own `session`, hence the effect above never fires for a
  // chain-only load). Same "only open, never fight a deliberate collapse"
  // rule as the effect above.
  function openRight() {
    setRails((prev) => (prev.rightCollapsed ? { ...prev, rightCollapsed: false } : prev));
  }

  function toggleRight() {
    setRails((prev) => ({ ...prev, rightCollapsed: !prev.rightCollapsed }));
  }

  function setRightWidth(width: number) {
    setRails((prev) => ({ ...prev, rightWidth: clamp(width, RIGHT_WIDTH_RANGE) }));
  }

  function _applyResult(result: SessionUploadResult) {
    if (result.status === 'created') {
      setSession(result.session);
      setInspection(null);
      setUploadStatus('created');
    } else {
      setInspection(result);
      setUploadStatus('needs_info');
    }
  }

  async function submitComparison(analysisMode: AnalysisMode = 'rules_first') {
    if (!oldFile || !newFile) return;
    setUploadStatus('busy');
    setUploadError(null);
    try {
      const result = await uploadSession(
        oldFile,
        newFile,
        {
          old_version: overrides.old_version || undefined,
          new_version: overrides.new_version || undefined,
          old_date: overrides.old_date || undefined,
          new_date: overrides.new_date || undefined,
        },
        analysisMode,
      );
      _applyResult(result);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
      setUploadStatus('error');
    }
  }

  async function loadDemo(analysisMode: AnalysisMode = 'rules_first', demoId: string = 'main_engine_cooling') {
    setUploadStatus('busy');
    setUploadError(null);
    try {
      _applyResult(await createDemoSession(analysisMode, demoId));
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
      setUploadStatus('error');
    }
  }

  function resetUpload() {
    setOldFile(null);
    setNewFile(null);
    setOverrides(EMPTY_OVERRIDES);
    setInspection(null);
    setSession(null);
    setUploadStatus('empty');
    setUploadError(null);
    setFocusRequest(null);
    setActiveDifferenceId(null);
  }

  function updateOverride<K extends keyof VersionOverrideFields>(key: K, value: VersionOverrideFields[K]) {
    setOverrides((prev) => ({ ...prev, [key]: value }));
  }

  /** DiffCard page-ref pill -> center stage viewer (ui-spec §3.3, now living
   * in the main column instead of a collapsible side panel — nothing to
   * un-collapse for the center; the viewer is always there). Optionally also
   * marks which difference to flash-highlight once that page renders. */
  function jumpToPage(side: 'old' | 'new', pdfPage: number | null, differenceId?: string) {
    if (pdfPage == null) return;
    setFocusRequest({ side, pdfPage });
    if (differenceId) setActiveDifferenceId(differenceId);
  }

  return {
    session,
    rails,
    toggleRight,
    openRight,
    setRightWidth,
    dataSourceStatus,
    setDataSourceStatus,
    approvalRoles,
    // upload flow
    oldFile,
    newFile,
    setOldFile,
    setNewFile,
    overrides,
    updateOverride,
    inspection,
    uploadStatus,
    uploadError,
    submitComparison,
    loadDemo,
    resetUpload,
    setSession,
    focusRequest,
    jumpToPage,
    activeDifferenceId,
    setActiveDifferenceId,
  };
}
