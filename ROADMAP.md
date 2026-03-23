# 項目開發路線圖 (Roadmap)

## 優先級矩陣

```
高影響 + 低工作量        高影響 + 高工作量
  🟢 Quick Wins          🔥 Strategic
─────────────────────────────────────────
  🟡 Nice to Have        🔴 Challenge
低影響 + 低工作量        低影響 + 高工作量
```

---

## 📅 發展時間表

### Phase 1: 儀表板完成 (1-2 週) 🔥 P0
**目標**: 提供完整的視覺化分析介面

#### Week 1: 基礎儀表板架構
- [ ] 新建 `frontend/src/pages/DashboardPage.jsx`
- [ ] 新建 `backend/routers/dashboard.py`
- [ ] 設計儀表板版面 (Figma/草稿)
- [ ] 配置路由 (`/dashboard`)

**後端 API**:
```python
GET /api/dashboard/sentiment      # 各資產類別情緒統計
GET /api/dashboard/heat           # 市場熱度排行
GET /api/dashboard/trending       # 熱門主題與事件
GET /api/dashboard/timeline       # 事件時間線
```

**前端元件**:
```jsx
DashboardPage.jsx
├── SentimentCard       // 情緒指標卡片
├── HeatmapChart        // 市場熱力圖
├── TrendingTopics      // 熱門主題排行
└── EventTimeline       // 事件時間線
```

#### Week 2: 圖表實現與數據集成
- [ ] 實現 Recharts 多維圖表
- [ ] 從 Alert/Article 表聚合情緒數據
- [ ] 連接 WebSocket 實時更新
- [ ] UI 優化與響應式設計

**實現細節**:
```python
# services/dashboard_analytics.py
async def get_sentiment_stats(hours=24) -> dict
async def get_market_heat(category=None) -> dict
async def get_trending_topics(limit=10) -> list
async def get_event_timeline(limit=20) -> list
```

**預期功能**:
- ✨ 情緒分布圖 (Pie Chart)
- ✨ 市場熱度排行 (Bar Chart)
- ✨ 主題趨勢線圖 (Line Chart)
- ✨ 事件時間線 (Timeline)
- ✨ 實時數據推送

**驗收標準**:
- [ ] 儀表板加載時間 < 2s
- [ ] 圖表每 30s 自動刷新
- [ ] WebSocket 推送延遲 < 1s
- [ ] 響應式設計在 1024px 以下可用

---

### Phase 2: AI 能力增強 (1 週) 🟠 P1
**目標**: 支援多個 AI 服務，優化成本

#### 2.1 Gemini API 集成
- [ ] 新建 `backend/services/gemini_ai.py`
- [ ] 在 `config.py` 新增 `GEMINI_API_KEY`
- [ ] 在 `config.py` 新增 `DEFAULT_AI_MODEL = 'gemini'`
- [ ] 修改分析路由支援 `model` 參數

**API 設計**:
```python
# config.py
DEFAULT_AI_MODEL: str = os.getenv("DEFAULT_AI_MODEL", "gemini")  # gemini|claude
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
CLAUDE_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# services/ai_factory.py (新建)
async def get_ai_service(model: str) -> AIService
  # 工廠模式: 返回 GeminiService 或 ClaudeService

# 分析端點修改
POST /api/radar/alerts/{id}/analyze?model=claude  # 使用 Claude
POST /api/search/topic/analyze?model=gemini       # 使用 Gemini
```

#### 2.2 成本優化
- [ ] Gemini 用於實時分析 (便宜)
- [ ] Claude 用於深度分析 (精準)
- [ ] 記錄 AI 調用成本

**實現**:
```python
# services/ai_cost_tracker.py
async def log_ai_call(model: str, tokens: int, cost: float)
async def get_cost_stats(period: str) -> dict
```

**驗收標準**:
- [ ] Gemini API 調用成功率 > 95%
- [ ] 回覆時間 < 原 Claude 時間
- [ ] 支援在 UI 中選擇 AI 模型

---

### Phase 3: 新聞來源管理與 UI (1 週) 🟡 P2
**目標**: 完善監控來源，使用者可自訂

#### 3.1 後端擴展
- [ ] 擴充 `routers/settings.py`
  - `GET /api/settings/sources` - 列表
  - `POST /api/settings/sources` - 新增
  - `PUT /api/settings/sources/{id}` - 更新
  - `DELETE /api/settings/sources/{id}` - 刪除

#### 3.2 前端 SettingsPage 擴展
- [ ] 新增「監控來源」管理卡片
- [ ] 支援新增/編輯/刪除 RSS 源
- [ ] 支援設定關鍵字過濾
- [ ] 顯示來源活躍狀態與最新抓取時間

**UI 設計**:
```jsx
SourceManagementCard
├── SourceList
│   └── SourceItem (可編輯/刪除)
├── AddSourceForm
│   ├── 來源名稱
│   ├── 來源 URL (RSS/API)
│   ├── 監控類型 (RSS|NewsAPI|Twitter)
│   ├── 關鍵字過濾 (逗號分隔)
│   └── 啟用/禁用 toggle
└── SourceStats (總數、活躍數、上次更新)
```

**驗收標準**:
- [ ] 可成功新增 RSS 源
- [ ] 可編輯/刪除現有源
- [ ] 新源在下次掃描 (5 分鐘內) 被納入
- [ ] 無效 RSS 顯示錯誤提示

---

### Phase 4: 社群媒體監控 (2-3 週) 🔥 P3
**目標**: 監控 Twitter/X 和特定人物

#### 4.1 Twitter 集成
- [ ] 新建 `backend/services/twitter_client.py`
- [ ] 使用 tweepy 或 x-api 客戶端
- [ ] 在 `config.py` 新增 Twitter API 密鑰
- [ ] 新建 `routers/social.py` 路由

**功能**:
```python
async def fetch_tweets(accounts: list[str], keywords: list[str]) -> list[dict]
async def monitor_account(username: str) -> dict
async def get_social_sentiment(username: str, hours=24) -> float
```

#### 4.2 特定人物追蹤
**預設監控清單**:
- 央行相關: 楊金龍 (@央銀), 美聯儲主席
- 知名分析師: 巴菲特, 達里歐等
- 財經媒體: Bloomberg, CNBC 官方帳號

#### 4.3 新增通知類型
- [ ] 社群媒體警報 (`type: 'social'`)
- [ ] 與現有警報聚合

**驗收標準**:
- [ ] 能抓取 Twitter 帖文
- [ ] 情緒分析準確率 > 80%
- [ ] 推送延遲 < 1 分鐘

---

### Phase 5: 新聞分析增強 (1 週) 🟡 P4
**目標**: 批量分析與自動摘要

#### 5.1 批量 AI 分析
- [ ] NewsDBPage 新增「批量分析」按鈕
- [ ] 後端 `POST /api/news/analyze-batch` 路由
- [ ] 並行處理 (多個文章並發分析)

**流程**:
```
使用者點擊「分析今日新聞」
  ↓
取得未分析的文章 (今日新增)
  ↓
批量呼叫 Gemini API (並行)
  ↓
儲存分析結果
  ↓
同步至 Google Sheets
  ↓
WebSocket 通知完成
```

#### 5.2 增強 UI
- [ ] 進度條顯示分析進度
- [ ] 分析結果 (重點、風險等級) 顯示
- [ ] 導出 PDF 報告

**驗收標準**:
- [ ] 100 篇文章分析 < 2 分鐘
- [ ] UI 顯示分析進度與結果

---

## 低優先級改進 (Nice to Have)

### 其他功能
- [ ] 黑名單過濾 (自動忽略某些來源)
- [ ] 自訂警報規則編輯器 (GUI)
- [ ] 警報历史分析與回測
- [ ] 性能指標儀表板 (系統健康檢查)
- [ ] 用戶偏好設定儲存 (深色/淺色模式、語言)
- [ ] 多用戶支援 (認證與授權)
- [ ] 導出功能 (CSV/PDF 報告)

---

## 依賴關係圖

```
Phase 1: 儀表板
  ↓
Phase 2: AI 增強 (獨立)
  ↓
Phase 3: 來源管理
  ↓
Phase 4: 社群監控
  ↓
Phase 5: 新聞分析
```

**關鍵路徑**: Phase 1 → Phase 3 → Phase 4 (共 4-5 週)

---

## 資源分配

| 階段 | 前端 | 後端 | 測試 | 文檔 |
|------|------|------|------|------|
| Phase 1 | 3 天 | 2 天 | 1 天 | 0.5 天 |
| Phase 2 | 1 天 | 2 天 | 1 天 | 0.5 天 |
| Phase 3 | 2 天 | 1 天 | 1 天 | 0.5 天 |
| Phase 4 | 2 天 | 3 天 | 2 天 | 1 天 |
| Phase 5 | 1.5 天 | 1.5 天 | 1 天 | 0.5 天 |

**總計**: ~4 週開發時間

---

## 成功指標 (KPI)

- ✅ 儀表板加載時間 < 2s
- ✅ 實時通知延遲 < 1s
- ✅ 系統正常運行時間 > 99%
- ✅ AI 分析準確率 > 85%
- ✅ 用戶能在 5 分鐘內設定新的監控源

---

**最後更新**: 2026-03-23
**下次檢查**: v0.2.0 計劃開始時
