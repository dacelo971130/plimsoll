interface MissingVersionFieldProps {
  label: string;
  missingFields: string[];
  version: string;
  date: string;
  onVersionChange: (value: string) => void;
  onDateChange: (value: string) => void;
}

const FIELD_LABEL: Record<string, string> = { title: '標題', version: '版本號', date: '發布日期' };

// ui-spec §3.3 — "版本號抓不到時就地補填，未填妥 → 比對按鈕維持 disabled（系統不
// 自行猜測版本號）"。標題缺失只警示、不擋比對；只有版本號會擋。
export function MissingVersionField({
  label,
  missingFields,
  version,
  date,
  onVersionChange,
  onDateChange,
}: MissingVersionFieldProps) {
  if (missingFields.length === 0) return null;

  return (
    <div className="mt-2 rounded-md border border-med-200 bg-med-50 p-2.5">
      <p className="text-[11.5px] text-med-700">
        {label}：系統未能自動辨識 {missingFields.map((f) => FIELD_LABEL[f] ?? f).join('、')}，請手動補填後才能比對。
      </p>
      {missingFields.includes('version') && (
        <input
          value={version}
          onChange={(e) => onVersionChange(e.target.value)}
          placeholder="例如 v1.0"
          className="mt-1.5 w-full rounded-md border border-line bg-surface px-2 py-1 text-[12.5px] text-ink-800"
        />
      )}
      {missingFields.includes('date') && (
        <input
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
          placeholder="例如 2026-08-15"
          className="mt-1.5 w-full rounded-md border border-line bg-surface px-2 py-1 text-[12.5px] text-ink-800"
        />
      )}
    </div>
  );
}
