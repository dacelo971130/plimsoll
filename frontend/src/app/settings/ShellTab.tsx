import { SHELL_CONFIG, type ShellVariant } from '../../state/shellConfig';
import type { Settings } from '../../state/useSettings';

interface ShellTabProps {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
}

const SHELL_OPTIONS: { value: ShellVariant; label: string; blurb: string }[] = [
  { value: 'A', label: '清單總覽模式', blurb: '差異清單一次全部看見，可用鍵盤快速切換與判定。' },
  { value: 'B', label: '逐步引導模式', blurb: '一次只看一筆變更，用「上一筆／下一筆」逐筆前進，介面文字與按鈕也放大一級。' },
];

// plimsoll-two-shell-spec.md §1.3 — reuses the slot + two-card visual style
// that used to be RoleTab (§04 #55 cut that tab entirely). Picking a card
// also seeds `fontSize` from that shell's preset (§1.4); 一般 tab's fontSize
// control still works afterward, this only sets the starting point.
export function ShellTab({ settings, update }: ShellTabProps) {
  function selectShell(variant: ShellVariant) {
    update('shellVariant', variant);
    update('fontSize', SHELL_CONFIG[variant].fontScale);
  }

  return (
    <div className="space-y-3">
      {SHELL_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => selectShell(opt.value)}
          aria-pressed={settings.shellVariant === opt.value}
          className={`w-full rounded-lg border p-3 text-left ${
            settings.shellVariant === opt.value ? 'border-ink-800 bg-accent-soft' : 'border-line hover:bg-accent-soft'
          }`}
        >
          <div className="text-[13.5px] font-medium text-ink-900">{opt.label}</div>
          <div className="mt-0.5 text-[12.5px] text-ink-600">{opt.blurb}</div>
        </button>
      ))}
      <p className="text-[11.5px] text-ink-500">
        兩張介面殼的功能集合完全相同，此設定只影響差異清單的呈現密度與節奏，不是兩個產品或權限等級。
      </p>
    </div>
  );
}
