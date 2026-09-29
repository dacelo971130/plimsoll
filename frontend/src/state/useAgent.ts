import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { askAgent, getAgentLatest, getAgentRun, getAgentStatus, startAgentBriefing } from '../lib/api';
import type { AgentAnswer, AgentBriefing, AgentItem, AgentRun, AgentStatus, AgentSuggestion } from '../types';

const POLL_MS = 1000;

/** What one difference card needs from the latest briefing. */
export interface AgentNote {
  runId: string;
  items: AgentItem[];
  suggestion: AgentSuggestion | null;
}

// 覆核 Agent state for the open session (spec §4). Runs are polled, not
// streamed — Cloudflare Quick Tunnel can't carry SSE. `status` decides
// whether the entry points exist at all (不做假的: no disabled button
// standing in for a missing key); past results still show without it.
export function useAgent(sessionId: string | null) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [briefing, setBriefing] = useState<AgentRun<AgentBriefing> | null>(null);
  const [answers, setAnswers] = useState<AgentRun<AgentAnswer>[]>([]);
  const [active, setActive] = useState<AgentRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;

  const refreshStatus = useCallback(() => {
    getAgentStatus()
      .then(setStatus)
      .catch(() => setStatus({ available: false, reason: '無法確認 Agent 狀態。', model: '' }));
  }, []);

  useEffect(() => {
    setBriefing(null);
    setAnswers([]);
    setActive(null);
    setError(null);
    if (!sessionId) return;
    refreshStatus();
    getAgentLatest(sessionId)
      .then((latest) => {
        if (sessionRef.current !== sessionId) return;
        setBriefing(latest.briefing);
        setAnswers(latest.answers);
        setActive(latest.running[0] ?? null);
      })
      .catch(() => undefined);
  }, [sessionId, refreshStatus]);

  // Poll the one active run until it settles, then file its result.
  useEffect(() => {
    if (!sessionId || !active || active.status !== 'running') return;
    const timer = window.setTimeout(() => {
      getAgentRun(sessionId, active.run_id)
        .then((run) => {
          if (sessionRef.current !== sessionId) return;
          if (run.status === 'running') {
            setActive(run);
            return;
          }
          setActive(null);
          if (run.status === 'failed') {
            setError(run.error ?? 'Agent 執行失敗。');
          } else if (run.kind === 'briefing') {
            setBriefing(run as AgentRun<AgentBriefing>);
          }
          if (run.kind === 'question') setAnswers((prev) => [...prev, run as AgentRun<AgentAnswer>]);
        })
        .catch((err) => {
          setActive(null);
          setError(err instanceof Error ? err.message : String(err));
        });
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [sessionId, active]);

  const start = useCallback(
    async (launch: () => Promise<AgentRun>) => {
      setError(null);
      try {
        setActive(await launch());
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        refreshStatus();
      }
    },
    [refreshStatus],
  );

  const startBriefing = useCallback(() => {
    if (sessionId) void start(() => startAgentBriefing(sessionId));
  }, [sessionId, start]);

  const ask = useCallback(
    (question: string) => {
      if (sessionId) void start(() => askAgent(sessionId, question));
    },
    [sessionId, start],
  );

  const notesById = useMemo(() => {
    const notes: Record<string, AgentNote> = {};
    const result = briefing?.result;
    if (!briefing || !result) return notes;
    const noteFor = (id: string) => (notes[id] ??= { runId: briefing.run_id, items: [], suggestion: null });
    for (const item of result.items) for (const id of item.difference_ids) noteFor(id).items.push(item);
    for (const s of result.suggestions) noteFor(s.difference_id).suggestion = s;
    return notes;
  }, [briefing]);

  return {
    available: status?.available ?? false,
    unavailableReason: status?.reason ?? null,
    briefing,
    answers,
    active,
    error,
    startBriefing,
    ask,
    notesById,
    refreshStatus,
  };
}

export type AgentState = ReturnType<typeof useAgent>;
