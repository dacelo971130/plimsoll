import type { Settings } from '../../state/useSettings';
import type { ThemeMode } from '../../types';

interface GeneralTabProps {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
}

const FONT_SIZE_OPTIONS: { value: Settings['fontSize']; label: string }[] = [
  { value: 'sm', label: '小' },
  { value: 'md', label: '中（預設）' },
  { value: 'lg', label: '大' },
  { value: 'xl', label: '特大' },
];

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: 'light', label: '淺色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟隨系統' },
];

// ui-spec §3.4 ① 一般. plimsoll-subtraction-matrix.html 小win #07 —
// 語言切換（沒有翻譯）、整體色調選擇器（海軍藍已定案唯一）、介面字體／原文字
// 體兩組選擇、自訂背景圖，全部判「砍」：每個設定都是一個沒做的決定，13 個開
// 關縮到這裡剩 3 個。
export function GeneralTab({ settings, update }: GeneralTabProps) {
  return (
    <div className="space-y-5">
      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">外觀</div>
        <div className="flex gap-1.5">
          {THEME_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => update('theme', opt.value)}
              aria-pressed={settings.theme === opt.value}
              className={`rounded-md border px-2.5 py-1.5 text-[12.5px] ${
                settings.theme === opt.value
                  ? 'border-ink-800 bg-ink-800 text-on-accent'
                  : 'border-line text-ink-600 hover:bg-accent-soft'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>

      <section>
        <label className="flex items-center justify-between gap-2 rounded-md border border-line px-2.5 py-1.5 text-[12.5px]">
          <span className="font-medium text-ink-700">色盲友善比對配色</span>
          <input
            type="checkbox"
            checked={settings.highlightPalette === 'colorblind'}
            onChange={(e) => update('highlightPalette', e.target.checked ? 'colorblind' : 'classic')}
            className="h-4 w-4"
          />
        </label>
        <p className="mt-1.5 text-[11.5px] text-ink-500">
          關閉時為經典綠／紅／黃；開啟後改為藍／橘，紅綠色盲安全。風險分級色（High／Medium／Low）維持固定語意色，不受此設定影響。
        </p>
      </section>

      <section>
        <div className="mb-1.5 text-[12.5px] font-medium text-ink-700">字級大小</div>
        <div className="flex gap-1.5">
          {FONT_SIZE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => update('fontSize', opt.value)}
              aria-pressed={settings.fontSize === opt.value}
              className={`rounded-md border px-2.5 py-1.5 text-[12.5px] ${
                settings.fontSize === opt.value
                  ? 'border-ink-800 bg-ink-800 text-on-accent'
                  : 'border-line text-ink-600 hover:bg-accent-soft'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
