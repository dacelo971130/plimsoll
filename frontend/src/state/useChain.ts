import { useState } from 'react';
import { createChain, createDemoChain, getChain, submitChainReview } from '../lib/api';
import type { ChainReviewSubmission, ChainSummary } from '../types';

export type ChainStatus = 'empty' | 'busy' | 'created' | 'error';

/** W5/W6/W8: chain (multi-version) comparison — independent of the P1
 * pairwise `useSession` lifecycle. A chain can be loaded whether or not a
 * pairwise session is currently open. */
export function useChain() {
  const [chain, setChain] = useState<ChainSummary | null>(null);
  const [chainStatus, setChainStatus] = useState<ChainStatus>('empty');
  const [chainError, setChainError] = useState<string | null>(null);
  // Real multi-file upload staging — ordered, since a chain never guesses
  // version order (backend/api/chains.py). The demo button above bypasses
  // all of this and goes straight to createDemoChain().
  const [chainFiles, setChainFiles] = useState<File[]>([]);

  async function loadDemoChain() {
    setChainStatus('busy');
    setChainError(null);
    try {
      const result = await createDemoChain();
      const full = await getChain(result.chain_id);
      setChain(full);
      setChainStatus('created');
    } catch (err) {
      setChainError(err instanceof Error ? err.message : String(err));
      setChainStatus('error');
    }
  }

  function addChainFiles(files: FileList | File[]) {
    setChainFiles((prev) => [...prev, ...Array.from(files)]);
  }

  function removeChainFile(index: number) {
    setChainFiles((prev) => prev.filter((_, i) => i !== index));
  }

  function moveChainFile(index: number, direction: -1 | 1) {
    setChainFiles((prev) => {
      const target = index + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function clearChainFiles() {
    setChainFiles([]);
  }

  async function uploadChain() {
    if (chainFiles.length < 2) return;
    setChainStatus('busy');
    setChainError(null);
    try {
      const result = await createChain(chainFiles);
      const full = await getChain(result.chain_id);
      setChain(full);
      setChainStatus('created');
      setChainFiles([]);
    } catch (err) {
      setChainError(err instanceof Error ? err.message : String(err));
      setChainStatus('error');
    }
  }

  async function reviewChain(submission: ChainReviewSubmission) {
    if (!chain) return;
    try {
      const result = await submitChainReview(chain.chain_id, submission);
      setChain(result.chain);
    } catch (err) {
      setChainError(err instanceof Error ? err.message : String(err));
    }
  }

  function resetChain() {
    setChain(null);
    setChainStatus('empty');
    setChainError(null);
    setChainFiles([]);
  }

  return {
    chain,
    chainStatus,
    chainError,
    loadDemoChain,
    reviewChain,
    resetChain,
    chainFiles,
    addChainFiles,
    removeChainFile,
    moveChainFile,
    clearChainFiles,
    uploadChain,
  };
}
