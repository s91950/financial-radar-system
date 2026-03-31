# 金融即時偵測系統

為資深金融分析師設計的市場監控與新聞分析平台，提供即時警報、主題追蹤、研究報告彙整與 YouTube 頻道監控。

## 系統架構

```
Frontend (:5173) ──Vite proxy──► FastAPI Backend (:8000)
                                   ├── REST API (/api/*)
                                   ├── WebSocket (/ws) — 即時廣播
                                   └── APScheduler — 5 個背景工作
```

---

## 六大功能模組

### 1. 即時雷達（Radar） `/`

自動掃描新聞，產生帶嚴重程度標記的警報。

- **掃描頻率**：預設每 5 分鐘，可在設定頁調整
- **三大文章來源**：
  1. RSS 訂閱（`MonitorSource type=rss`）
  2. Google News 一般搜尋（關鍵字由設定頁的「雷達主題」管理）
  3. 使用者自訂主題（Topic）的關鍵字搜尋
- **嚴重程度**：`緊急 / 高 / 低`，依標題與內容關鍵字判定，使用者可在設定頁自訂關鍵字清單
- **部位暴險**：自動比對 Google Sheets 持倉，產生暴險摘要
- **AI 分析**：按需觸發（按鈕），不自動執行
- **通知**：LINE 僅送「緊急」等級；Discord / Email 全送

### 2. 主題追蹤（Topics） `/search`

使用者自訂主題，設定 boolean 關鍵字，自動彙整相關文章。

- 雷達掃描同步將符合主題的文章寫入 `TopicArticle`
- 使用者也可手動搜尋並匯入文章
- 支援 AI 針對主題做深度分析

**關鍵字格式**：

| 格式 | 範例 | 邏輯 |
|------|------|------|
| 簡單列舉 | `升息, 降息, Fed` | 任一詞命中（OR） |
| 分組括號 | `(Moody's OR 穆迪), (降評 OR 負面展望)` | 每組至少一詞，且**所有組**皆需命中（AND of OR） |

### 3. 新聞資料庫（News DB） `/news`

手動挑選、儲存新聞文章。

- 搜尋預覽（不自動儲存），使用者勾選後批次存入 SQLite + Google Sheets
- 情緒與熱度儀表板
- 每日 08:00 自動蒐集（`金融市場`、`台股`、`美股`、`經濟數據`、`央行政策`）並同步 Google Sheets

### 4. 研究報告（Reports） `/reports`

每日自動蒐集主要央行與研究機構的最新報告。

- **機構**：IMF、BIS、Fed、ECB、BOJ、BOE、NBER 等
- **抓取模式**：標準 RSS / feedparser，遇到 RSS 失效的機構（IMF、ECB、NBER）改用 HTML 爬蟲（IDEAS/RePEC）
- 每日 10:00 自動執行，使用者到此頁面勾選後儲存

### 5. YouTube 監控（YouTube） `/youtube`

追蹤財經相關 YouTube 頻道，每 30 分鐘偵測新影片。

- 輸入頻道 URL 或 ID 即可新增
- 新影片標記 `is_new`，WebSocket 即時通知

### 6. 系統設定（Settings） `/settings`

統一管理所有可設定項目：

- 監控來源（RSS 訂閱、研究機構）
- 通知頻道（LINE Messaging API、Discord Webhook、Email）
- Google Sheets 連接（GAS Web App URL 或 Service Account JSON）
- AI 模型切換（Gemini / Claude）
- 雷達主題關鍵字與掃描間隔
- 嚴重程度關鍵字自訂
- 市場監控清單與信號條件

---

## 排程工作

詳細說明請見 [docs/排程工作說明.md](docs/排程工作說明.md)

| 工作 | 頻率 |
|------|------|
| 即時雷達掃描 | 每 N 分鐘（預設 5） |
| 市場指標檢查 | 每 60 分鐘 |
| 每日新聞蒐集 | 每日 08:00 |
| 每日研究報告蒐集 | 每日 10:00 |
| YouTube 頻道偵測 | 每 30 分鐘 |

---

## 技術棧

### 後端
- **框架**：FastAPI (Python 3.10+)
- **資料庫**：SQLite + SQLAlchemy ORM
- **排程**：APScheduler
- **AI**：Gemini（預設，免費）/ Claude（可切換）
- **資料源**：RSS Feed、Google News、NewsAPI、YouTube RSS、HTML 爬蟲（RePEC/IDEAS）
- **通知**：LINE Messaging API、Discord Webhook、SMTP Email、WebSocket

### 前端
- **框架**：React 18 + Vite 6
- **樣式**：Tailwind CSS（Dark Theme）
- **圖表**：Recharts
- **HTTP**：Axios（60s timeout）

---

## 快速開始

### 前置條件
- Python 3.10+
- Node.js 18+

### 安裝與執行

**後端**（從專案根目錄執行）
```bash
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**前端**
```bash
cd frontend
npm install
npm run dev   # 開發模式 :5173，/api 與 /ws 代理到 :8000
```

**便捷腳本**
```bash
./start.sh   # Linux/Mac
start.bat    # Windows
```

**健康檢查**
```bash
curl http://localhost:8000/api/health
```

---

## 環境設定

複製 `.env.example` 至 `.env`：

```env
# AI（選其一，Gemini 免費推薦）
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
DEFAULT_AI_MODEL=gemini          # 或 claude

ANTHROPIC_API_KEY=your_anthropic_key   # 僅 claude 模式需要

# 新聞源
NEWS_API_KEY=your_newsapi_key

# LINE Messaging API（緊急警報推播）
LINE_CHANNEL_ACCESS_TOKEN=your_token
LINE_TARGET_ID=your_user_id
LINE_CHANNEL_SECRET=your_channel_secret   # LINE Bot Webhook 簽名驗證

# Discord（完全免費，無訊息數限制）
DISCORD_WEBHOOK_URL=

# Email SMTP
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENT=recipient@example.com

# Google Sheets（二擇一）
GOOGLE_APPS_SCRIPT_URL=your_gas_url          # 推薦：GAS Web App
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json  # 備選：Service Account
GOOGLE_SHEETS_SPREADSHEET_ID=your_sheet_id

# 排程
RADAR_INTERVAL_MINUTES=5
MARKET_CHECK_INTERVAL_MINUTES=60
NEWS_SCHEDULE_HOUR=8
NEWS_SCHEDULE_MINUTE=0
```

---

## API 路由

| 前綴 | 路由模組 | 功能 |
|------|----------|------|
| `/api/radar` | `routers/radar.py` | 警報 CRUD、市場資料、監控清單、信號條件 |
| `/api/search` | `routers/search.py` | 主題搜尋、AI 分析、部位匹配 |
| `/api/news` | `routers/news_db.py` | 文章 CRUD、預覽、批次儲存、情緒 |
| `/api/topics` | `routers/topics.py` | 主題 CRUD、文章管理、Google News 搜尋匯入 |
| `/api/research` | `routers/research.py` | 研究機構管理、報告 CRUD、預覽、儲存 |
| `/api/youtube` | `routers/youtube.py` | 頻道管理、影片列表 |
| `/api/settings` | `routers/settings.py` | 監控源、通知、Sheets、AI 模型設定 |
| `/api/line/webhook` | `routers/line_webhook.py` | LINE Bot Reply（收到訊息回傳最新警報） |
| `/api/utils/resolve-url` | `main.py` | 解析 Google News 重定向，取得最終 URL |
| `/ws` | `main.py` | WebSocket 即時廣播 |

---

## 核心設計

### AI 分析
- **預設引擎**：Gemini（免費額度），可切換至 Claude
- **觸發時機**：使用者手動點擊，**絕不自動執行**（節省 API 費用）
- **Factory 模式**：`ai_factory.get_ai_service()` 依 `DEFAULT_AI_MODEL` 返回對應模組，兩者介面一致

### 部位暴險比對（`services/exposure.py`）
| 比對條件 | 分數 |
|----------|------|
| 標的代號完全符合 | +3 |
| 名稱關鍵字符合 | +2 |
| 分類符合 | +0.5 |
| 判定門檻 | ≥ 1 分視為相關 |

資料來源：Google Sheets Sheet1（持倉資料）

### 市場信號條件
- 每個監控標的可設多個 `SignalCondition`，依 `priority` 評估，首個命中優先
- 運算子：`gt / lt / gte / lte / between`
- 僅在 signal **狀態改變**時觸發 Alert（防重複）

### Alert 去重
- 同一小時內相同頭條只建一筆 Alert（`dedup_key` + DB UNIQUE 約束）
- `--reload` 跨進程保護：DB 層 240 秒 timestamp 鎖

---

## 資料庫模型（SQLite）

| 資料表 | 說明 |
|--------|------|
| `articles` | 新聞文章 |
| `alerts` | 雷達與市場警報 |
| `market_watchlist` | 市場監控標的 |
| `signal_conditions` | 信號觸發條件 |
| `monitor_sources` | RSS / 研究機構來源 |
| `notification_settings` | 通知頻道設定 |
| `topics` | 使用者自訂主題 |
| `topic_articles` | 主題對應文章 |
| `research_reports` | 研究報告 |
| `youtube_channels` | YouTube 頻道 |
| `youtube_videos` | YouTube 影片 |
| `system_config` | 執行期設定（key/value） |

資料庫路徑：`data/financial_radar.db`（git 忽略）

---

## 檔案結構

```
.
├── backend/
│   ├── main.py                  # FastAPI 進入點、WebSocket
│   ├── config.py                # 設定管理（.env 讀取）
│   ├── database.py              # ORM 模型、init_db、migrate
│   ├── routers/
│   │   ├── radar.py
│   │   ├── search.py
│   │   ├── news_db.py
│   │   ├── topics.py
│   │   ├── research.py
│   │   ├── youtube.py
│   │   ├── settings.py
│   │   └── line_webhook.py
│   ├── services/
│   │   ├── ai_factory.py        # AI 引擎選擇器
│   │   ├── gemini_ai.py         # Gemini 實作
│   │   ├── claude_ai.py         # Claude 實作
│   │   ├── exposure.py          # 部位暴險比對
│   │   ├── google_sheets.py     # Sheets 讀寫（GAS + Service Account）
│   │   ├── google_news.py       # Google News RSS 搜尋
│   │   ├── rss_feed.py          # RSS 抓取
│   │   ├── research_feed.py     # 研究報告抓取（RSS + HTML 爬蟲）
│   │   ├── youtube_feed.py      # YouTube RSS 抓取
│   │   ├── market_data.py       # 市場報價（yfinance）
│   │   ├── notification.py      # LINE / Discord / Email 通知
│   │   └── sentiment.py         # 情緒分析
│   └── scheduler/
│       └── jobs.py              # 所有排程工作
├── frontend/
│   ├── src/
│   │   ├── pages/               # 6 個模組頁面
│   │   ├── components/          # Layout、UI 元件
│   │   ├── services/api.js      # Axios API 客戶端
│   │   └── hooks/               # useWebSocket 等
│   └── vite.config.js           # 代理設定（含 ngrok whitelist）
├── docs/
│   └── 排程工作說明.md
├── data/                        # SQLite 資料庫（git 忽略）
├── .env.example
└── CLAUDE.md
```

---

## 常見問題

**Q：如何新增 RSS 來源？**
進入「系統設定」→「監控來源」，新增類型為 `RSS` 的來源。

**Q：如何設定 LINE 通知？**
在 LINE Developers Console 建立 Messaging API Channel，取得 `Channel Access Token` 與 `Target ID` 填入 `.env`。LINE 只推送「緊急」等級的警報。

**Q：LINE Bot Webhook 怎麼用？**
設定 `LINE_CHANNEL_SECRET` 後，將 ngrok URL（`https://xxx.ngrok-free.app/api/line/webhook`）填入 LINE Developers Console 的 Webhook URL。使用者傳任意訊息給 Bot 即可收到最新 3 則警報回覆，此為 Reply API，**不計入月額 200 則限制**。

**Q：Discord 通知如何設定？**
在 Discord 頻道「整合」→「Webhook」建立後，複製 URL 填入 `.env` 的 `DISCORD_WEBHOOK_URL`，或在設定頁填入。

**Q：Google Sheets 如何連接？**
推薦使用 GAS Web App（部署 Google Apps Script 後取得 URL，無需 Service Account）。備選：下載 Service Account JSON 放入專案根目錄。

**Q：AI 分析為何要手動觸發？**
為控制 API 費用，所有 AI 分析均為按需執行，掃描與搜尋時不會自動分析。

**Q：為何沒收到通知？**
1. 確認 `.env` 中對應 token/webhook 已填入
2. 查看 `data/notification_debug.log`，記錄每次通知派送狀態
3. LINE 需有「緊急」等級的文章才會推送

---

## 授權

All rights reserved. 本項目為專有軟體，未經許可不得複製、修改或散佈。

---

**版本**：0.8.0 | **最後更新**：2026-03-31
