# 金融即時偵測系統

Financial Real-time Detection System — 為資深金融分析師設計的市場監控和新聞分析平台。

## 系統概述

該系統由四個核心模塊組成，提供實時市場警報、主題搜尋、新聞管理和視覺化儀表板：

### 四大模塊

1. **即時雷達 (Radar)** — 自動化監控
   - 每 5 分鐘掃描 RSS + NewsAPI
   - 自動匹配位置暴險
   - 實時推送通知 (LINE/Email/Web)

2. **主題搜尋 (Search)** — 用戶主導分析
   - 自定義主題搜尋
   - 智能位置暴險匹配
   - 按需 AI 深度分析

3. **新聞資料庫 (News DB)** — 內容管理
   - 自動蒐集與篩選
   - 批量保存至 Google Sheets
   - 情緒與熱度指標

4. **儀表板 (Dashboard)** — 視覺化分析 *[開發中]*
   - 市場熱度指標
   - 情緒分析圖表
   - 主題趨勢排行

## 技術棧

### 後端
- **框架**: FastAPI (Python 3.10+)
- **資料庫**: SQLite + SQLAlchemy ORM
- **排程**: APScheduler
- **通知**: LINE Notify, SMTP Email, WebSocket
- **AI**: Claude API (Anthropic)
- **資料源**: NewsAPI, RSS Feed, Google News, Google Sheets

### 前端
- **框架**: React 18 + Vite 6
- **樣式**: Tailwind CSS (Dark Theme)
- **圖表**: Recharts
- **HTTP**: Axios

## 快速開始

### 前置條件
- Python 3.10+
- Node.js 18+
- SQLite (內建)

### 安裝與執行

#### 後端
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### 前端
```bash
cd frontend
npm install
npm run dev  # 開發模式，:5173 (代理 /api, /ws 到 :8000)
```

#### 便捷脚本
```bash
./start.sh        # Linux/Mac
start.bat         # Windows
```

### 健康檢查
```bash
curl http://localhost:8000/api/health
```

## 環境設定

複製 `.env.example` 至 `.env`：

```env
# AI 分析
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=your_gemini_key_here

# 新聞源
NEWS_API_KEY=your_newsapi_key

# 通知
LINE_NOTIFY_TOKEN=your_line_token
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENT=recipient@gmail.com

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json
GOOGLE_SHEETS_SPREADSHEET_ID=your_sheet_id
GOOGLE_SHEETS_POSITION_SHEET=positions
GOOGLE_SHEETS_NEWS_SHEET=news_archive

# 排程
RADAR_INTERVAL_MINUTES=5
MARKET_CHECK_INTERVAL_MINUTES=60
NEWS_SCHEDULE_HOUR=8
NEWS_SCHEDULE_MINUTE=0
```

## API 路由

| 前綴 | 模塊 | 功能 |
|------|------|------|
| `/api/radar` | 即時雷達 | 警報 CRUD、市場數據、監控條件 |
| `/api/search` | 主題搜尋 | 搜尋、AI 分析、位置匹配 |
| `/api/news` | 新聞資料庫 | 文章 CRUD、預覽、保存、情緒 |
| `/api/settings` | 系統設定 | 監控源、通知、Google Sheets |
| `/ws` | WebSocket | 實時警報廣播 |

## 核心概念

### 警報流程 (Alert Flow)
```
RSS/NewsAPI → 新聞匹配 → 位置暴險分析 → 信號條件評估 → 警報創建 → 通知推送
```

### AI 分析
- **預設**: Claude Sonnet 4 (可配置)
- **時機**: 按需觸發 (不自動)
- **內容**: 事件摘要、市場影響、部位風險、後續預測

### 信號條件 (Signal Conditions)
- 優先級評估（首個匹配優先）
- 支援運算子: `gt`, `lt`, `gte`, `lte`, `between`, `cross_above`, `cross_below`
- 信號類型: `positive`, `neutral`, `negative`

### 位置匹配算法 (Exposure Matching)
- 符號完全匹配: +3 分
- 名稱關鍵字匹配: +2 分
- 分類匹配: +0.5 分
- 閾值: ≥1 分判定為相關

## 文件結構

```
.
├── backend/
│   ├── main.py              # FastAPI 應用進入點
│   ├── config.py            # 設定管理
│   ├── database.py          # SQLAlchemy ORM 模型
│   ├── routers/             # API 路由
│   │   ├── radar.py
│   │   ├── search.py
│   │   ├── news_db.py
│   │   └── settings.py
│   ├── services/            # 業務邏輯層
│   │   ├── claude_ai.py
│   │   ├── exposure.py
│   │   ├── google_sheets.py
│   │   ├── market_data.py
│   │   ├── notification.py
│   │   ├── rss_feed.py
│   │   ├── news_api.py
│   │   └── sentiment.py
│   └── scheduler/
│       └── jobs.py          # APScheduler 定時任務
├── frontend/
│   ├── src/
│   │   ├── pages/           # 四大模塊頁面
│   │   ├── components/      # UI 元件
│   │   ├── services/        # API 客戶端
│   │   └── hooks/           # React Hooks
│   └── vite.config.js
├── data/                    # SQLite 資料庫 (git ignored)
└── CLAUDE.md               # AI 助手指南
```

## 開發進度

### 完成功能 ✅
- 即時雷達掃描與通知
- 主題搜尋與 AI 分析
- 新聞預覽與篩選
- Google Sheets 集成
- WebSocket 實時更新
- 市場指標監控

### 開發中 🚧
- 完整儀表板（市場熱度、情緒圖表）
- Gemini AI 集成

### 計劃中 📋
- 社群媒體監控 (Twitter/X)
- 特定人物追蹤
- 批量 AI 分析新聞
- 進階圖表與篩選

## 常見問題

### Q: 如何新增市場指標？
A: 進入「系統設定」→「監控指標」，新增符號（如 ^TWII）。

### Q: 如何自訂信號條件？
A: 在市場指標卡片上點擊「⚙️」，設定運算子和閾值。

### Q: 位置暴險如何匹配？
A: 系統自動掃描 Google Sheets 中的持倉，按符號、名稱、分類比對新聞。

### Q: 為何沒有收到通知？
A: 檢查 `.env` 中 LINE_NOTIFY_TOKEN 或 EMAIL 設定是否正確。

## 貢獻指南

1. 新建 feature branch: `git checkout -b feature/your-feature`
2. 提交變更: `git commit -am 'Add feature'`
3. 推送: `git push origin feature/your-feature`
4. 提交 PR

## 授權

All rights reserved. 本項目為專有軟體，未經許可不得複製、修改或散佈。

## 聯絡

有問題或建議？請在 Issues 中提出。

---

**最後更新**: 2026-03-23
**版本**: 0.1.0 (Alpha)
