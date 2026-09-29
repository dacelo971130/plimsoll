import { useEffect, useId, useRef, useState } from 'react';

// 2026-09-28 使用者回饋「首頁載入動畫：第一次進入頁面、分析文件中都播放，參考
// 形象網站（水慢慢淹上來）」— the product website's load-line mark
// (plimsoll-index hero: navy disc + red load line + TF/F/T/W/WNA draft
// ticks), same geometry, with the water rising up to the line. The water
// never goes above the line — 「到這裡為止，是安全的」 — so only the ticks
// below it (W, WNA) light up as it passes.

// translateY of the water path (its surface sits at y=168): 52 puts it just
// under the disc (disc bottom ≈ y=214.5), -6 just under the load line (y=160).
const EMPTY = 52;
const FULL = -6;
const SURFACE_Y = 168;
const TICKS = [
  { y: 82, label: 'TF' },
  { y: 108, label: 'F' },
  { y: 134, label: 'T' },
  { y: 186, label: 'W' },
  { y: 212, label: 'WNA' },
];

type Ease = (t: number) => number;
const linear: Ease = (t) => t;
const easeOut: Ease = (t) => 1 - (1 - t) ** 3;
const easeInOut: Ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

interface Segment {
  to: number;
  ms: number;
  ease: Ease;
  flash?: boolean; // flash the load line when this segment ends (water reached it)
}

// intro: rise once, flash, hold. loop: rise, flash, hold, drain, repeat —
// for as long as the analysis runs. finish: surge from wherever the loop is
// up to the line, flash, hold (the analysis just completed).
type Phase = 'intro' | 'loop' | 'finish';

const SCRIPTS: Record<Phase, Segment[]> = {
  intro: [
    { to: EMPTY, ms: 450, ease: linear },
    { to: FULL, ms: 1700, ease: easeOut, flash: true },
    { to: FULL, ms: 900, ease: linear },
  ],
  loop: [
    { to: FULL, ms: 2600, ease: easeInOut, flash: true },
    { to: FULL, ms: 700, ease: linear },
    { to: EMPTY, ms: 800, ease: easeInOut },
    { to: EMPTY, ms: 250, ease: linear },
  ],
  finish: [
    { to: FULL, ms: 450, ease: easeOut, flash: true },
    { to: FULL, ms: 650, ease: linear },
  ],
};

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

// The water level is driven by requestAnimationFrame and written straight to
// the SVG (no React state per frame); only the rare line flash re-renders.
function LoadLineGraphic({ phase, onPhaseEnd, className }: { phase: Phase; onPhaseEnd?: () => void; className?: string }) {
  const clipId = `ll-clip-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const waterRef = useRef<SVGGElement>(null);
  const tickRefs = useRef<(SVGLineElement | null)[]>([]);
  const levelRef = useRef(EMPTY);
  const onPhaseEndRef = useRef(onPhaseEnd);
  useEffect(() => {
    onPhaseEndRef.current = onPhaseEnd;
  });
  const [flashKey, setFlashKey] = useState(0);

  useEffect(() => {
    let raf = 0;
    let timer = 0;
    let cancelled = false;

    const apply = (level: number) => {
      levelRef.current = level;
      waterRef.current?.setAttribute('transform', `translate(0 ${level})`);
      TICKS.forEach((t, i) => tickRefs.current[i]?.classList.toggle('ll-hit', SURFACE_Y + level <= t.y));
    };

    if (prefersReducedMotion()) {
      // No rising water: show the end state and move on without the wait.
      apply(phase === 'loop' ? (EMPTY + FULL) / 2 : FULL);
      if (phase !== 'loop') timer = window.setTimeout(() => onPhaseEndRef.current?.(), 600);
      return () => window.clearTimeout(timer);
    }

    // Every segment's start is fixed from the script's own t0, not from the
    // frame the previous segment happened to end on — so dropped frames or a
    // throttled background tab never stretch the timeline.
    const run = (segments: Segment[], done: () => void) => {
      const t0 = performance.now();
      const froms = segments.map((_, i) => (i === 0 ? levelRef.current : segments[i - 1].to));
      const ends: number[] = [];
      segments.reduce((acc, seg) => {
        ends.push(acc + seg.ms);
        return acc + seg.ms;
      }, 0);
      let flashed = -1;
      const step = (now: number) => {
        if (cancelled) return;
        const elapsed = Math.max(0, now - t0);
        const index = ends.findIndex((end) => elapsed < end);
        const reached = index === -1 ? segments.length : index;
        for (let k = flashed + 1; k < reached; k++) {
          if (segments[k].flash) setFlashKey((key) => key + 1);
          flashed = k;
        }
        if (index === -1) {
          apply(segments[segments.length - 1].to);
          done();
          return;
        }
        const seg = segments[index];
        const segStart = index === 0 ? 0 : ends[index - 1];
        apply(froms[index] + (seg.to - froms[index]) * seg.ease((elapsed - segStart) / seg.ms));
        raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };

    const loopForever = () => run(SCRIPTS.loop, loopForever);
    if (phase === 'loop') loopForever();
    else run(SCRIPTS[phase], () => onPhaseEndRef.current?.());

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [phase]);

  return (
    // viewBox cropped to the drawing (disc, line, ticks and labels span
    // x≈36–260, y≈80–220) — the site hero's 0 0 280 320 left a tall empty band
    // under the disc that pushed the label far below the mark.
    <svg viewBox="30 70 240 160" className={className} role="img" aria-label="Plimsoll 載重線標記" overflow="visible">
      <defs>
        <clipPath id={clipId}>
          <circle cx="110" cy="160" r="54.5" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <g ref={waterRef} transform={`translate(0 ${EMPTY})`}>
          <path
            className="ll-water-sway"
            d="M40 168 Q55 162 70 168 T100 168 T130 168 T160 168 T190 168 V240 H40 Z"
            fill="var(--brand-water)"
            opacity="0.85"
          />
        </g>
      </g>
      <circle className="ll-draw-disc" cx="110" cy="160" r="58" fill="none" stroke="var(--brand-ring)" strokeWidth="7" />
      <line className="ll-draw-line" x1="40" y1="160" x2="250" y2="160" stroke="#C8102E" strokeWidth="7" strokeLinecap="round" />
      {/* Remounted per flash (key) so the three-pulse animation replays each
          time the water reaches the line. */}
      {flashKey > 0 && (
        <line key={flashKey} className="ll-flash" x1="40" y1="160" x2="250" y2="160" stroke="#ff5470" strokeWidth="7" strokeLinecap="round" />
      )}
      <g className="ll-fade-in">
        <line x1="210" y1="82" x2="210" y2="212" stroke="var(--brand-water)" strokeWidth="1.5" />
        {TICKS.map((t, i) => (
          <line
            key={t.label}
            ref={(el) => {
              tickRefs.current[i] = el;
            }}
            className="ll-tick"
            x1="195"
            y1={t.y}
            x2="225"
            y2={t.y}
            strokeWidth="3.5"
          />
        ))}
        {TICKS.map((t) => (
          <text key={t.label} className="ll-label" x="230" y={t.y + 4}>
            {t.label}
          </text>
        ))}
      </g>
    </svg>
  );
}

const OVERLAY = 'fixed inset-0 flex flex-col items-center justify-center gap-3 bg-canvas/95 backdrop-blur-sm transition-opacity duration-300';

// First entry in a browser tab session (AppShell decides when): the mark
// draws itself, the water rises to the line once, then the overlay fades.
// Any click or key skips it.
export function IntroLoader({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);
  const leavingRef = useRef(false);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  function leave() {
    if (leavingRef.current) return;
    leavingRef.current = true;
    setLeaving(true);
    window.setTimeout(() => onDoneRef.current(), 320);
  }

  useEffect(() => {
    const onKey = () => leave();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div
      data-intro-loader
      onClick={leave}
      className={`${OVERLAY} z-[70] cursor-pointer ${leaving ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
    >
      <LoadLineGraphic phase="intro" onPhaseEnd={leave} className="w-[min(240px,55vw)]" />
      <div className="font-mono text-[13px] font-semibold tracking-[0.08em] text-ink-800">PLIMSOLL</div>
      <p className="ll-fade-in-late text-[13px] text-ink-500">到這裡為止，是安全的。</p>
    </div>
  );
}

type BusyPhase = 'hidden' | 'loop' | 'finish' | 'leaving';

// While a comparison / chain is being built. When it ends the water surges to
// the line (success) or the overlay just fades (error — reaching the line
// would claim a result that isn't there).
export function BusyLoader({ busy, failed, detail }: { busy: boolean; failed: boolean; detail: string }) {
  const [phase, setPhase] = useState<BusyPhase>('hidden');
  const phaseRef = useRef<BusyPhase>('hidden');
  const [graphicPhase, setGraphicPhase] = useState<'loop' | 'finish'>('loop');
  const [shownDetail, setShownDetail] = useState(detail);

  function go(next: BusyPhase) {
    phaseRef.current = next;
    setPhase(next);
  }

  useEffect(() => {
    if (busy) {
      setShownDetail(detail);
      setGraphicPhase('loop');
      go('loop');
      return;
    }
    if (phaseRef.current !== 'loop') return;
    if (failed) {
      go('leaving');
    } else {
      setGraphicPhase('finish');
      go('finish');
    }
    // Only the busy edge matters; `failed` / `detail` are read at that moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy]);

  useEffect(() => {
    if (phase !== 'leaving') return;
    const timer = window.setTimeout(() => go('hidden'), 320);
    return () => window.clearTimeout(timer);
  }, [phase]);

  if (phase === 'hidden') return null;
  return (
    <div
      data-busy-loader
      role="status"
      aria-live="polite"
      className={`${OVERLAY} deck-fade z-[60] ${phase === 'leaving' ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
    >
      <LoadLineGraphic
        phase={graphicPhase}
        onPhaseEnd={() => go('leaving')}
        className="w-[min(220px,50vw)]"
      />
      <div className="font-mono text-[13px] font-semibold tracking-[0.08em] text-ink-800">PLIMSOLL · 比對中</div>
      <p className="text-[13px] text-ink-500">{shownDetail}</p>
    </div>
  );
}
