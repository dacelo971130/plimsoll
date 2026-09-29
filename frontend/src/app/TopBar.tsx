import { CircleHelp, Globe, Settings } from 'lucide-react';
import { PRODUCT_SITE_URL } from '../lib/links';
import { BrandMark } from './BrandMark';
import type { TabKey } from './SettingsPopover';
import { StatusDot } from './StatusDot';
import type { DataSourceStatus } from '../types';

interface TopBarProps {
  docPairLabel: string;
  dbStatus: DataSourceStatus['status'];
  onOpenSettings: (tab?: TabKey) => void;
  onOpenHelp: () => void;
  onReload: () => void;
}

// ui-spec §2 / §9 #8: TopBar only keeps brand, doc-pair pill, and the gear —
// role/theme/language/font/highlight/background/API key/data source all
// live inside SettingsPopover. 2026-09-27 使用者回饋 — 左／右欄收合鈕從
// TopBar 移除：左欄（HistoryRail）整個砍掉，右欄的收合／展開改成右欄自己內部
// 的控制（見 RightPanel.tsx），不需要一個永遠存在的頂欄按鈕操作一個要等有比
// 對才存在的欄。
//
// plimsoll-two-shell-spec.md §2 問題 8【待人工覆核】— gear and status dot are
// two independent controls (same visual stack, dot still overlapping the
// gear's corner): the gear opens Settings to its last-used tab as before,
// the dot deep-links straight to 進階（資料來源區塊，settings 6→3 分頁合併後
// 資料來源移到這裡，見小win #07）since that's what its own color/tooltip is
// actually about.
//
// 2026-09-27 使用者要求：齒輪左邊加「使用說明」，打開整頁說明（help/HelpPage.tsx）。
// 帶文字標籤而不是只有圖示——評審第一次打開時要一眼找得到，這顆是入口不是
// 進階功能（plimsoll-review-agent-spec.md §5.1）。
export function TopBar({ docPairLabel, dbStatus, onOpenSettings, onOpenHelp, onReload }: TopBarProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      {/* 2026-09-28 品牌對齊 — 行銷網站的品牌 mark（海軍藍圓環＋紅線；圓環
       * 深色主題會換淺一點的 navy-200，見 BrandMark.tsx／tokens.css）。
       * 同日使用者回饋：標誌＋字樣是重新整理鈕（有比對時會先確認，見
       * AppShell.tsx 的 reloadApp）；-ml 抵掉按鈕自己的 padding，字樣位置不動。 */}
      <button
        type="button"
        onClick={onReload}
        title="重新整理"
        className="-ml-1.5 flex items-center gap-2 rounded-md px-1.5 py-1 text-ink-900 hover:bg-accent-soft"
      >
        <BrandMark size={18} />
        <span className="text-[15px] font-semibold tracking-tight">Plimsoll</span>
      </button>

      <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[12.5px] text-ink-600">
        {docPairLabel}
      </span>

      <div className="ml-auto flex items-center gap-1.5">
        {/* 2026-09-28 使用者回饋 — 使用說明左邊多一顆，導向形象網站（新分頁，
            不離開正在覆核的這一頁）。 */}
        <a
          href={PRODUCT_SITE_URL}
          target="_blank"
          rel="noopener noreferrer"
          title="在新分頁開啟 Plimsoll 形象網站"
          className="flex items-center gap-1 rounded-md px-2 py-1.5 text-[12.5px] text-ink-600 hover:bg-accent-soft hover:text-ink-800"
        >
          <Globe size={16} />
          <span>形象網站</span>
        </a>
        <button
          type="button"
          onClick={onOpenHelp}
          className="flex items-center gap-1 rounded-md px-2 py-1.5 text-[12.5px] text-ink-600 hover:bg-accent-soft hover:text-ink-800"
        >
          <CircleHelp size={16} />
          <span>使用說明</span>
        </button>
        <div className="relative">
          <button
            type="button"
            onClick={() => onOpenSettings()}
            title="設定"
            className="rounded-md p-1.5 text-ink-500 hover:bg-accent-soft hover:text-ink-800"
          >
            <Settings size={16} />
          </button>
          <button
            type="button"
            onClick={() => onOpenSettings('advanced')}
            aria-label="查看資料來源狀態"
            title="查看資料來源狀態"
            className="absolute -right-0.5 -top-0.5 rounded-full"
          >
            <StatusDot status={dbStatus} />
          </button>
        </div>
      </div>
    </header>
  );
}
