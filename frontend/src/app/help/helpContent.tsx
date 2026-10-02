import type { ReactNode } from 'react';
import { GlossarySection } from './GlossarySection';
import { Kbd, Note, QuickstartStep, Steps, Table, Ui } from './helpBlocks';
import { ResetHintsButton } from './ResetHintsButton';
import { CompareLayoutIllustration } from './illustrations/CompareLayoutIllustration';
import { DiffCardIllustration } from './illustrations/DiffCardIllustration';
import { ExportGuardIllustration } from './illustrations/ExportGuardIllustration';
import { HighlightLegend } from './illustrations/HighlightLegend';
import { ShellModesIllustration } from './illustrations/ShellModesIllustration';
import { UploadIllustration } from './illustrations/UploadIllustration';

// 使用說明的文字內容。寫作準則見 docs/help-content-style-guide.md（2026-09-28
// 改版；改版前舊版全文封存於 docs/help-content-archive-2026-09-28.md）。五條
// 準則摘要：
//  - 30 字內講得完就不展開；不補「為什麼」「原理」。
//  - 一個標題只回答一件事——操作放這裡，原因放「常見問題」，深入內容連結到
//    專門講那件事的標題，不要重複寫一次。
//  - 主詞是使用者的動作（「點下 X」），不用抽象名詞開頭。
//  - 按鈕／分頁名稱一律用 <Ui>（照介面原文引用）；顏色只用在風險等級。
//  - 只寫介面上真的存在、真的能用的功能；描述實際行為，不照元件自己的簡介文
//    字；兩者不一致時先修介面，不在這裡遷就。不出現實作名詞（規則代號、分析
//    模式代號、元件名稱等）。
// 介面改動時，這個檔案要跟著檢查。比對標示的示範色塊沿用 CenterStage.tsx 的
// MARK_CLASS，改那邊時 illustrations/HighlightLegend.tsx 要一起改。

export interface HelpSection {
  id: string;
  title: string;
  body: ReactNode;
  // 只有「三步上手」是 true：一直展開，不放進 <details>，因為它必須在
  // 1280×800 不捲動就看到（HelpPage.tsx 靠這個旗標決定怎麼包）。
  alwaysOpen?: boolean;
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'quickstart',
    title: '三步上手',
    alwaysOpen: true,
    body: (
      <>
        <p className="text-[12.5px] text-ink-600">
          上傳舊版與新版文件，Plimsoll 抓出新增／刪除／修改並給風險等級；最終判定永遠在你手上。
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          <QuickstartStep n={1} title="上傳兩版文件" figure={<UploadIllustration />}>
            <p>
              拖曳 PDF 到 <Ui>舊版文件</Ui>／<Ui>新版文件</Ui>。
            </p>
            <p>
              按 <Ui>開始版本差異比對</Ui>。
            </p>
          </QuickstartStep>
          <QuickstartStep n={2} title="看差異與風險" figure={<CompareLayoutIllustration />}>
            <p>右欄列出差異與風險等級。</p>
            <p>點差異卡可跳到原文位置。</p>
          </QuickstartStep>
          <QuickstartStep n={3} title="覆核並匯出" figure={<DiffCardIllustration />}>
            <p>逐筆選 已確認／需追蹤／不採納。</p>
            <p>
              看完後按 <Ui>匯出審查報告 →</Ui>。
            </p>
          </QuickstartStep>
        </div>
        <p className="mt-3 text-[12.5px] text-ink-600">畫面上的操作提示每個步驟只出現一次，按過「知道了」就不再顯示。</p>
        <div className="mt-1.5">
          <ResetHintsButton />
        </div>
      </>
    ),
  },
  {
    id: 'overview',
    title: '介面總覽',
    body: (
      <>
        <h4 className="font-medium text-ink-900">上傳畫面</h4>
        <ul className="list-disc space-y-1 pl-5">
          <li>只接受 PDF；拖曳到 舊版文件／新版文件 兩個框。</li>
          <li>檔案卡顯示：名稱、適用設備、頁數、大小、版本、日期、文字層狀態。</li>
          <li>版本號或日期抓不到：按開始後補填即可，再按一次開始。</li>
          <li>
            選錯檔案：按檔案卡右上角的 ✕ 清掉重選。
          </li>
        </ul>

        <h4 className="mt-3 font-medium text-ink-900">頂端列</h4>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            左邊：<Ui>Plimsoll</Ui> 標誌（點一下重新整理）、目前比對的版本。
          </li>
          <li>
            右邊：<Ui>形象網站</Ui>、<Ui>使用說明</Ui>、設定齒輪（角落狀態點＝資料來源狀態）。
          </li>
        </ul>

        <h4 className="mt-3 font-medium text-ink-900">中間比對區</h4>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <Ui>文字比對</Ui>：左右並排重建文字，可用 <Ui>搜尋本頁文字…</Ui>。
          </li>
          <li>
            <Ui>原始 PDF</Ui>：兩份 PDF 疊色框標差異；少數差異定位不到，只能在文字比對看。
          </li>
          <li>
            <Ui>放大鏡</Ui>（只在原始 PDF 模式）：兩側同步放大，固定 2 倍。
          </li>
          <li>用 ‹ › 翻頁，左右兩欄同步頁碼。</li>
        </ul>
        <HighlightLegend />

        <h4 className="mt-3 font-medium text-ink-900">右欄</h4>
        <p>有比對結果後才出現。拖曳左邊緣調寬；按 收合右欄 縮成窄邊。由上到下：</p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>
            <Ui>＋ 開始新的比對</Ui>：會先確認是否已匯出，避免不小心清掉紀錄。<Ui>匯出審查報告 →</Ui>：見「匯出審查報告」一節。
          </li>
          <li>AI 功能列，見「AI 輔助功能」一節。</li>
          <li>覆核人身分：填一次姓名與核准角色，之後判定都用這個身分送出。</li>
          <li>
            風險篩選：<Ui>全部</Ui>／<Ui>High</Ui>／<Ui>Medium</Ui>／<Ui>Low</Ui>。
          </li>
          <li>
            <Ui>覆核 Agent</Ui>（選 Claude、Gemini 或 Bedrock 才出現），見「覆核 Agent」一節。
          </li>
          <li>
            <Ui>鏈式趨勢分析</Ui>（有多版本比對時），見「多版本鏈式分析」一節。
          </li>
          <li>
            <Ui>待核准清單</Ui>：差異清單，見「覆核」一節。
          </li>
        </ol>
      </>
    ),
  },
  {
    id: 'modes',
    title: '兩種操作模式',
    body: (
      <>
        <p>
          在 <Ui>設定</Ui> → <Ui>操作模式</Ui> 切換。功能完全相同，只差呈現方式，不是權限等級。
        </p>
        <ShellModesIllustration />
        <Table
          head={['', '清單總覽模式（預設）', '逐步引導模式']}
          rows={[
            ['適合', '一次看完、鍵盤快速判定', '一次只看一筆'],
            ['放大鏡', '跟著滑鼠移動', '點一下鎖定，再點或 Esc 解除'],
            ['原始 PDF', '—', '多一個開新分頁連結'],
          ]}
        />
        <p>
          逐步引導模式按 <Ui>結束逐項覆核，回到清單</Ui> 回到完整清單；沒判定也能按下一筆，不會被擋。
        </p>
      </>
    ),
  },
  {
    id: 'review',
    title: '覆核',
    body: (
      <>
        <p>
          點差異卡任何地方，或按 <Ui>查看</Ui>，跳到原文並展開，可看到逐字比對、<Ui>變更解讀</Ui>、<Ui>觸發規則</Ui> 與{' '}
          <Ui>建議處置</Ui>，下方是覆核列：
        </p>
        <Table
          head={['選項', '什麼時候用']}
          rows={[
            [<Ui key="c">✓ 已確認</Ui>, '看過原文，確認這筆。High 選這個匯出才不算未覆核。'],
            [<Ui key="t">◷ 需追蹤</Ui>, '需要後續追蹤。'],
            [<Ui key="d">✕ 不採納</Ui>, '不採納系統初判。'],
          ]}
        />
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <Ui>風險改判</Ui>：系統初判不對時改成 High／Medium／Low。
          </li>
          <li>
            <Ui>覆核筆記（選填）</Ui>：寫下判斷理由，跟著紀錄保存。
          </li>
          <li>核准權限：DPA／船舶技術監督到 High，船隊經理到 Medium，其他到 Low。超過會被拒絕並顯示原因。</li>
        </ul>

        <h4 className="mt-3 font-medium text-ink-900">卡片模式</h4>
        <p>
          按 <Ui>待核准清單</Ui> 旁的 <Ui>卡片模式</Ui>，逐筆放大成置中卡片；判定方式不變。看完按 <Ui>回到清單</Ui> 或 Esc
          跳回原本那一筆。
        </p>

        <h4 className="mt-3 font-medium text-ink-900">鍵盤快速鍵</h4>
        <p>在輸入框打字時不會觸發。</p>
        <Table
          head={['按鍵', '動作']}
          rows={[
            [
              <>
                <Kbd>J</Kbd> <Kbd>K</Kbd>
              </>,
              '下一筆／上一筆',
            ],
            [
              <>
                <Kbd>←</Kbd> <Kbd>→</Kbd>
              </>,
              '卡片模式 上一筆／下一筆',
            ],
            [
              <>
                <Kbd>A</Kbd> <Kbd>T</Kbd> <Kbd>D</Kbd>
              </>,
              '已確認／需追蹤／不採納（先展開一筆）',
            ],
            [<Kbd key="e">Enter</Kbd>, '送出判定並前往下一筆'],
            [<Kbd key="esc">Esc</Kbd>, '解除鎖定的放大鏡；卡片模式 裡離開'],
          ]}
        />
      </>
    ),
  },
  {
    id: 'export',
    title: '匯出審查報告',
    body: (
      <>
        <Steps
          items={[
            <>
              按右欄的 <Ui>匯出審查報告 →</Ui>。覆核人與核准角色自動帶入；報告編號／部門選填。
            </>,
            <>
              主要格式 <Ui>匯出 PDF</Ui>；要 HTML 或 Word 可展開 <Ui>其他格式</Ui>。
            </>,
          ]}
        />
        <ExportGuardIllustration />
        <p>
          <strong className="text-ink-900">還有 High 未標「已確認」</strong>：會跳出提示逐筆列出。按 <Ui>取消</Ui> 回去覆核，或勾選確認後{' '}
          <Ui>仍要匯出為修訂草稿</Ui>——報告會標「修訂草稿」並加註警示。
        </p>
      </>
    ),
  },
  {
    id: 'chain',
    title: '多版本鏈式分析',
    body: (
      <>
        <p>同一份文件有多個版本時，一次看某個參數在各版的變化，找出累積起來才會超標的漂移。</p>
        <Steps
          items={[
            <>
              切到 <Ui>鏈式分析比對</Ui> 分頁；可先按 <Ui>載入鏈式漂移示範</Ui> 看看。
            </>,
            <>
              用 <Ui>選擇 PDF 檔案</Ui> 依版本順序（舊到新）加入，至少 2 個版本。
            </>,
            <>
              按 <Ui>建立鏈式比對</Ui>，結果見右欄 <Ui>鏈式趨勢分析</Ui>；逐項判定並在 <Ui>鏈級簽核</Ui> 留下紀錄。
            </>,
          ]}
        />
      </>
    ),
  },
  {
    id: 'ai',
    title: 'AI 輔助功能',
    body: (
      <>
        <p>AI 只提供建議，不會改變系統的風險初判，也不會替你判定。</p>
        <p>
          先到 <Ui>設定</Ui> → <Ui>進階</Ui> → <Ui>AI 模型</Ui> 選 <Ui>分析模型</Ui> 與 <Ui>模型</Ui>，貼上 <Ui>API Key / Token</Ui>
          （只存這個分頁，關閉即清除）。伺服器已設定金鑰時不用自己貼。
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <Ui>AI 語意建議</Ui>：替部分差異補上語意判讀，標示「此為 AI 建議，非定論」。
          </li>
          <li>
            <Ui>產生詞彙別名候選</Ui>：找出同義詞組，到 詞彙別名核准 人工核准或拒絕。
          </li>
          <li>
            <Ui>批次語意分析</Ui>：鏈式分析裡一次分析整條鏈。
          </li>
          <li>工程圖頁／掃描頁：附讀圖描述或自動辨識文字，仍需人工校對。</li>
          <li>
            <Ui>成本試算</Ui>：免金鑰即可看各模型示範費用，見「AI 成本試算」一節。
          </li>
          <li>
            <Ui>覆核 Agent</Ui>：先查證再整理成簡報，見「覆核 Agent」一節。
          </li>
        </ul>
        <p>
          <Ui>分析模式</Ui> 決定送 AI 的量：預設只送幅度大的修改，可到 設定 → 進階 → 分析模式 放寬，下次比對生效。
        </p>
        <Note>沒設定金鑰時，AI 相關按鈕會顯示「未啟用」，其餘功能照常可用；覆核 Agent 沒設定好之前不會出現。</Note>
      </>
    ),
  },
  {
    id: 'ai-cost',
    title: 'AI 成本試算',
    body: (
      <>
        <p>
          設定頁 <Ui>模型</Ui> 下拉與 AI 功能列的 <Ui>成本試算</Ui>，都用下表牌價換算（每 100 萬 tokens 美金，2026-09-28 對照官方定價）：
        </p>
        <Table
          head={['供應商', '模型', '輸入 / 輸出（每 100 萬 tokens）', '定位']}
          rows={[
            ['Claude（Anthropic）', 'Claude Haiku 4.5', '$1.00 / $5.00', '輕量'],
            ['Claude（Anthropic）', 'Claude Sonnet 5', '$2.00 / $10.00', '中階'],
            ['Claude（Anthropic）', 'Claude Opus 5.5', '$4.00 / $20.00', '旗艦'],
            ['Claude（Anthropic）', 'Claude Fable 5.1', '$10.00 / $50.00', '旗艦'],
            ['Gemini（Google）', 'Gemini 3.1 Flash-Lite', '$0.25 / $1.50', '輕量'],
            ['Gemini（Google）', 'Gemini 3.8 Flash', '$0.75 / $3.75', '中階'],
            ['Gemini（Google）', 'Gemini 2.5 Pro', '$1.25 / $10.00', '旗艦'],
            ['ChatGPT（OpenAI）', 'GPT-6 Luna', '$0.10 / $0.50', '輕量'],
            ['ChatGPT（OpenAI）', 'GPT-6 Sol', '$2.00 / $10.00', '中階'],
            ['ChatGPT（OpenAI）', 'GPT-6 Astra', '$10.00 / $50.00', '旗艦'],
            ['Bedrock（AWS）', 'Amazon Nova 2 Lite', '$0.30 / $2.50', '輕量'],
            ['Bedrock（AWS）', 'Claude Haiku 4.5（Bedrock）', '$1.00 / $5.00', '輕量'],
            ['Bedrock（AWS）', 'Claude Sonnet 5（Bedrock）', '$2.00 / $10.00', '中階'],
          ]}
        />
        <p>
          用這份文件實際會送審的差異筆數與文字量估算費用區間（低：預設 rules_first 模式；高：最寬鬆 model_only 模式），仍是用字元數推算
          token，不是各供應商真正的 tokenizer 結果，正式費用以供應商帳單為準。
        </p>
        <Note>Bedrock 要另外選 <Ui>區域（Region）</Ui>，並在 AWS 主控台先開通所選模型；Bedrock 不支援批次語意分析。Nova 2 Lite 的牌價以從美東呼叫的全球端點為準，從東京呼叫約貴兩成。</Note>
      </>
    ),
  },
  {
    id: 'agent',
    title: '覆核 Agent',
    body: (
      <>
        <p>Agent 在你開始覆核前先查證、整理、排序。它只提供建議，判定永遠由你決定。</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            位置：右欄 <Ui>覆核 Agent</Ui>，選 Claude、Gemini 或 Bedrock 時出現（ChatGPT 不支援）。
          </li>
          <li>
            按 <Ui>請 Agent 準備覆核</Ui>：自動查證 High 與信心較低的差異。
          </li>
          <li>完成後看到覆核簡報：建議先看、影響與建議動作、待確認、名詞解釋。</li>
          <li>每個結論都附引用（例如「D01 · 新 p.3」），點了跳到那一頁。</li>
          <li>引用與原文逐字核對，對不上會移到「待確認」。</li>
        </ul>

        <h4 className="font-medium text-ink-900">預填與批次確認</h4>
        <ul className="list-disc space-y-1 pl-5">
          <li>展開差異卡看「Agent 說明」；未判定的差異會預先選好建議判定，可改掉。</li>
          <li>
            採納建議送出時，筆記會記下「採納 Agent 建議」。Low／Medium 可勾選批次確認；High 必須逐筆展開確認。
          </li>
        </ul>

        <h4 className="font-medium text-ink-900">問文件</h4>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            在 <Ui>問文件</Ui> 輸入問題，只回答與載入文件有關的內容；文件裡找不到就直說找不到。
          </li>
          <li>載入鏈式比對時，可以問「某個數值哪一版改的、為什麼」；簡報也會列出本機的相似歷史案例。</li>
        </ul>

        <Note>Agent 不能替你送出判定、不能刪除或匯出、不用文件以外的知識回答。</Note>
      </>
    ),
  },
  {
    id: 'glossary',
    title: '名詞解釋',
    body: <GlossarySection />,
  },
  {
    id: 'faq',
    title: '常見問題',
    body: (
      <dl className="space-y-3">
        {[
          [
            '為什麼有些差異沒有 AI 建議？',
            '預設分析模式只送「沒被規則判定、改寫幅度大」的修改。到 設定 → 進階 → 分析模式 放寬，下次比對生效。',
          ],
          [
            '頁碼為什麼有兩種？',
            'PDF 頁碼是檔案第幾頁；印刷頁碼是文件自己印的頁碼，常因封面、目錄而不同。抓不到印刷頁碼會留空，不猜。',
          ],
          [
            '覆核送出被拒絕，顯示權限不足？',
            '你的核准角色到不了這個風險等級。確認右欄的覆核人身分，或換有權限的角色覆核。',
          ],
          ['版本號或日期抓不到怎麼辦？', '按開始後會請你補填版本號與日期，填完再按一次開始。'],
          ['匯出時跳出未完成覆核提示？', '還有 High 沒標「已確認」（需追蹤、不採納都算未確認）。回去覆核，或確認後匯出為修訂草稿。'],
          [
            '檔案卡提示「偵測到掃描頁或文字層不足」？',
            '建議人工雙重校對這幾頁，以防系統漏看重大變更。',
          ],
          [
            '為什麼原始 PDF 模式看不到全部差異？',
            '少數差異無法在頁面上定位色框，只會出現在文字比對模式，頁面下方會註明筆數。',
          ],
          [
            '色覺辨識有困難怎麼辦？',
            '到 設定 → 一般 開啟「色盲友善比對配色」。',
          ],
          [
            '選了 Bedrock 為什麼 AI 功能沒有作用？',
            '確認三件事：已選區域（Region）、金鑰是同一個區域產生的、所選模型已在 AWS 主控台開通。Bedrock 也不支援批次語意分析。',
          ],
        ].map(([q, a]) => (
          <div key={q} className="rounded-lg border border-line bg-surface px-3 py-2.5">
            <dt className="font-medium text-ink-900">{q}</dt>
            <dd className="mt-1 text-ink-700">{a}</dd>
          </div>
        ))}
      </dl>
    ),
  },
  {
    id: 'privacy',
    title: '資料與隱私',
    body: (
      <ul className="list-disc space-y-1 pl-5">
        <li>上傳的 PDF、比對結果與覆核紀錄，存在執行 Plimsoll 的那台電腦上，不在瀏覽器裡。</li>
        <li>每一次判定都新增一筆紀錄，不覆寫舊的；所有覆核歷程保留供日後稽核。</li>
        <li>使用 AI 功能時，差異片段、掃描頁影像或工程圖裁切會送到你選的 AI 服務，這些服務可能位於海外。</li>
        <li>請只使用合成或已獲授權公開的文件，不要上傳真實的內部維修手冊或受限制的技術文件。</li>
        <li>示範資料全部是虛構內容，不可當成真實的技術指示。</li>
      </ul>
    ),
  },
];
