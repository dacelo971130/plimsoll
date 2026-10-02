# 比對準確率基準測試

讓本系統和競品用**同一批文件、同一份人工答案、同一套評分規則**比準確率。評分與報告由
`scripts/accuracy_bench.py` 產生，報告輸出到 `docs/benchmark/accuracy-report.html`。

```text
data/benchmark/
├── cases/<案例>/case.json        # 一組新舊文件 + 人工答案（標準答案）
├── results/<案例>/<工具>.csv      # 每個工具回報的變更，一列一筆
├── results/<案例>/<工具>.json     # 這次怎麼跑的：版本、設定、耗時、資料去向
├── competitors.json              # 要涵蓋的競品清單（41 項、35 家），報告的「競品涵蓋」表由它產生
└── templates/                    # 空白結果 CSV、執行紀錄範本、AI 類工具的固定提示詞
```

## 流程

```bash
# 1. 跑本系統（不呼叫任何模型），寫出 results/<案例>/plimsoll.csv
python3 scripts/accuracy_bench.py run-plimsoll

# 2. 列出要交給競品的 PDF——有抽頁的案例（例如鋼船規範第 I 篇）會先抽好，放在 data/benchmark/build/
python3 scripts/accuracy_bench.py prepare

# 3. 替競品建空白結果檔（每個案例各一份）。competitors.json 的產品已經建好了；清單外的新工具才需要這步
python3 scripts/accuracy_bench.py scaffold --tool acrobat
python3 scripts/accuracy_bench.py scaffold --all      # 清單裡新加的產品

# 4. 在競品裡比對 prepare 列出的那兩個 PDF，把它回報的每一筆變更填進 CSV（見下方欄位說明），
#    並在同名 .json 填上 run_date、版本與設定。ChatGPT／Gemini 等 AI 助理一律用 templates/llm_prompt.md 的固定提示詞

# 5. 評分，產生報告
python3 scripts/accuracy_bench.py score
```

## AI 模型 API 基準線

`scripts/llm_baseline.py` 用 API 把同一組文件交給三家的旗艦模型（Claude Opus 5.5、GPT-6 Astra、Gemini 3.1 Pro），
用的就是 `templates/llm_prompt.md` 的固定提示詞，結果直接寫成 `results/<案例>/{claude,gpt,gemini}-api.csv`，
模型回覆原文另存 `.raw.md`。三個模型拿到的輸入完全相同：兩份 PDF 的文字層逐頁、附頁碼標記——比的是模型本身，
不是各家 PDF 解析器（網頁版的 chatgpt／gemini／claude-ai 仍是另外的項目，由人上傳 PDF 跑）。

```bash
python3 scripts/llm_baseline.py --estimate        # 不呼叫模型，只估 token 與費用
python3 scripts/llm_baseline.py --budget 40       # 實際執行；已有結果的組合會略過，--force 才重跑
```

金鑰從環境變數或 repo 根目錄的 `.env`（已在 .gitignore）讀：`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`GEMINI_API_KEY`。
缺哪一家就略過哪一家。會實際花錢，費用記在各結果的執行紀錄 `cost_note`。

## 結果 CSV 欄位

用 Excel 編輯時請存成「CSV UTF-8」。一列一筆工具回報的變更，**照工具給的原樣填，不要合併或幫它補字**——
工具把一句話拆成三筆，就填三列；拆得碎是它的特性，報告裡的「每筆變更卡片數」會反映出來。

| 欄位 | 說明 |
|---|---|
| `item_id` | 工具自己的編號，沒有就留空 |
| `change_type` | `新增`／`刪除`／`修改`（也接受 add/delete/modify 等英文）；工具沒分就留空 |
| `old_page`、`new_page` | 工具標示的頁碼：交給它的那個 PDF 的第幾頁，從 1 起算，**不是頁面上印的頁碼**；沒標就留空 |
| `old_text`、`new_text` | 工具標出的舊文字與新文字，原樣複製 |
| `risk` | 工具給的風險等級，換算成 `High`／`Medium`／`Low`（或 高／中／低）；工具不分級就整欄留空 |
| `gt_id` | 留空＝自動比對。自動對不到、但你判斷它就是某筆答案的碎片，填答案編號（多筆用 `;` 分隔）；確定是雜訊填 `noise` |
| `note` | 隨意 |

還沒填的結果檔（沒有資料列、執行紀錄的 `run_date` 也還是範本字樣）評分時會跳過，報告標「未跑」；
工具真的什麼都沒抓到時，填上 `run_date` 就會照常計分（全部算漏報）。

## 怎麼算「對到」

工具回報的舊文字含有答案的 `old_anchors` 其中一個、或新文字含有 `new_anchors` 其中一個，**而且**工具有標的頁碼落在
答案頁碼 ± `page_tolerance` 內，就算對到。比對前會去掉所有空白、統一全形半形（`80 °C` 等於 `80°C`，`，` 等於 `,`）。

自動對不到的回報會在報告裡逐筆列出。這些不是雜訊，就是答案的碎片——逐字比對工具常只回報「建議 → 必須」這種
片段，不含錨點。由人判斷後填 `gt_id`；**同一條規則也適用在本系統的結果上**，重跑 `run-plimsoll` 時，
文字完全相同的列會沿用你先前填的 `gt_id`。

## 新增一個案例

建 `cases/<案例 id>/case.json`，格式照 `cases/demo-cooling-v1.0-v1.1/case.json`。答案的原則：

- **答案不能從任何比對工具的輸出抄**，包括本系統——否則就是拿自己的答案考自己。來源要寫在 `ground_truth_source`。
- 錨點要挑「只有這筆變更才有」的字串，通常是新舊數值、料號、新增的關鍵詞；「必須」「建議」這種到處都有的字不要當錨點。
- `expected_risk` 由懂船舶作業的人判斷；還沒覆核前 `label_status` 保持 `draft`，報告會標示。
- 答案若只列出部分變更（例如官方「重大增修表」只列重大項目），設 `"recall_only": true`：只量偵測率，不量精確率，
  因為答案沒列的回報不一定是雜訊。
- 某些變更不想計分（例如每頁頁首的版次），設 `"scored": false`：回報它不算漏報、也不算雜訊。
- 條文級的答案可以只給頁碼不給錨點，頁碼可寫範圍：`"new_pages": ["120-125"]`。
- 只比對原 PDF 的一部分：`"old_pdf": {"source": "data/specs/....pdf", "pages": "7-184"}`。答案頁碼一律是抽出檔的頁序。
  答案若印在文件裡（例如官方增修表），抽頁時要把那一頁排除，否則 AI 類工具會直接照抄。
- 一筆「修訂」若同時含刪列、插句，工具回報成刪除或新增也是對的：用 `"accept_change_types": ["修改", "刪除"]` 列出都算對的類型。

## 機密文件

`results/` 裡會有文件內容的片段，`data/benchmark/` 是進 git 的。真實船舶文件或授權受限的文件，改放
`data/benchmark-local/`（已在 `.gitignore`），結構相同，跑的時候加 `--root`：

```bash
python3 scripts/accuracy_bench.py run-plimsoll --root data/benchmark-local
python3 scripts/accuracy_bench.py score --root data/benchmark-local   # 報告寫在 data/benchmark-local/report.html
```

把文件上傳到雲端競品（線上比對網站、ChatGPT 等）等於把內容交給第三方，請先確認文件授權與保密要求，並在執行紀錄的
`data_handling` 寫清楚。
