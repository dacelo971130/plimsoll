import type { DataSourceStatus } from '../types';

const COLOR: Record<DataSourceStatus['status'], string> = {
  connected: 'bg-low-500',
  disconnected: 'bg-ink-400',
  connecting: 'bg-med-500',
  error: 'bg-high-500',
};

const LABEL: Record<DataSourceStatus['status'], string> = {
  connected: '已連線',
  disconnected: '未連線 · 資料僅存本機',
  connecting: '連線中…',
  error: '連線失敗',
};

/** Global DB-sync status dot — lives next to the TopBar gear, never next to
 * a per-session storage tag (architecture-decisions-A-B.md §24 design note:
 * this is the one and only global fact, tags are per-session and repeat in
 * three places). */
export function StatusDot({ status }: { status: DataSourceStatus['status'] }) {
  return (
    <span
      className={`inline-block h-[8px] w-[8px] rounded-full ${COLOR[status]}`}
      title={`資料庫：${LABEL[status]}`}
      aria-label={`資料庫：${LABEL[status]}`}
    />
  );
}
