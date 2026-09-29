import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { Settings } from '../state/useSettings';
import type { DataSourceStatus } from '../types';
import { AdvancedTab } from './settings/AdvancedTab';
import { GeneralTab } from './settings/GeneralTab';
import { ShellTab } from './settings/ShellTab';

export type TabKey = 'general' | 'shell' | 'advanced';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'general', label: '一般' },
  { key: 'shell', label: '操作模式' },
  { key: 'advanced', label: '進階' },
];

interface SettingsPopoverProps {
  open: boolean;
  onClose: () => void;
  // TopBar's status dot deep-links straight to 進階（資料來源區塊）(plimsoll-
  // two-shell-spec.md §2 問題 8) instead of whatever tab was last open; the
  // gear still opens to the last-used tab (`tab` state below persists
  // across opens).
  initialTab?: TabKey;
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  dataSourceStatus: DataSourceStatus;
  onDataSourceStatusChange: (status: DataSourceStatus) => void;
}

// ui-spec §3.4 — 桌面 392px 浮層（P6 才做手機全螢幕版）。plimsoll-subtraction-
// matrix.html 小win #07：6 分頁縮成 3（一般／操作模式／進階），AI 模型／資料
// 來源／詞彙別名核准合併進「進階」，語言／色調／字體／背景圖判「砍」直接從
// GeneralTab 消失，「角色」已由兩殼工作換成「操作模式」，「更多視圖」整個砍掉。
export function SettingsPopover({
  open,
  onClose,
  initialTab,
  settings,
  update,
  dataSourceStatus,
  onDataSourceStatusChange,
}: SettingsPopoverProps) {
  const [tab, setTab] = useState<TabKey>('general');

  useEffect(() => {
    if (open && initialTab) setTab(initialTab);
  }, [open, initialTab]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20" onClick={onClose}>
      <div
        role="dialog"
        aria-label="設定"
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col border-l border-line bg-surface shadow-[var(--sh-3)] sm:w-[392px]"
      >
        <div className="flex items-center justify-between border-b border-line p-3">
          <span className="text-[14px] font-medium text-ink-900">設定</span>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-500 hover:bg-accent-soft">
            <X size={16} />
          </button>
        </div>

        <div className="flex gap-1 overflow-x-auto border-b border-line px-3 pt-2">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`shrink-0 rounded-t-md px-2.5 py-1.5 text-[12.5px] font-medium ${
                tab === t.key ? 'border-b-2 border-ink-800 text-ink-900' : 'text-ink-500 hover:text-ink-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === 'general' && <GeneralTab settings={settings} update={update} />}
          {tab === 'shell' && <ShellTab settings={settings} update={update} />}
          {tab === 'advanced' && (
            <AdvancedTab
              settings={settings}
              update={update}
              dataSourceStatus={dataSourceStatus}
              onDataSourceStatusChange={onDataSourceStatusChange}
            />
          )}
        </div>
      </div>
    </div>
  );
}
