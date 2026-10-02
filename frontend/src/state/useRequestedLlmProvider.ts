import { useEffect, useState } from 'react';
import { LLM_SETTINGS_EVENT, requestedProviderId, type LlmProviderId } from '../lib/llmProviders';

/** requestedProviderId(), kept current as 設定 → AI 模型 changes. */
export function useRequestedLlmProvider(): LlmProviderId | null {
  const [id, setId] = useState(requestedProviderId);
  useEffect(() => {
    const onChange = () => setId(requestedProviderId());
    window.addEventListener(LLM_SETTINGS_EVENT, onChange);
    return () => window.removeEventListener(LLM_SETTINGS_EVENT, onChange);
  }, []);
  return id;
}
