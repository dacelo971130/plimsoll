import type { RiskLevel } from '../../types';

// 2026-09-27 使用者回饋「下方清單要有相同顏色，High 就是紅色」— the solid
// --*-fill set is shared by RiskPill, OverviewMessage's risk filter tiles and
// DiffListMessage's card stripe, so one risk is one colour on every surface.
export const RISK_FILL: Record<RiskLevel, string> = {
  High: 'bg-high-fill text-high-on-fill',
  Medium: 'bg-med-fill text-med-on-fill',
  Low: 'bg-low-fill text-low-on-fill',
};

export const RISK_STRIPE: Record<RiskLevel, string> = {
  High: 'border-l-high-fill',
  Medium: 'border-l-med-fill',
  Low: 'border-l-low-fill',
};
