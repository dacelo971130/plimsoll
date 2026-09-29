#!/usr/bin/env node
/**
 * Records a ~30-36s muted product-demo video of the Plimsoll app for the
 * marketing site's "04 · 實際操作" section, storyboard:
 *   0. the app's load-line intro (title card)
 *   1. drop 舊版/新版 PDFs, run a real comparison (比對中 load-line overlay)
 *   2. filter to High, open a couple of diffs (viewer jumps + flashes)
 *   3. show the export button un-lit (unsigned-High badge)
 *   4. 專注簽核 flashcard deck: sign every High card with A -> Enter
 *   5. Esc -> export button lights up -> open the export dialog
 *
 * Everything here is deliberately isolated from shared/real state:
 *   - builds the frontend into a throwaway temp dist dir (never
 *     frontend/dist itself — a git-ignored local build artifact, not
 *     tracked, but still not something this script should clobber)
 *   - runs THIS worktree's backend on its own port against a fresh temp
 *     PLIMSOLL_STORE_ROOT seeded ONLY with a copy of data/store/config/
 *     (approval roles + rulesets) -- never data/store/ itself, never the
 *     shared Docker backend on :8110
 *   - drives it with playwright-core against the Chromium already cached
 *     under ~/Library/Caches/ms-playwright (no browser download)
 *
 * Kept: <repoRoot>/tmp/demo/plimsoll-demo.webm + a handful of PNG stills.
 * Deleted on every run (success or failure): the temp store, temp dist,
 * and raw pre-trim recording; the backend child process is always killed.
 *
 * Usage: npm run record:demo   (run from frontend/, or via the npm script)
 */

'use strict';

const { spawnSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const FRONTEND_DIR = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..');
// The backend's Python: $PLIMSOLL_RECORD_PYTHON, else this checkout's .venv,
// else the main checkout's .venv (a git worktree has none of its own), else
// whatever python3 is on PATH.
function findPython() {
  if (process.env.PLIMSOLL_RECORD_PYTHON) return process.env.PLIMSOLL_RECORD_PYTHON;
  const candidates = [path.join(REPO_ROOT, '.venv/bin/python3')];
  const common = spawnSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], { cwd: REPO_ROOT, encoding: 'utf8' });
  if (common.status === 0) candidates.push(path.join(path.dirname(common.stdout.trim()), '.venv/bin/python3'));
  return candidates.find((p) => fs.existsSync(p)) ?? 'python3';
}
const PYTHON = findPython();
const PORT = Number(process.env.PLIMSOLL_RECORD_PORT || 8140);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const VIDEO_W = 1440;
const VIDEO_H = 810;
const FFMPEG = path.join(os.homedir(), 'Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac');
const OLD_PDF = path.join(REPO_ROOT, 'data/demo/Main_Engine_Cooling_v1.0.pdf');
const NEW_PDF = path.join(REPO_ROOT, 'data/demo/Main_Engine_Cooling_v1.1.pdf');
const OUT_DIR = path.join(REPO_ROOT, 'tmp/demo');

function log(msg) {
  console.log(`[record-demo] ${msg}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function run(cmd, args, opts = {}) {
  const { quiet, ...rest } = opts;
  const res = spawnSync(cmd, args, { stdio: quiet ? 'pipe' : 'inherit', encoding: 'utf8', ...rest });
  if (res.status !== 0) {
    if (quiet) {
      process.stdout.write(res.stdout || '');
      process.stderr.write(res.stderr || '');
    }
    throw new Error(`command failed (${res.status}): ${cmd} ${args.join(' ')}`);
  }
  return res;
}

async function waitForHealth(url, timeoutMs) {
  const start = Date.now();
  let lastErr = null;
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch (err) {
      lastErr = err;
    }
    await sleep(250);
  }
  throw new Error(`backend never became healthy at ${url}: ${lastErr}`);
}

function killTree(proc) {
  if (!proc || proc.killed || proc.exitCode !== null) return;
  try {
    proc.kill('SIGTERM');
  } catch {
    /* already gone */
  }
}

async function main() {
  for (const p of [OLD_PDF, NEW_PDF]) {
    if (!fs.existsSync(p)) throw new Error(`missing demo PDF: ${p}`);
  }

  fs.mkdirSync(OUT_DIR, { recursive: true });

  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'plimsoll-record-'));
  const distDir = path.join(tmpRoot, 'record-dist');
  const storeDir = path.join(tmpRoot, 'store');
  const videoRawDir = path.join(tmpRoot, 'video');
  fs.mkdirSync(videoRawDir, { recursive: true });
  log(`temp workspace: ${tmpRoot}`);

  let backendProc = null;
  let browser = null;

  try {
    // ---- 1. build the frontend into a throwaway dist dir --------------
    log('building frontend (vite build)...');
    run(path.join(FRONTEND_DIR, 'node_modules/.bin/vite'), ['build', '--outDir', distDir, '--emptyOutDir'], {
      cwd: FRONTEND_DIR,
      quiet: true,
    });

    // ---- 2. seed an isolated store: config only, never data/store/ ----
    fs.mkdirSync(storeDir, { recursive: true });
    fs.cpSync(path.join(REPO_ROOT, 'data/store/config'), path.join(storeDir, 'config'), { recursive: true });

    // ---- 3. launch the backend against that isolated store/dist -------
    const launcherPath = path.join(tmpRoot, 'launcher.py');
    const launcherSrc = [
      'import os, sys',
      `sys.path.insert(0, ${JSON.stringify(REPO_ROOT)})`,
      `os.environ["PLIMSOLL_STORE_ROOT"] = ${JSON.stringify(storeDir)}`,
      'from pathlib import Path',
      'import backend.config as config',
      `config.FRONTEND_DIST = Path(${JSON.stringify(distDir)})`,
      '# main.py mounts FRONTEND_DIST at import time -- must be set above first',
      'from backend.main import app',
      'import uvicorn',
      `uvicorn.run(app, host="127.0.0.1", port=${PORT}, log_level="warning")`,
      '',
    ].join('\n');
    fs.writeFileSync(launcherPath, launcherSrc);

    const backendLogFd = fs.openSync(path.join(tmpRoot, 'backend.log'), 'a');
    log(`starting isolated backend on ${BASE_URL} (store=${storeDir})...`);
    backendProc = spawn(PYTHON, [launcherPath], {
      cwd: REPO_ROOT,
      stdio: ['ignore', backendLogFd, backendLogFd],
    });
    backendProc.on('exit', (code, signal) => {
      if (code !== null && code !== 0) log(`backend exited early (code=${code}, signal=${signal}) -- see backend.log`);
    });

    await waitForHealth(`${BASE_URL}/api/health`, 20000);
    log('backend healthy.');

    const rolesRes = await fetch(`${BASE_URL}/api/config/approval-roles`);
    const rolesJson = await rolesRes.json();
    const dpaRole = rolesJson.roles.find((r) => r.code === 'DPA') || rolesJson.roles[0];
    if (!dpaRole) throw new Error('no approval roles returned by backend');
    log(`reviewer role: ${dpaRole.code}`);

    // ---- 4. drive it with playwright-core ------------------------------
    const { chromium } = require('playwright-core');
    // playwright-core is pinned to 1.60.0 in package.json because that's the
    // version whose Chromium (1223) is already in ~/Library/Caches/ms-playwright;
    // a newer one would want a browser download.
    browser = await chromium.launch({ headless: true });
    const contextCreatedAt = Date.now();
    const context = await browser.newContext({
      viewport: { width: VIDEO_W, height: VIDEO_H },
      recordVideo: { dir: videoRawDir, size: { width: VIDEO_W, height: VIDEO_H } },
    });

    const identity = JSON.stringify({ reviewerName: '陳測試', approvalRoleCode: dpaRole.code });
    await context.addInitScript(
      `(() => {
        try { localStorage.setItem('plimsoll.reviewerIdentity.v1', ${JSON.stringify(identity)}); } catch (e) {}

        function setupCursor() {
          const style = document.createElement('style');
          style.textContent = \`
            @keyframes __demo_ring_pulse { 0% { transform: translate(-50%,-50%) scale(0.4); opacity: 0.9; } 100% { transform: translate(-50%,-50%) scale(2.2); opacity: 0; } }
          \`;
          document.head.appendChild(style);

          const cursor = document.createElement('div');
          cursor.id = '__demo_cursor__';
          cursor.style.position = 'fixed';
          cursor.style.top = '0';
          cursor.style.left = '0';
          cursor.style.width = '0';
          cursor.style.height = '0';
          cursor.style.zIndex = '2147483647';
          cursor.style.pointerEvents = 'none';
          cursor.style.willChange = 'transform';
          cursor.innerHTML = \`
            <svg width="26" height="26" viewBox="0 0 26 26" style="position:absolute; top:0; left:0; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.45));">
              <path d="M3 2 L3 20 L8 15.5 L11.5 22.5 L14.5 21 L11 14 L18 14 Z" fill="#0b1f3a" stroke="white" stroke-width="1.2" stroke-linejoin="round"/>
            </svg>
          \`;
          document.documentElement.appendChild(cursor);

          document.addEventListener(
            'mousemove',
            (e) => {
              cursor.style.transform = 'translate(' + e.clientX + 'px, ' + e.clientY + 'px)';
            },
            true,
          );
          document.addEventListener(
            'mousedown',
            (e) => {
              const ring = document.createElement('div');
              ring.style.position = 'fixed';
              ring.style.top = e.clientY + 'px';
              ring.style.left = e.clientX + 'px';
              ring.style.width = '28px';
              ring.style.height = '28px';
              ring.style.marginLeft = '-14px';
              ring.style.marginTop = '-14px';
              ring.style.borderRadius = '50%';
              ring.style.border = '2px solid #2f6fed';
              ring.style.zIndex = '2147483647';
              ring.style.pointerEvents = 'none';
              ring.style.animation = '__demo_ring_pulse 420ms ease-out forwards';
              document.documentElement.appendChild(ring);
              ring.addEventListener('animationend', () => ring.remove());
            },
            true,
          );
        }

        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', setupCursor);
        } else {
          setupCursor();
        }
      })();`,
    );

    const page = await context.newPage();
    const video = page.video();

    const beats = {};
    const mark = (name) => {
      beats[name] = Date.now() - contextCreatedAt;
    };
    const shot = async (name) => {
      await page.screenshot({ path: path.join(OUT_DIR, name) });
    };

    async function moveTo(locator) {
      // The right panel scrolls internally (e.g. after jumping to a card),
      // so a target that was on-screen a beat ago can now be clipped above
      // or below the visible area -- scroll it back into view first, or the
      // cursor (and the screenshot) ends up pointing at nothing.
      await locator.scrollIntoViewIfNeeded();
      const box = await locator.boundingBox();
      if (!box) throw new Error('locator has no bounding box (not visible?)');
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y, { steps: 25 });
      return { x, y };
    }

    async function waitEnabled(locator, timeoutMs = 8000) {
      const start = Date.now();
      while (Date.now() - start < timeoutMs) {
        if (await locator.isEnabled()) return;
        await sleep(100);
      }
      throw new Error('timed out waiting for locator to become enabled');
    }

    log('navigating...');
    await page.goto(`${BASE_URL}/`, { waitUntil: 'load' });
    await page.getByRole('button', { name: /開始版本差異比對/ }).waitFor({ state: 'visible' });
    mark('page_loaded');

    // The app's own load-line intro plays on a tab's first visit (fresh
    // context = always here) and makes a natural title card for the video;
    // everything under it is click-blocked until it's gone.
    await page.locator('[data-intro-loader]').waitFor({ state: 'detached', timeout: 10000 }).catch(() => undefined);
    mark('intro_done');
    await sleep(300);

    // ---- Beat 1: 交出兩本手冊 ------------------------------------------
    const oldDropzone = page.getByRole('button', { name: /舊版文件/ });
    await moveTo(oldDropzone);
    mark('old_dropzone_hover');
    await sleep(450);
    await oldDropzone.locator('input[type="file"]').setInputFiles(OLD_PDF);
    await page.getByText('Main_Engine_Cooling_v1.0.pdf').waitFor();
    await sleep(600);

    const newDropzone = page.getByRole('button', { name: /新版文件/ });
    await moveTo(newDropzone);
    await sleep(450);
    await newDropzone.locator('input[type="file"]').setInputFiles(NEW_PDF);
    await page.getByText('Main_Engine_Cooling_v1.1.pdf').waitFor();
    await sleep(600);

    await shot('01-upload.png');

    const submitBtn = page.getByRole('button', { name: /開始版本差異比對/ });
    await moveTo(submitBtn);
    await waitEnabled(submitBtn);
    await sleep(350);
    await submitBtn.click();
    mark('submit_click');

    await page.getByText('待核准清單').waitFor({ timeout: 15000 });
    // The 「比對中」 load-line overlay finishes (water surges to the line) and
    // fades before the results are clickable.
    await page.locator('[data-busy-loader]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => undefined);
    mark('results_visible');
    await sleep(900);

    // ---- Beat 2: 差異逐筆浮出 -------------------------------------------
    // NB: the export button's sr-only text also contains "筆 High 未確認", so
    // a plain hasText:'High' match on 'button' would grab it instead -- only
    // the risk-filter tiles (and the change-type filter row) carry
    // aria-pressed, so scoping to that disambiguates reliably.
    const highTile = page.locator('button[aria-pressed]').filter({ hasText: 'High' });
    await moveTo(highTile);
    await sleep(350);
    await highTile.click();
    mark('high_tile_click');
    await sleep(1000);

    // Scoped to <aside> (the right panel): CenterStage's reconstructed page
    // text ALSO stamps data-difference-id on its <mark> highlight spans for
    // whatever differences fall on the currently-shown page (DocumentColumn
    // in CenterStage.tsx), so an unscoped `[data-difference-id]` locator
    // starts matching those too the moment a jump navigates to a page with
    // marked differences -- easy to misread as app duplication bug, but
    // it's two different features sharing one attribute name.
    const diffCards = page.locator('aside [data-difference-id]');
    const firstCard = diffCards.first();
    await firstCard.scrollIntoViewIfNeeded();
    const firstCardBox = await firstCard.boundingBox();
    await page.mouse.move(firstCardBox.x + 40, firstCardBox.y + 18, { steps: 20 });
    await sleep(300);
    await page.mouse.down();
    await page.mouse.up();
    mark('first_card_click');
    await sleep(400);
    await shot('02-diff-flash.png');
    await sleep(1400);

    const secondCard = diffCards.nth(1);
    const secondCardViewBtn = secondCard.locator('button').filter({ hasText: '查看' });
    await moveTo(secondCardViewBtn);
    await sleep(350);
    await secondCardViewBtn.click();
    mark('second_card_view');
    await sleep(1300);

    // ---- Beat 3: 匯出鍵不亮 ---------------------------------------------
    const exportBtn = page.getByRole('button', { name: /匯出審查報告/ });
    await moveTo(exportBtn);
    mark('export_hover');
    await sleep(1500);
    await shot('03-export-not-lit.png');
    await sleep(500);

    // ---- Beat 4: 專注簽核 -------------------------------------------------
    const focusBtn = page.getByRole('button', { name: /卡片模式/ });
    await moveTo(focusBtn);
    await sleep(350);
    await focusBtn.click();
    mark('deck_open');
    await page.getByRole('dialog', { name: '卡片模式' }).waitFor();
    await sleep(700);

    const highCount = 8; // D01/D02/D03/D05/D06/D07/D08/D09 -- see probe in task notes
    for (let i = 0; i < highCount; i += 1) {
      await page.keyboard.press('a');
      await sleep(350);
      if (i === Math.floor(highCount / 2)) await shot('04-focus-deck-signing.png');
      await page.keyboard.press('Enter');
      if (i === 0) mark('first_sign');
      if (i === highCount - 1) mark('last_sign');
      await sleep(600);
    }

    await page.getByText('都看過了').waitFor({ timeout: 8000 });
    mark('deck_done');
    await sleep(1100);

    await page.keyboard.press('Escape');
    mark('deck_closed');
    await sleep(700);

    // ---- Beat 5: 匯出鍵亮起 -> 開啟匯出對話框 -----------------------------
    // closeDeck() jumps the viewer back to the last-focused card, which
    // scrolls the right panel down -- move (and thereby scroll) back up to
    // the export button BEFORE the "lit" still, or the button is off-screen.
    const exportBtn2 = page.getByRole('button', { name: /匯出審查報告/ });
    await moveTo(exportBtn2);
    await sleep(600);
    await shot('05-export-lit.png');
    await sleep(350);
    await exportBtn2.click();
    mark('export_dialog_open');
    await page.getByRole('heading', { name: '匯出審查報告' }).waitFor();
    await sleep(1800);
    mark('end');

    await context.close();
    await browser.close();
    browser = null;

    const rawVideoPath = await video.path();
    log(`raw recording: ${rawVideoPath}`);

    // ---- trim the lead-in (blank frames before the page even loaded) --
    const finalPath = path.join(OUT_DIR, 'plimsoll-demo.webm');
    const trimStartSec = Math.max(0, beats.page_loaded / 1000 - 0.3);
    let trimmed = false;
    try {
      run(FFMPEG, [
        '-y',
        '-ss',
        trimStartSec.toFixed(2),
        '-i',
        rawVideoPath,
        '-c:v',
        'libvpx',
        '-b:v',
        '1M',
        '-an',
        finalPath,
      ], { quiet: true });
      if (fs.existsSync(finalPath) && fs.statSync(finalPath).size > 0) trimmed = true;
    } catch (err) {
      log(`trim failed (${err.message}), falling back to raw recording`);
    }
    if (!trimmed) {
      fs.copyFileSync(rawVideoPath, finalPath);
    }

    // ---- report actual beat timestamps relative to the trimmed video --
    const rel = (ms) => Math.max(0, ms / 1000 - trimStartSec);
    const stat = fs.statSync(finalPath);

    const probe = spawnSync(FFMPEG, ['-i', finalPath], { encoding: 'utf8' });
    const durationMatch = /Duration:\s*(\d+):(\d+):([\d.]+)/.exec(probe.stderr || '');
    let durationSec = null;
    if (durationMatch) {
      durationSec = Number(durationMatch[1]) * 3600 + Number(durationMatch[2]) * 60 + Number(durationMatch[3]);
    }

    const report = {
      trimmed,
      trimStartSec: Number(trimStartSec.toFixed(2)),
      finalPath,
      fileSizeBytes: stat.size,
      durationSec,
      beatsRelSec: Object.fromEntries(Object.entries(beats).map(([k, v]) => [k, Number(rel(v).toFixed(2))])),
      stillsDir: OUT_DIR,
    };
    fs.writeFileSync(path.join(tmpRoot, 'report.json'), JSON.stringify(report, null, 2));
    console.log('[record-demo] RESULT ' + JSON.stringify(report));
  } finally {
    killTree(backendProc);
    if (browser) {
      try {
        await browser.close();
      } catch {
        /* ignore */
      }
    }
    try {
      fs.rmSync(tmpRoot, { recursive: true, force: true });
    } catch {
      /* best effort cleanup */
    }
  }
}

main().catch((err) => {
  console.error('[record-demo] FAILED', err);
  process.exitCode = 1;
});
