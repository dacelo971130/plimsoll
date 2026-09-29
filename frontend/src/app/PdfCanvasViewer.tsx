import { useEffect, useRef, useState, type MouseEvent } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import pdfjsWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import type { PDFDocumentProxy, RenderTask, TextItem } from 'pdfjs-dist/types/src/display/api';
import { sessionPdfUrl } from '../lib/api';
import type { DifferenceRecord } from '../types';
import { MAGNIFIER_ZOOM_DEFAULT } from './magnifierConfig';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorkerUrl;

type MarkKind = 'add' | 'del' | 'mod';

const KIND_BY_CHANGE_TYPE: Record<DifferenceRecord['change_type'], MarkKind> = {
  新增: 'add',
  刪除: 'del',
  修改: 'mod',
};

// User feedback: CJK PDFs often segment one line into many tiny per-glyph
// text items, so drawing one box per item produced a scribble of small
// circles around individual characters instead of one clean highlight —
// "圖片中的框線很醜" — and the intended audience (視力／年紀較長的使用者)
// needs something that reads as "this whole line changed" at a glance, not
// a puzzle of dots to squint at. Boxes are merged per visual line (see
// mergeLineBoxes below) before this style is applied, and the style itself
// leans bold/high-contrast: a solid heavier border plus a stronger fill
// reads as a highlighter stroke, not a faint outline.
// -600 doesn't exist anywhere in this design system's colour scale (tokens.css
// only defines -700/-500/-200/-50 per risk colour, see index.css's @theme
// block) — using it here silently fell back to the generic grey --line
// border colour (Tailwind just never generated `.border-med-600` etc.),
// exactly the same class of bug as the earlier missing `--color-on-accent`.
// -700 is the darkest defined step and reads clearly against the pale -500
// fill below.
const KIND_BORDER_STYLE: Record<MarkKind, string> = {
  add: 'border-[3px] border-low-700 bg-low-500/20',
  del: 'border-[3px] border-high-700 bg-high-500/20',
  mod: 'border-[3px] border-med-700 bg-med-500/20',
};

// Must match backend.services.drawing_diff.RASTERIZE_DPI — a DrawingRegion's
// bbox is in PyMuPDF-rasterized pixel coordinates at THIS dpi; converting it
// to this component's pdfjs-rendered canvas pixels is a plain linear scale
// (both ultimately derive from the same PDF point coordinate system, just
// sampled at different resolutions).
const DRAWING_REGION_RASTERIZE_DPI = 150;

interface OverlayBox {
  x: number;
  y: number;
  width: number;
  height: number;
  kind: MarkKind;
  differenceId: string;
  // Drawing-region boxes are already one clean rectangle per pixel-diff
  // region (backend/services/drawing_diff.py) — never candidates for the
  // per-line text merge below, which only exists to clean up pdf.js's
  // per-glyph text-item fragmentation.
  isDrawingRegion?: boolean;
}

// Merges same-difference, same-visual-line boxes into one continuous
// rectangle (min-left/min-top to max-right/max-bottom) plus a little
// breathing room, instead of one box per pdf.js text item. Boxes are
// grouped by differenceId (never bleeds across different differences), then
// within a group, sorted top-to-bottom/left-to-right and merged while
// consecutive boxes' vertical ranges overlap — items from the SAME matched
// substring land on the same line consecutively, so this never merges
// across an unrelated gap of unchanged text.
function mergeLineBoxes(boxes: OverlayBox[]): OverlayBox[] {
  const byDiff = new Map<string, OverlayBox[]>();
  for (const b of boxes) {
    if (b.isDrawingRegion) continue;
    if (!byDiff.has(b.differenceId)) byDiff.set(b.differenceId, []);
    byDiff.get(b.differenceId)!.push(b);
  }

  const PAD = 2; // a little breathing room so the stroke doesn't clip ascenders/descenders
  const merged: OverlayBox[] = [];
  for (const group of byDiff.values()) {
    group.sort((a, b) => a.y - b.y || a.x - b.x);
    let current: OverlayBox | null = null;
    for (const b of group) {
      if (current && b.y < current.y + current.height && current.y < b.y + b.height) {
        const c: OverlayBox = current;
        const left = Math.min(c.x, b.x);
        const top = Math.min(c.y, b.y);
        const right = Math.max(c.x + c.width, b.x + b.width);
        const bottom = Math.max(c.y + c.height, b.y + b.height);
        current = { ...c, x: left, y: top, width: right - left, height: bottom - top };
      } else {
        if (current) merged.push(current);
        current = { ...b };
      }
    }
    if (current) merged.push(current);
  }

  return [
    ...boxes.filter((b) => b.isDrawingRegion),
    ...merged.map((b) => ({ ...b, x: b.x - PAD, y: b.y - PAD, width: b.width + PAD * 2, height: b.height + PAD * 2 })),
  ];
}

// A fractional (0–1) point on the page, shared between the old/new
// PdfCanvasViewer siblings so both magnifier lenses track the SAME point on
// the page regardless of which side's canvas the cursor is actually over —
// fractional rather than pixel coordinates because the two sides' canvases
// can differ slightly in intrinsic size (a version's margins/DPI can shift a
// point) while still needing to visually line up.
export interface HoverPoint {
  x: number;
  y: number;
}

// User feedback round 2: the original circular 180px/3x lens showed barely
// one character — a circle wastes its corners (a reading lens needs a
// rectangle to show a run of text, not a porthole), and 3x on top of a
// small crop left almost nothing legible. A wide rectangle at a lower
// default zoom shows a real snippet of the line (plus a bit of the lines
// above/below for context) instead of one glyph, and the zoom is now a
// live-adjustable prop instead of a hardcoded constant. Min/max/step/default
// live in magnifierConfig.ts (not here) — CenterStage's zoom-stepper UI
// needs those same numbers without pulling pdfjs-dist into its bundle.
const MAGNIFIER_WIDTH = 320;
const MAGNIFIER_HEIGHT = 170;

// Canvas draw calls can't use Tailwind classes — reads the SAME CSS custom
// properties the DOM overlay boxes use (tokens.css), so the lens tracks
// whatever theme/dark-mode/accent is actually active instead of a
// hardcoded colour that could drift from it.
const KIND_COLOR_VARS: Record<MarkKind, { border: string; fill: string }> = {
  add: { border: '--low-700', fill: '--low-500' },
  del: { border: '--high-700', fill: '--high-500' },
  mod: { border: '--med-700', fill: '--med-500' },
};

interface PdfCanvasViewerProps {
  sessionId: string;
  side: 'old' | 'new';
  page: number;
  differences: DifferenceRecord[];
  activeDifferenceId: string | null;
  // 放大鏡 — user feedback: "就算字體放大還是無法精準確認到底有沒有改"; a
  // hover-synced loupe on both sides at once is the actual fix, not more
  // zoom on one side alone. All optional so callers outside 原始 PDF mode
  // (there are none today, but the type shouldn't force it) can omit them.
  magnifierEnabled?: boolean;
  magnifierZoom?: number;
  // plimsoll-two-shell-spec.md §3 #11 — which DOM event writes hoverPoint;
  // the lens-drawing effect below never branches on this, only the two
  // handlers right above the returned JSX do.
  magnifierInput?: 'hover' | 'click';
  hoverPoint?: HoverPoint | null;
  onHoverPoint?: (point: HoverPoint | null) => void;
}

/** P5 §3c — 原始 PDF 模式的差異疊框。No backend bbox plumbing needed: renders
 * the page via pdfjs onto a canvas, pulls the SAME page's text items via
 * `getTextContent()`, and re-runs the exact substring-matching heuristic
 * `highlightDifferences.ts` already uses for the 文字比對 mode — just against
 * pdfjs's text items instead of the reconstructed-text string, so each
 * matched item's own transform gives an exact pixel box to draw over the
 * canvas. A difference whose text can't be located on this page (extraction/
 * OCR wording can drift slightly) is silently skipped — never guessed at —
 * and rolled into one honest "N 筆差異無法定位" footnote instead of either a
 * wrong box or a hard error. */
export function PdfCanvasViewer({
  sessionId,
  side,
  page,
  differences,
  activeDifferenceId,
  magnifierEnabled = false,
  magnifierZoom = MAGNIFIER_ZOOM_DEFAULT,
  magnifierInput = 'hover',
  hoverPoint = null,
  onHoverPoint,
}: PdfCanvasViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const lensCanvasRef = useRef<HTMLCanvasElement>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);
  const [docReady, setDocReady] = useState(false);
  const [numPages, setNumPages] = useState(0);
  const [boxes, setBoxes] = useState<OverlayBox[]>([]);
  const [unmatchedCount, setUnmatchedCount] = useState(0);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Every box below is computed in the canvas's INTRINSIC pixel buffer space
  // (canvas.width/height, set from the pdfjs viewport). But the <canvas>
  // itself is styled `max-w-full`, so the browser shrinks its CSS/displayed
  // size to fit whatever room CenterStage/RightPanel's resizable rails leave
  // it — which almost never equals the intrinsic size. Positioning the
  // overlay <div>s with raw intrinsic-pixel offsets against that shrunk
  // canvas is exactly why the marks used to drift off the text (bug report:
  // "疊層在 pdf 上各種跑位根本沒有疊在字上"). Fix: measure the actual
  // displayed-vs-intrinsic width ratio and CSS-scale the whole overlay layer
  // by it, so it always tracks the canvas 1:1 regardless of how narrow the
  // panel currently is.
  const [displayScale, setDisplayScale] = useState(1);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });

  // Loads the PDF document ONCE per (sessionId, side) — previously this and
  // the per-page render below were a single effect keyed on `page` too, so
  // pdfjsLib.getDocument() (a full network fetch + parse of the WHOLE PDF)
  // reran on every single page turn, including a diff card's jump-to-page
  // click. That's the actual reason "點擊比對結果新舊定位時反應很慢" — the
  // page number changing doesn't need the whole document reloaded, only
  // doc.getPage(page) on the document already in memory.
  useEffect(() => {
    let cancelled = false;
    docRef.current = null;
    setDocReady(false);
    setError(null);
    pdfjsLib
      .getDocument({ url: sessionPdfUrl(sessionId, side) })
      .promise.then((doc) => {
        if (cancelled) return;
        docRef.current = doc;
        setNumPages(doc.numPages);
        setDocReady(true);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, side]);

  useEffect(() => {
    if (!docReady || !docRef.current) return;
    let cancelled = false;
    setReady(false);
    setBoxes([]);
    // A page's failure belongs to that page — without this, one bad page
    // left "此頁 PDF 載入失敗" under every page rendered after it.
    setError(null);
    // The pager runs to max(old, new) page count, so the shorter version
    // simply has no page here (demo v1.0 is 6 pages, v1.1 is 7). That's not
    // a load failure: pdf.js would throw "Invalid page request", and the
    // canvas would still show the previous page as if it were this one.
    if (page < 1 || page > docRef.current.numPages) return;

    async function run() {
      try {
        const pdfPage = await docRef.current!.getPage(page);
        const viewport = pdfPage.getViewport({ scale: 1.4 });
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext('2d');
        if (!canvas || !ctx) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        setNaturalSize({ width: viewport.width, height: viewport.height });
        // Cancel any still-in-flight render on this SAME canvas before
        // starting a new one — pdf.js throws "Cannot use the same canvas
        // during multiple render() operations" if two overlap, which a fast
        // double-click on a page-nav/jump-to-page button could trigger
        // (the effect below re-running while the previous run's render()
        // hadn't resolved yet).
        renderTaskRef.current?.cancel();
        const renderTask = pdfPage.render({ canvasContext: ctx, viewport, canvas });
        renderTaskRef.current = renderTask;
        await renderTask.promise;
        if (cancelled) return;

        const relevant = differences.filter((d) => (side === 'old' ? d.old : d.new)?.page.pdf_page === page);
        const newBoxes: OverlayBox[] = [];
        let unmatched = 0;

        const dpiScale = (viewport.scale * 72) / DRAWING_REGION_RASTERIZE_DPI;
        for (const d of relevant) {
          if (d.kind !== 'drawing') continue;
          for (const region of d.regions ?? []) {
            const [x0, y0, x1, y1] = region.bbox;
            newBoxes.push({
              x: x0 * dpiScale,
              y: y0 * dpiScale,
              width: (x1 - x0) * dpiScale,
              height: (y1 - y0) * dpiScale,
              kind: 'mod',
              differenceId: d.id,
              isDrawingRegion: true,
            });
          }
        }

        const textContent = await pdfPage.getTextContent();
        const items = textContent.items.filter((it): it is TextItem => 'str' in it);
        let concatenated = '';
        const itemRanges: { start: number; end: number; index: number }[] = [];
        for (let i = 0; i < items.length; i++) {
          const start = concatenated.length;
          concatenated += items[i].str;
          itemRanges.push({ start, end: concatenated.length, index: i });
        }
        const normalizedConcatenated = concatenated.normalize('NFKC');
        const canUseNormalizedOffsets = normalizedConcatenated.length === concatenated.length;

        for (const d of relevant) {
          if (d.kind === 'drawing') continue;
          const text = (side === 'old' ? d.old : d.new)?.text;
          if (!text) continue;
          let start = concatenated.indexOf(text);
          if (start === -1 && canUseNormalizedOffsets) start = normalizedConcatenated.indexOf(text.normalize('NFKC'));
          if (start === -1) {
            unmatched++;
            continue;
          }
          const end = start + text.length;
          const kind = KIND_BY_CHANGE_TYPE[d.change_type];
          const spanning = itemRanges.filter((r) => r.start < end && r.end > start);
          if (spanning.length === 0) {
            unmatched++;
            continue;
          }
          for (const r of spanning) {
            const item = items[r.index];
            const combined = pdfjsLib.Util.transform(viewport.transform, item.transform);
            const fontHeight = Math.hypot(combined[2], combined[3]);
            const scaleFactor = Math.hypot(viewport.transform[0], viewport.transform[1]);
            newBoxes.push({
              x: combined[4],
              y: combined[5] - fontHeight,
              width: item.width * scaleFactor,
              height: fontHeight,
              kind,
              differenceId: d.id,
            });
          }
        }

        if (!cancelled) {
          setBoxes(mergeLineBoxes(newBoxes));
          setUnmatchedCount(unmatched);
          setReady(true);
        }
      } catch (err) {
        // pdf.js throws RenderingCancelledException from the .cancel() call
        // above — that's expected/benign (a newer render superseded this
        // one), never a real failure to surface as "此頁 PDF 載入失敗".
        if (err instanceof Error && err.name === 'RenderingCancelledException') return;
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }

    void run();
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
  }, [docReady, page, differences, side]);

  // Re-measure whenever the canvas's DISPLAYED size changes for any reason
  // other than a fresh render above — the right rail being dragged/collapsed,
  // the window resizing, etc. ResizeObserver fires once immediately on
  // observe() too, so this also covers the very
  // first paint without a separate effect.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || naturalSize.width === 0) return;
    const observer = new ResizeObserver((entries) => {
      const displayedWidth = entries[0]?.contentRect.width;
      if (displayedWidth) setDisplayScale(displayedWidth / naturalSize.width);
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [naturalSize]);

  // Redraws the lens on every hoverPoint change regardless of WHICH side's
  // mousemove produced it — this is what keeps both sides' lenses locked to
  // the same point (the actual ask), not just the side under the cursor.
  useEffect(() => {
    if (!magnifierEnabled || !hoverPoint || !ready) return;
    const source = canvasRef.current;
    const lens = lensCanvasRef.current;
    const ctx = lens?.getContext('2d');
    if (!source || !lens || !ctx) return;

    const cropWidth = MAGNIFIER_WIDTH / magnifierZoom;
    const cropHeight = MAGNIFIER_HEIGHT / magnifierZoom;
    const cx = hoverPoint.x * naturalSize.width;
    const cy = hoverPoint.y * naturalSize.height;
    const sx = Math.min(Math.max(cx - cropWidth / 2, 0), Math.max(naturalSize.width - cropWidth, 0));
    const sy = Math.min(Math.max(cy - cropHeight / 2, 0), Math.max(naturalSize.height - cropHeight, 0));

    lens.width = MAGNIFIER_WIDTH;
    lens.height = MAGNIFIER_HEIGHT;
    ctx.imageSmoothingEnabled = false; // crisp pixels, not a blurred blow-up — precision is the whole point
    ctx.clearRect(0, 0, MAGNIFIER_WIDTH, MAGNIFIER_HEIGHT);
    ctx.drawImage(source, sx, sy, cropWidth, cropHeight, 0, 0, MAGNIFIER_WIDTH, MAGNIFIER_HEIGHT);

    // The diff-mark boxes are separate DOM <div>s layered over the canvas
    // (CSS borders/fills), never part of the canvas's own pixels — so
    // drawImage() above only ever copies the bare PDF render. Without this,
    // the magnifier shows a plain unmarked crop with no indication a diff
    // mark exists there at all, making it useless for exactly the thing
    // it's for (user feedback: "看不到標示的比對後差異的圖層"). Re-draw
    // each mark that overlaps the cropped region, in the SAME live theme
    // colours as the DOM overlay (see KIND_COLOR_VARS above), scaled into
    // lens-canvas coordinates by the same magnifierZoom factor used for
    // the crop itself.
    const rootStyle = getComputedStyle(document.documentElement);
    for (const b of boxes) {
      if (b.x + b.width < sx || b.x > sx + cropWidth || b.y + b.height < sy || b.y > sy + cropHeight) continue;
      const lx = (b.x - sx) * magnifierZoom;
      const ly = (b.y - sy) * magnifierZoom;
      const lw = b.width * magnifierZoom;
      const lh = b.height * magnifierZoom;
      const colors = KIND_COLOR_VARS[b.kind];
      ctx.fillStyle = rootStyle.getPropertyValue(colors.fill).trim();
      ctx.globalAlpha = 0.25;
      ctx.fillRect(lx, ly, lw, lh);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = rootStyle.getPropertyValue(colors.border).trim();
      ctx.lineWidth = 2 + magnifierZoom;
      ctx.strokeRect(lx, ly, lw, lh);
    }

    // Crosshair pinpointing the exact hovered pixel — the lens crop is
    // re-centered/clamped near page edges, so the hovered point isn't always
    // dead-center; the crosshair is what actually answers "did THIS change".
    // Drawn LAST so it stays visible even on top of a highlighted mark.
    const markerX = ((cx - sx) / cropWidth) * MAGNIFIER_WIDTH;
    const markerY = ((cy - sy) / cropHeight) * MAGNIFIER_HEIGHT;
    ctx.strokeStyle = 'rgba(206, 58, 49, 0.85)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(markerX, 0);
    ctx.lineTo(markerX, MAGNIFIER_HEIGHT);
    ctx.moveTo(0, markerY);
    ctx.lineTo(MAGNIFIER_WIDTH, markerY);
    ctx.stroke();
  }, [hoverPoint, magnifierEnabled, magnifierZoom, ready, naturalSize, boxes]);

  function pointFromEvent(e: MouseEvent<HTMLDivElement>): HoverPoint | null {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return null;
    return { x, y };
  }

  function handleMouseMove(e: MouseEvent<HTMLDivElement>) {
    if (!magnifierEnabled || !onHoverPoint || magnifierInput !== 'hover') return;
    const point = pointFromEvent(e);
    if (point) onHoverPoint(point);
  }

  // 殼 B — click locks the lens to a point instead of tracking the cursor;
  // clicking again clears it (Esc also clears — wired at ComparisonViewer,
  // which owns hoverPoint for both old/new sides at once).
  function handleClick(e: MouseEvent<HTMLDivElement>) {
    if (!magnifierEnabled || !onHoverPoint || magnifierInput !== 'click') return;
    if (hoverPoint) {
      onHoverPoint(null);
      return;
    }
    const point = pointFromEvent(e);
    if (point) onHoverPoint(point);
  }

  const pageMissing = docReady && (page < 1 || page > numPages);
  const displayedWidth = naturalSize.width * displayScale;
  const displayedHeight = naturalSize.height * displayScale;
  const lensHalfW = MAGNIFIER_WIDTH / 2;
  const lensHalfH = MAGNIFIER_HEIGHT / 2;
  const lensLeft = hoverPoint
    ? Math.min(Math.max(hoverPoint.x * displayedWidth, lensHalfW), Math.max(displayedWidth - lensHalfW, lensHalfW))
    : 0;
  const lensTop = hoverPoint
    ? Math.min(Math.max(hoverPoint.y * displayedHeight, lensHalfH), Math.max(displayedHeight - lensHalfH, lensHalfH))
    : 0;

  return (
    <div>
      {pageMissing && (
        <p className="text-[13px] text-ink-400">
          此版本沒有第 {page} 頁（共 {numPages} 頁）
        </p>
      )}
      {/* Hidden, not unmounted: canvasRef must survive for the next page turn. */}
      <div
        className={`relative max-w-full ${pageMissing ? 'hidden' : 'inline-block'} ${magnifierEnabled ? 'cursor-crosshair' : ''}`}
        onMouseMove={magnifierInput === 'hover' ? handleMouseMove : undefined}
        onClick={magnifierInput === 'click' ? handleClick : undefined}
      >
        <canvas ref={canvasRef} className="max-w-full rounded-md border border-line" />
        {ready && (
          <div
            className="absolute left-0 top-0 origin-top-left"
            style={{ width: naturalSize.width, height: naturalSize.height, transform: `scale(${displayScale})` }}
          >
            {boxes.map((b, i) => (
              <div
                key={i}
                data-difference-id={b.differenceId}
                className={`pointer-events-none absolute rounded-md ${KIND_BORDER_STYLE[b.kind]} ${
                  b.differenceId === activeDifferenceId ? 'diff-mark-flash' : ''
                }`}
                style={{ left: b.x, top: b.y, width: b.width, height: b.height }}
              />
            ))}
          </div>
        )}
        {magnifierEnabled && hoverPoint && ready && (
          <div
            className="pointer-events-none absolute z-10 overflow-hidden rounded-xl border-2 border-ink-800 bg-surface shadow-[var(--sh-3)]"
            style={{
              left: lensLeft,
              top: lensTop,
              width: MAGNIFIER_WIDTH,
              height: MAGNIFIER_HEIGHT,
              transform: 'translate(-50%, -50%)',
            }}
          >
            <canvas ref={lensCanvasRef} width={MAGNIFIER_WIDTH} height={MAGNIFIER_HEIGHT} />
            <span className="pointer-events-none absolute bottom-1 right-1.5 rounded bg-ink-900/70 px-1.5 py-0.5 text-[10.5px] font-medium text-white">
              {magnifierZoom.toFixed(1)}×
            </span>
          </div>
        )}
      </div>
      {error && <p className="mt-1 text-[11px] text-high-700">此頁 PDF 載入失敗：{error}</p>}
      {!error && ready && unmatchedCount > 0 && (
        <p className="mt-1 text-[11px] text-ink-400">有 {unmatchedCount} 筆差異無法在原始 PDF 上定位疊框，僅「文字比對」模式可見。</p>
      )}
    </div>
  );
}
