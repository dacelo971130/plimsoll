import { useEffect, useState } from 'react';
import { useChain } from '../state/useChain';
import { useSession } from '../state/useSession';
import { useSettings } from '../state/useSettings';
import { useShell } from '../state/useShell';
import { CenterStage } from './CenterStage';
import { HelpPage } from './help/HelpPage';
import { BusyLoader, IntroLoader } from './LoadLineLoader';
import { RightPanel } from './RightPanel';
import { SettingsPopover, type TabKey } from './SettingsPopover';
import { TopBar } from './TopBar';

// ui-spec §2 — 骨架：中 CenterStage（文字／PDF 比對主視圖，含差異底色標示）／
// 右 RightPanel（可收合／可拖曳縮放，KPI＋鏈式分析＋差異清單＋匯出），TopBar
// 橫跨頂端。2026-09-27 使用者回饋：左欄（HistoryRail，紀錄清單）整個砍掉，見
// RightPanel.tsx／CenterStage.tsx 的對應說明。
//
// plimsoll-two-shell-spec.md §1 — `shell` is the one piece of state that
// decides which of the two interface shells (清單總覽／逐步引導) is active;
// it's read here once and threaded down as a plain prop (no Context — see
// §1.2), plus stamped as `data-shell` for any future CSS hook.
const INTRO_SEEN_KEY = 'plimsoll.introSeen.v1';

export function AppShell() {
  const { settings, update } = useSettings();
  const { shell } = useShell(settings);
  const {
    session,
    rails,
    toggleRight,
    openRight,
    setRightWidth,
    dataSourceStatus,
    setDataSourceStatus,
    approvalRoles,
    oldFile,
    newFile,
    setOldFile,
    setNewFile,
    overrides,
    updateOverride,
    inspection,
    uploadStatus,
    uploadError,
    submitComparison,
    loadDemo,
    resetUpload,
    setSession,
    focusRequest,
    jumpToPage,
    activeDifferenceId,
  } = useSession();
  const {
    chain,
    chainStatus,
    chainError,
    loadDemoChain,
    reviewChain,
    resetChain,
    chainFiles,
    addChainFiles,
    removeChainFile,
    moveChainFile,
    uploadChain,
  } = useChain();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsInitialTab, setSettingsInitialTab] = useState<TabKey | undefined>(undefined);
  const [helpOpen, setHelpOpen] = useState(false);

  // 2026-09-28 使用者回饋 — 載重線動畫：第一次進入頁面播一次（同一個分頁工作
  // 階段內重新整理不再播），分析文件時也播。sessionStorage may be unavailable
  // (private mode / blocked storage): then just skip the intro.
  const [introOpen, setIntroOpen] = useState(() => {
    try {
      return sessionStorage.getItem(INTRO_SEEN_KEY) !== '1';
    } catch {
      return false;
    }
  });
  function closeIntro() {
    setIntroOpen(false);
    try {
      sessionStorage.setItem(INTRO_SEEN_KEY, '1');
    } catch {
      // storage blocked — the intro simply replays next load
    }
  }
  const uploadBusy = uploadStatus === 'busy';
  const chainBusy = chainStatus === 'busy';
  // Which flow was running, so the loader can tell success from failure on
  // the render where busy turns false (both statuses have moved on by then).
  const [busyKind, setBusyKind] = useState<'upload' | 'chain'>('upload');
  useEffect(() => {
    if (uploadBusy) setBusyKind('upload');
    else if (chainBusy) setBusyKind('chain');
  }, [uploadBusy, chainBusy]);

  // A chain can now be started straight from the first screen (SourceTab's
  // 鏈式分析比對 tab) with no pairwise session ever created — useSession's own
  // auto-reveal effect only watches `session`, so without this a completed
  // chain would land invisibly behind a still-collapsed right panel.
  useEffect(() => {
    if (chain) openRight();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain?.chain_id]);

  // 右欄「＋ 開始新的比對」— back to an empty first screen. A chain and a
  // pairwise session are separate lifecycles (useChain／useSession), so
  // clearing only the session used to leave a loaded chain stuck in the
  // right panel with no way to dismiss it.
  function startOver() {
    resetUpload();
    resetChain();
  }

  // 2026-09-28 使用者回饋 — TopBar 的 Plimsoll 標誌重新整理整頁。畫面上有比
  // 對／鏈式分析（或正在分析）時先確認：重新整理後沒有介面能再打開這次比對
  // （紀錄清單已拿掉），雖然已送出的判定都已存在伺服器。
  function reloadApp() {
    const hasWork = session !== null || chain !== null || uploadBusy || chainBusy;
    if (
      hasWork &&
      !window.confirm('重新整理會回到首頁，這次比對不會留在畫面上（已送出的判定仍然保存）。確定要重新整理嗎？')
    ) {
      return;
    }
    window.location.reload();
  }

  function openSettings(tab?: TabKey) {
    setSettingsInitialTab(tab);
    setSettingsOpen(true);
  }

  const docPairLabel = session
    ? `${session.old_meta.version ?? '?'} → ${session.new_meta.version ?? '?'}`
    : '尚未載入文件';

  return (
    <div className="flex h-screen flex-col bg-canvas" data-shell={shell}>
      <TopBar
        docPairLabel={docPairLabel}
        dbStatus={dataSourceStatus.status}
        onOpenSettings={openSettings}
        onOpenHelp={() => setHelpOpen(true)}
        onReload={reloadApp}
      />

      <div className="flex min-h-0 flex-1">
        <CenterStage
          shell={shell}
          session={session}
          inspection={inspection}
          focusRequest={focusRequest}
          activeDifferenceId={activeDifferenceId}
          oldFile={oldFile}
          newFile={newFile}
          setOldFile={setOldFile}
          setNewFile={setNewFile}
          overrides={overrides}
          updateOverride={updateOverride}
          uploadStatus={uploadStatus}
          uploadError={uploadError}
          submitComparison={() => submitComparison(settings.analysisMode)}
          loadDemo={(demoId) => loadDemo(settings.analysisMode, demoId)}
          resetUpload={resetUpload}
          chainStatus={chainStatus}
          chainError={chainError}
          loadDemoChain={loadDemoChain}
          chainFiles={chainFiles}
          addChainFiles={addChainFiles}
          removeChainFile={removeChainFile}
          moveChainFile={moveChainFile}
          uploadChain={uploadChain}
        />
        <RightPanel
          shell={shell}
          collapsed={rails.rightCollapsed}
          width={rails.rightWidth}
          onResize={setRightWidth}
          onToggle={toggleRight}
          session={session}
          approvalRoles={approvalRoles}
          onSessionUpdate={setSession}
          onJumpToPage={jumpToPage}
          onStartOver={startOver}
          chain={chain}
          onChainReview={reviewChain}
        />
      </div>

      <SettingsPopover
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initialTab={settingsInitialTab}
        settings={settings}
        update={update}
        dataSourceStatus={dataSourceStatus}
        onDataSourceStatusChange={setDataSourceStatus}
      />

      {/* Rendered over everything and unmounted on close — comparison, review
          drafts and scroll positions underneath are untouched (spec §5.1). */}
      <HelpPage open={helpOpen} onClose={() => setHelpOpen(false)} />
      <BusyLoader
        busy={uploadBusy || chainBusy}
        failed={busyKind === 'chain' ? chainStatus === 'error' : uploadStatus === 'error'}
        detail={chainBusy ? '正在建立鏈式比對，逐版找出差異…' : '正在逐頁比對兩份文件…'}
      />
      {introOpen && <IntroLoader onDone={closeIntro} />}
    </div>
  );
}
