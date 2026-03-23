# 版本更新日誌 (Changelog)

所有對本項目的重大變更都將記錄於此。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)，
版本號遵循 [語義化版本](https://semver.org/lang/zh-TW/)。

## [0.1.0] - 2026-03-23

### 新增 (Added)
- ✅ 四大核心模塊框架
  - 即時雷達 (Radar) - 自動化市場監控
  - 主題搜尋 (Search) - 用戶主導分析
  - 新聞資料庫 (News DB) - 內容管理與存檔
  - 儀表板 (Dashboard) - 視覺化分析 *[規劃中]*

- ✅ 後端功能
  - FastAPI REST API 架構
  - SQLite 資料庫 + SQLAlchemy ORM
  - APScheduler 定時任務 (每 5 分鐘掃描)
  - WebSocket 實時通知推送
  - Claude AI API 集成
  - Google Sheets 讀寫集成
  - RSS Feed + NewsAPI 資料源
  - 郵件 + LINE Notify 通知服務

- ✅ 前端功能
  - React 18 + Vite 6 開發環境
  - 響應式 Dark Theme 設計
  - 實時 WebSocket 客戶端
  - 四大頁面完整 UI/UX
  - 市場指標卡片與迷你圖表
  - 警報詳細展開面板
  - 位置暴險自動匹配顯示

- ✅ 核心特性
  - 信號條件評估引擎 (優先級評估)
  - 位置暴險匹配算法 (符號/名稱/分類)
  - 情緒分析基礎設施
  - 多通知渠道支援

### 計劃中 (Planned)
- ⏳ 完整儀表板
  - 市場熱度圖 (Heatmap)
  - 情緒指標時序圖
  - 主題趨勢排行
  - 事件時間線

- ⏳ Gemini AI 集成
  - 作為預設 AI 分析服務
  - Claude 作為高級深度分析選項
  - 成本優化配置

- ⏳ 社群媒體監控
  - Twitter/X 帳號追蹤
  - 特定人物監控 (央行總裁、知名分析師等)
  - 社群情緒聚合

- ⏳ 批量新聞分析
  - 每日新聞 AI 分析按鈕
  - 批量情緒分析
  - 重點摘要自動生成

### 已知限制 (Known Limitations)
- 儀表板功能尚未實現
- 僅支援 Claude AI，Gemini 支援開發中
- 無社群媒體監控
- 無特定人物追蹤功能
- 警報通知可能延遲 (取決於 5 分鐘掃描週期)

### 技術細節
- Python 3.10+ + FastAPI 0.104+
- React 18 + Vite 6 + Tailwind CSS 3
- SQLite (無需額外資料庫安裝)
- 非同步 I/O (asyncio)

---

## 版本說明

- **Major (主版本)**: 重大功能變更或 API 破壞性變更
- **Minor (次版本)**: 新增向後兼容的功能
- **Patch (修訂版本)**: 錯誤修復

預期路線圖:
```
v0.1.0 (Current)  → 基礎功能完善
  ↓
v0.2.0            → 完整儀表板 + Gemini 集成
  ↓
v0.3.0            → 社群媒體監控
  ↓
v1.0.0            → 正式版本
```

---

**更新日期**: 2026-03-23
