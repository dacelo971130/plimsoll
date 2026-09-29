/** The Plimsoll brand mark — 2026-09-28 品牌對齊 — 跟行銷網站的 mark 完全一
 * 致：海軍藍圓環 + 紅色水平線（船舶載重線 the load-line motif）。
 * 圓環用 --brand-ring token（淺色 #0B2F6B／深色改用較淺的 navy-200，見
 * tokens.css）而不是寫死色號：寫死的深藍在深色頂欄背景上對比只有 1.37:1
 * （幾乎看不見）。紅線維持 #C8102E 不隨主題變。
 * Sized via `size` (px, square) or `className` (e.g. Tailwind `size-5`);
 * aria-hidden unless `label` is given, in which case it becomes an
 * accessible image. */
export function BrandMark({
  size = 20,
  className,
  label,
}: {
  size?: number;
  className?: string;
  label?: string;
}) {
  return (
    <svg
      width={className ? undefined : size}
      height={className ? undefined : size}
      className={className}
      viewBox="0 0 100 100"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <circle cx="50" cy="50" r="34" fill="none" stroke="var(--brand-ring)" strokeWidth="8" />
      <line x1="8" y1="50" x2="92" y2="50" stroke="#C8102E" strokeWidth="8" />
    </svg>
  );
}
