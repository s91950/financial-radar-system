# 金融雷達 NotebookLM 助手（Chrome Extension）

三顆按鈕讓你可以**手動**對 NotebookLM 做：

1. **匯入剪貼簿 URL** — 讀剪貼簿，抽出所有 URL，逐個匯入到指定 notebook
2. **清空 sources** — 刪除 notebook 內所有非 `[SKILL] ` 開頭的 sources（保留分析框架）
3. **產生分析報告** — 用設定的提示詞產生一份報告，下載後 POST 到 VM `/api/radar/extension-report`，可在 `/analysis` 頁面「Extension 分析」tab 看到

> 與系統現有的 hourly 自動排程（`scripts/notebooklm_hourly.py`）**完全獨立**：
> - 不寫入 `nlm_latest_report` / `nlm_yt_latest_report`，LINE「分析」指令永遠拿到 hourly 的最新版
> - Extension 報告儲存在 `NlmReport(report_type="extension_manual")` + 獨立的 `extension_*` SystemConfig keys
> - 可以同時跑，互不干擾

## 安裝（Load unpacked）

1. 開啟 Chrome，前往 `chrome://extensions/`
2. 右上角開啟「開發人員模式」
3. 點「載入未封裝項目」，選擇本資料夾（`extension/`）
4. 安裝後請務必先**確認已登入 NotebookLM**：開 [https://notebooklm.google.com](https://notebooklm.google.com) 確認可用

## 設定

點工具列 puzzle icon → 此擴充功能 → ⚙ 設定，或在 `chrome://extensions/` 內找此擴充功能 → 「擴充功能選項」。

需要填：
- **新聞 notebook ID** — 從 `notebooklm.google.com/notebook/{ID}` 抓
- **YouTube notebook ID** — 同上，建議用獨立 notebook 給 YT 影片
- **VM API Base URL** — 預設 `http://34.23.154.194`，產生報告後會 POST 到 `{base}/api/radar/extension-report`
- **新聞／YT 提示詞** — 留空使用內建預設（繁體中文、固定 3 點格式、最多 2 分類）

## 使用方式

點 Chrome 工具列的擴充功能 icon（puzzle 圖示 → 此擴充功能）→ 跳出小視窗 → 切換 notebook → 點三顆按鈕之一。

產生的報告會自動推送到 VM，重新整理金融雷達 `/analysis` 頁面 → 點「🧩 Extension 分析」tab 即可看到。

## 注意事項

- **產生報告會等到完成（最久 5 分鐘）**：請保持 popup 開啟。關掉 popup 雖然多數情況 service worker 還會繼續跑，但保險起見不要關。
- **配額**：NotebookLM 每帳號每日有 generate_report 次數限制（依 Google AI 等級而定），手動 + hourly 共用同一帳號額度
- **認證**：Extension 直接用瀏覽器既有的 NotebookLM 登入 cookies，**不再需要** `storage_state.json`、Playwright headed 模式、PSIDRTS 保活那些 hack；認證過期會跳訊息提示

## 故障排除

| 訊息 | 可能原因 |
|---|---|
| `未登入 NotebookLM` | 直接到 [notebooklm.google.com](https://notebooklm.google.com) 重新登入 |
| `無法從 NotebookLM 首頁抽出 CSRF/Session token` | NotebookLM 改了首頁結構，回報以便更新 regex |
| `RPC error for {id}: 401/403` | 認證過期，重登 |
| `RPC ... 回 null` | NotebookLM 可能改了內部 RPC ID 或 payload，需要更新 `lib/notebooklm.js` 的 RPC 常數 |
| 推送 VM 失敗 | 檢查 VM URL 是否正確、VM 服務是否在跑 |

## 與本機 hourly 腳本的對應關係

| 動作 | Extension（手動） | hourly 腳本（自動） |
|---|---|---|
| 認證 | 瀏覽器 cookies | `~/.notebooklm/storage_state.json` |
| 排程 | 使用者按按鈕 | Windows Task Scheduler 每 3 小時 |
| 內容 | 剪貼簿手動 URL | 從 `/api/news/articles` 自動抓 |
| 提示詞 | options 自訂 | `scripts/notebooklm_hourly.py::_build_news_prompt` |
| 推送 endpoint | `/api/radar/extension-report` | `/api/radar/notebooklm-report` |
| 顯示 tab | 🧩 Extension 分析 | 📰 NLM 新聞 / 📺 NLM YouTube |
| LINE「分析」指令 | 不影響 | 取最新 |
