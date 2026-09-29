import type { RiskLevel } from '../../types';
import { RISK_FILL } from './riskStyle';

// ui-spec §4.2 — risk is never colour-only; the text label carries the
// semantics too (accessibility rule in §4.3).
export function RiskPill({ risk, size = 'md' }: { risk: RiskLevel; size?: 'md' | 'lg' }) {
  const sizing = size === 'lg' ? 'px-2.5 py-1 text-[13px]' : 'px-1.5 py-0.5 text-[11px]';
  return <span className={`rounded-full font-semibold ${sizing} ${RISK_FILL[risk]}`}>{risk}</span>;
}
