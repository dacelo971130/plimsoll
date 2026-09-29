import { useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';

interface DropzoneProps {
  label: string;
  disabled?: boolean;
  onFile: (file: File) => void;
}

// ui-spec §3.3 — "空狀態：舊版 / 新版兩個 Dropzone（拖曳或點選，僅收 PDF）"
export function Dropzone({ label, disabled, onFile }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function acceptFile(file: File | undefined) {
    if (!file) return;
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) return;
    onFile(file);
  }

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        acceptFile(e.dataTransfer.files[0]);
      }}
      className={`flex w-full flex-col items-center gap-1.5 rounded-lg border border-dashed p-4 text-center transition-colors ${
        dragOver ? 'border-ink-800 bg-accent-soft' : 'border-line hover:bg-accent-soft'
      } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
    >
      <UploadCloud size={18} className="text-ink-500" />
      <span className="text-[12.5px] font-medium text-ink-700">{label}</span>
      <span className="text-[11.5px] text-ink-500">拖曳或點選上傳 PDF</span>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => acceptFile(e.target.files?.[0])}
      />
    </button>
  );
}
