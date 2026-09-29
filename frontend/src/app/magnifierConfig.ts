// plimsoll-subtraction-matrix.html 小win #08 — 使用者要的是看清楚，不是選倍
// 率；固定一個好值，刪掉可調的 min/max/step。維持獨立小檔（不從
// PdfCanvasViewer.tsx 匯出）是因為 CenterStage.tsx 在主 bundle 就要用到這個
// 值，而 PdfCanvasViewer.tsx 特意 lazy-load 以免把 pdfjs-dist（~1MB）一起打進
// 主 bundle。

export const MAGNIFIER_ZOOM_DEFAULT = 2;
