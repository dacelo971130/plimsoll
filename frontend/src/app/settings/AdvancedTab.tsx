import type { Settings } from '../../state/useSettings';
import type { DataSourceStatus } from '../../types';
import { AiModelTab } from './AiModelTab';
import { AliasApprovalTab } from './AliasApprovalTab';
import { DataSourceTab } from './DataSourceTab';

interface AdvancedTabProps {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  dataSourceStatus: DataSourceStatus;
  onDataSourceStatusChange: (status: DataSourceStatus) => void;
}

// plimsoll-subtraction-matrix.html 小win #07 — settings 6 分頁縮成 3
// （一般／操作模式／進階）。AI 模型、資料來源、詞彙別名核准都是真功能（不是
// RoleTab／MoreViewsTab 那種假分頁），矩陣判「藏」不是「砍」——這裡合併成一個
// 分頁的三個區塊，不是刪除任何一個。
export function AdvancedTab({ settings, update, dataSourceStatus, onDataSourceStatusChange }: AdvancedTabProps) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wide text-ink-500">AI 模型</h3>
        <AiModelTab settings={settings} update={update} />
      </section>

      <section className="border-t border-line pt-5">
        <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wide text-ink-500">資料來源</h3>
        <DataSourceTab status={dataSourceStatus} onStatusChange={onDataSourceStatusChange} />
      </section>

      <section className="border-t border-line pt-5">
        <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wide text-ink-500">詞彙別名核准</h3>
        <AliasApprovalTab />
      </section>
    </div>
  );
}
