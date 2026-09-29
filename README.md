# 🚢 Plimsoll — 船舶技術文件版本差異 Agent

把兩份船舶技術文件的版本差異，轉成可追溯、可解釋、並保留人工決策的維修與安全審查摘要。命名緣由見 [`docs/redesign/naming.md`](docs/redesign/naming.md)。

## 目錄結構

```text
backend/
├── main.py                 # FastAPI app：CORS、掛載 frontend/dist、掛載 API router
├── config.py                # data/store 路徑常數（可用 PLIMSOLL_STORE_ROOT 覆寫，供測試隔離）
├── storage/
│   ├── events.py            # 稽核骨幹：append-only 寫入、fold 投影、前綴 hash 完整性驗證
│   ├── sync_target.py        # 可插拔 SyncTarget 介面 + NullSyncTarget（P0 預設，永遠未連線）
│   └── config_loader.py      # 讀 approval_roles / rulesets / approval_policies
├── models/                  # Pydantic schema，鏡射 architecture-decisions-A-B.md 的資料結構
├── services/                # 確定性比對引擎為預設路徑（無 LLM 相依），語意/OCR/工程圖層一律 opt-in
│   ├── extraction.py          # PyMuPDF 文字擷取、雙頁碼、掃描頁偵測、metadata 正則擷取
│   ├── comparison.py          # 頁雜湊短路 + SequenceMatcher 對齊 + rulesets 規則分級
│   ├── normalize.py           # 術語別名正規化視圖（比對前套用，不改原文顯示）
│   ├── chain.py                # 多版本鏈式漂移趨勢分析（W6）
│   ├── drawing_diff.py         # 工程圖頁像素差異定位 + 選擇性 LLM 讀圖描述
│   ├── session_store.py       # 組裝 session.json/differences.json/pages.json + 寫入 AI_INITIAL/HUMAN_REVIEW/EXPORT_SIGNOFF 事件 + PDF 原檔暫存
│   ├── export.py              # HTML/DOCX/PDF 審查報告產生（修訂草稿浮水印）
│   ├── cjk_font.py            # reportlab CJK 字型註冊（PDF 匯出 + demo PDF 生成共用）
│   ├── llm/                    # 多供應商語意層（anthropic/gemini/openai BYOK，Message Batches）；永不改 ai_risk/rule_id
│   ├── ocr/                    # 掃描頁 vision-LLM OCR，與 llm/ 共用同一組 opt-in 金鑰閘門
│   └── agent/                  # 覆核 Agent：按鈕觸發、唯讀工具、逐字驗證引用，輸出寫獨立的 agent_runs.jsonl
├── api/
│   ├── system.py             # /api/health、/api/system/data-source、/api/config/approval-roles
│   ├── demo_auth.py          # 可選的共用密碼（設 PLIMSOLL_DEMO_PASSWORD 才啟用），公開 Demo 網址時用
│   ├── sessions.py           # POST /api/sessions（上傳/inspect/create）、/demo、GET 系列、/pdf/{side}、POST /review-events、POST /export
│   ├── agent.py               # 覆核 Agent 端點（背景執行緒 + 輪詢）
│   ├── aliases.py             # 術語別名核准佇列
│   ├── chains.py              # 多版本鏈式分析端點
│   └── llm_headers.py          # 共用 BYOK header 依賴（X-Llm-Provider / X-Llm-Api-Key）
└── tests/                   # pytest：稽核骨幹、config 規則、擷取/比對引擎、session store、review/export 攔截、API 煙霧測試（27 個檔案）

data/store/
├── config/                  # 版本化種子設定（追蹤於 git）
│   ├── approval_roles.json
│   ├── rulesets/v1.json
│   └── approval_policies/v1.json
├── sessions/                 # 執行期資料（.gitignore）；每個 session 含 source/{old,new}.pdf（C2 nice-to-have）
├── exports/                   # 執行期資料（.gitignore）
└── .integrity/                 # 執行期資料（.gitignore）

frontend/src/
├── app/                      # AppShell 兩欄骨架：TopBar／CenterStage／RightPanel（左欄 HistoryRail 已於 2026-09-27 移除；
│   │                           #「Two-shell A/B」是密度/步調設定，不是版面分岔，見 two-shell-spec.md）
│   ├── settings/               # SettingsPopover 分頁（含 AI 模型 BYOK 設定）
│   ├── source/                 # Dropzone、FileCard、MissingVersionField、SourceTab、TextSourceTab（文字重建/原始PDF）
│   ├── thread/                 # Thread 訊息型別、DiffCard 展開態、ExportMessage、UnreviewedExportGuard
│   └── agent/                  # 覆核 Agent 簡報/問答 UI
├── state/                    # useSettings、useSession（上傳+覆核+跳頁流程）、useReviewerIdentity、shellConfig（two-shell 密度設定）
├── lib/                      # api.ts（後端 fetch 封裝，含 BYOK header）、charDiff.ts（逐字 LCS diff）、ruleLabels.ts、llmProviders.ts
├── styles/tokens.css           # Design tokens：中性階、風險語意色、比對高亮兩組預設、淺/深雙主題
└── types.ts                    # 前端資料型別，對齊 backend/models/*

docs/redesign/                # 規格與決策文件（唯一真相來源，程式碼不得自行改變其結構；本身視為凍結，不再開新檔）
data/specs/                   # 命題工作包、鋼船規範 PDF（僅供研究授權，不進種子/RAG）
data/demo/                    # 合成 Demo PDF 五版（v1.0 六頁；v1.1–v1.4 七頁，供鏈式漂移 demo）
```

### 用容器啟動

不需要本機裝 Python/Node，`docker compose` 一次建置前端＋後端，單一 port 對外：

```bash
docker compose up --build
# 開啟 http://localhost:8110（不用 8099：那是 Postman Interceptor 擴充功能的埠，見 docker-compose.yml）
```

### 用 docker + Cloudflare 起一個臨時 domain

```bash
# 1. 設密碼再起容器。網址公開前一定要設，理由與登入方式見下方「讓別人連到本機」。
#    要讓訪客直接用你的 AI 額度（Demo Day 定案：金鑰由伺服器提供，不讓訪客自己貼），
#    一併帶 ANTHROPIC_API_KEY——docker-compose.yml 已經會把它轉送進容器。
ANTHROPIC_API_KEY='換成你的金鑰' PLIMSOLL_DEMO_PASSWORD='plimsoll' docker compose up --build

# 2. 另開一個終端機建立通道，畫面會印出 https://xxxx.trycloudflare.com
docker run --rm cloudflare/cloudflared:latest tunnel --url http://host.docker.internal:8110
```

- **登入**：開網址時瀏覽器會跳出帳號密碼框，帳號隨便填，密碼填 `PLIMSOLL_DEMO_PASSWORD` 的值。`/api/health` 不需要密碼。
- **前端要先 build**：`frontend/dist` 不進 git，只能本機 `npm run build` 產生；沒 build 就啟動，公開網址只會看到後端回的 JSON 提示，不是網頁介面。
- **AI 功能**：啟動前一併 `export ANTHROPIC_API_KEY=…`，訪客就不用自己在設定頁貼金鑰（額度算伺服器這邊的）；設定前先到 [Anthropic Console](https://console.anthropic.com/) 設好月度花費上限，避免公開網址期間額度失控。
- **筆電不能睡眠**：展示期間另開終端機跑 `caffeinate -dis`（macOS）。
- **限制**：Quick Tunnel 官方定位是測試用、不保證可用性，同時處理中的請求上限 200 個。每次重啟 `cloudflared`
  網址都會變；要在投影片放固定的 QR code，改用 Tailscale Funnel（免費方案即可，`tailscale funnel 8000`，
  第一次會提示到管理頁啟用 Funnel）。
- **資料**：上傳的檔案與稽核日誌都留在這台筆電上；網路流量會經過 Cloudflare，AI 呼叫會送到 Anthropic（美國）。
  **只放合成 demo 資料，不要上傳真實船舶文件。**

## 邊界

不串接企業正式系統、不修改正式程序、不控制設備。資料來源僅本機檔案＋自製合成文件，不得索引 DNV/LR/ABS
船級社規範。PyMuPDF（AGPL）僅限本 demo／非閉源商用場景；閉源商用化需另購授權。
