# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 最近重大進度（給新對話的快速摘要）

完整 commit 史用 `git log --oneline` 看，這邊只記跨多檔、影響架構的轉折：

**2026-07-08 — 風險等級全系統改為三級顯示「高 / 中 / 低」＋雷達選取模式**（前端四頁 + backend 通知文字 + scripts，**資料值不變**）：
- **命名轉換（僅顯示層）**：`critical`→顯示「高」（沿用紅色）、`high`→「中」（沿用橘色）、`low`→「低」（綠）；「緊急」一詞全面退場。DB / API / `Alert.content` 的 `{critical}` 前綴 / GAS Sheet 嚴重度欄的英文值**全部不動**，未來看到 UI「高」要對應到程式裡的 `critical`、UI「中」對應 `high`。
- 改動位置：[RadarPage.jsx](frontend/src/pages/RadarPage.jsx)（pills 拿掉 medium、`SEVERITY_LABELS`、新增 `sevMatch()` 讓舊 medium 資料併入「中」篩選）、[NewsDBPage.jsx](frontend/src/pages/NewsDBPage.jsx)（`SEVERITY_CFG` + 兩組 pills）、[SearchPage.jsx](frontend/src/pages/SearchPage.jsx)（`SEV_LABELS` + 風險標記 picker + pills）、[SettingsPage.jsx](frontend/src/pages/SettingsPage.jsx)（布林規則、最低風險等級、GN 僅高風險、嚴重度關鍵字區、LINE 推播門檻）、[notification.py](backend/services/notification.py) `_SEV_LABEL`、[line_webhook.py](backend/routers/line_webhook.py)「通知」回覆改稱「高風險新聞」、`gas_digest.gs` / `perplexity_digest.py` 標籤（GAS 需手動重新部署才生效）。舊 medium 資料一律併入「中」（橘色）顯示與篩選。
- **雷達選取模式**：篩選列新增「選取」切換鈕（在「全選連結」旁），開啟後卡片內勾選框才顯示；關閉時清空已選；「全選連結」點擊會自動開啟選取模式。

**2026-07-07 — 雷達卡片再改版：移除大標題/展開功能，新聞標題變直達超連結**（[RadarPage.jsx](frontend/src/pages/RadarPage.jsx)，純前端）：
- **拿掉卡片大標題**（`[N 則] 標題...`）與**移除編號 `1) 2)`**：卡片不再可點擊展開，直接是一份新聞清單；非 `news` 類型或無新聞行可顯示時仍 fallback 顯示 `alert.title`。
- **新聞標題本身變成超連結**：`content` 行與 `source_urls` 同源同序（後端仍以風險序寫入），前端在**排序前**把 `parseSourceUrl(source_urls[i]).url` 逐行配對綁到該行物件上再一起排序，避免「風險重排後點第 3 則卻開到別篇」；兩陣列長度不一致時（少數缺 URL 的舊告警）整卡退回純文字不給點，寧可不能點也不開錯篇。
- **勾選/複製/收藏功能改做在卡片行內**（取代原本只能在展開詳情面板操作）：每行新聞前有勾選框（key 用含 `{sev}` 前綴的 `source_urls` 原始字串，與篩選列「複製 N 個連結 / 收藏」批次流程共用同一個 `selectedSourceUrls` Set）、卡片 meta 列有「全選」（只勾套用嚴重度篩選後、有 URL 的行）、每行尾端有單行複製按鈕。篩選列「全選連結」按鈕不再需要先套篩選條件才出現。
- **連帶移除的入口（其功能本身未刪，只是拿掉 RadarPage 側呼叫點）**：「AI 深度分析」按鈕（`POST /api/radar/alerts/{id}/analyze`）、「可能影響部位」`exposure_summary` 顯示區塊。**目前狀態**：`exposure_summary` 仍由 `_radar_scan_inner()` 照常計算並寫入 `Alert` 表，但整個前端已無任何頁面顯示它；`radarAPI.analyzeAlert()` 與 `searchAPI.analyzeTopic()` 這兩支 API client 方法目前在全部 `frontend/src/pages/*.jsx` 中都無呼叫端（純 backend 能力保留，UI 入口暫無）——修改「AI 分析」相關功能前務必先 grep 確認呼叫端是否存在，不要假設按鈕還在。

**2026-06-08 — 雷達卡片：風險排序貫通 + 標題改 [N 則] + 一律全部顯示**（[jobs.py](backend/scheduler/jobs.py) + [RadarPage.jsx](frontend/src/pages/RadarPage.jsx)，**部分已被 2026-07-07 改版取代**：標題與編號已移除，風險排序邏輯仍適用於行內顯示順序）：
- **卡片內新聞固定按風險排序** critical→high→medium→low（無等級墊底）。後端建立 Alert 前先對 `new_articles` 做**穩定排序**（`key=_SEVERITY_ORDER[_article_severity(a)]`，同風險維持原收集序），讓 `content` / `source_urls` 以風險序寫入 DB；前端 `orderByMode()` 也對顯示再排一次當保險（舊告警 DB 內仍是收集序，靠前端顯示時重排）。
- **序號跟著風險重編**：前端**先排序再編號**（`num = idx+1`），所以風險最高 = `1)`。**踩坑**：卡片內新聞列表（來自 `content`）與詳情面板「資料來源」清單（來自 `source_urls`）是兩條各自編號的陣列，必須**用同一把風險 key 排序、各自重編號**才能對齊；num 與 url 綁在同一物件一起走，避免「點第 3 則卻開到別篇」。
- **標題一律 `[N 則]`**（含單則 `[1 則]`）：後端直接產 `[N 則]`，不再有 `[N 主題 / N 則]` / `[N 則相關]`。前端 `formatAlertTitle(alert, count)` 把舊告警殘留前綴（`[手動]` / `[N 則相關]` / `[N 主題 / N 則]` / `[N 則]`）剝掉後以實際則數重組（idempotent），新舊告警顯示一致；只對 `alert.type === 'news'` 套用。
- **一律全部顯示**：移除「預設只顯示 3 則、點卡片展開才全看」與「...共 N 則」截斷（桌面 + 手機 `showLines = visibleLines`）。

**2026-06-05 — Extension v0.7.x：定時自動分析（新聞 + YT，瀏覽器活 session，免 notebooklm login）**：
- 痛點：NLM hourly（`notebooklm_hourly.py`）靠無頭 cookie，Google 一直讓它過期 → 自 5/8 停擺。解法是改用「活著的瀏覽器 session」，正是 Extension 的強項（直接吃瀏覽器既有 NotebookLM cookies）。
- [background.js](extension/background.js)：`AUTO_YT_ALARM` 排程（新聞+YT 共用）+ `runAuto(kinds, trigger)` / `_runAutoOne(kind, trigger)` / `setupAutoAlarm()` / `AUTO_FETCHERS{news,yt}`。alarm 喚醒 SW → 依序跑啟用的 kind（news 先 yt 後，`_autoBusy` 單鎖防並發）→ 各自抓 VM（news: `GET /api/news/articles?limit=60` 去重 key=source_url；yt: `GET /api/youtube/videos?new_only=true` 去重 key=video_id）→ 本機去重 → 對該 kind 指定 notebook 跑 `runCombinedForTask`（清空→匯入→產報告→推 `extension-report` kind=news|yt）→ generateOk 才記去重。間隔下限 30 分；`storage.onChanged` 監看 enable/interval 重建 alarm。
- [options.html](extension/options.html) / [options.js](extension/options.js)：「⏰ 定時自動分析（新聞 + YT）」區塊：共用間隔 + 新聞/YT 各自啟用開關、notebook 下拉、立即跑一次、重置去重、即時狀態。新 message：`get_auto_status` / `run_auto_now{kind?}` / `reset_auto_dedup{kind}`。**提示詞顯示**：options 載入時用 `get_settings` 把實際生效的新聞/YT 提示詞（含內建預設）填進 textarea 供檢視編輯。
- **與三路並存**：NLM hourly（📺 NLM，需 login）、VM Gemini（📺 Gemini，最穩備援）、本自動路徑（→ 🧩 Extension 新聞 / 🧩 Extension YT）。前提：Chrome 開著 + 已在某分頁登入 NotebookLM（不需 `notebooklm login` CLI）。
- **v0.7.2 修排程狂跑 bug**：`setupAutoAlarm()` 原本每次 SW 重啟（MV3 閒置即被殺、有事件再起，會重跑 top-level）都 `clear+create` 且 `delayInMinutes:1`，等於把排程反覆重設成「1 分鐘後」→ 變成沒事就跑、燒光 NotebookLM 每日產報告配額（症狀：明明設 3h 卻常跑、報「產生報告失敗：API 沒回 artifact_id（可能配額用盡）」）。修法：alarm 改**冪等** — 已存在且 `periodInMinutes` 相同就直接 return 不重建；首次/改間隔時 `delayInMinutes` 改成一個完整間隔（要立刻跑用「立即跑一次」）。配額是每日限制，當天燒光需隔日才恢復。

**2026-05-21 — LINE 分析指令改回 Extension；Extension 匯入 bug 修正**：
- [line_webhook.py](backend/routers/line_webhook.py)：「分析」/「yt分析」指令從讀 `SystemConfig["nlm_latest_report"]` 改為查 `NlmReport` 表最新 `extension_manual` 記錄（`[news]`/`[yt]` 前綴區分），新增 `_get_latest_extension_report(db, kind)` helper
- [background.js](extension/background.js)：`PER_URL_TIMEOUT_MS` 30s → **60s**（World Bank 等政府網站同步抓取需更長等待，耗時剛好 30s 就是 timeout 觸發）
- [popup.js](extension/popup.js)：`handleCombined()` 改為先讀剪貼簿再 `confirm()`，修正 `confirm()` 後 document 失焦導致 `clipboard.readText()` 拋 "Document is not focused" 的問題；確認訊息同時顯示解析到的 URL 數量

**2026-05-19 — Extension v0.6.3：UI 全面改版 + PDF 超時修正 + 寬鬆匯入判定**：
- **SVG 圖示系統**：popup.html 頂部 `<svg display:none>` 集中定義 13 個 symbol，所有按鈕從 emoji 改成 `<svg class="icon"><use href="#ic-xxx"/>` （black/white stroke currentColor，深/淺色背景均適用）
- **提示詞收藏側邊面板**（`#pp-panel`）：點 ✏️（`#btn-prompt-settings`）滑出 `position: fixed; right: 0` 的書籤式抽屜；選取的提示詞 ID 存 `chrome.storage.local.selectedPromptId`；內容陣列存 `savedPrompts: [{id, name, content}]`
- **Kind chip 預設「不推送」**；批次操作三合一列 `actions-row3`；寬鬆匯入判定 `succeeded > 0`；PDF 超時 `PDF_TIMEOUT_MS = 90_000`（一般網頁 60s）

**2026-05-14 — RBAC 收緊 + LINE 群組彙整推送 + 多處 bug 修正**：
- `ROLE_ORDER` guest 從 1 收回 0；`news_db` / `youtube` router 拿掉 router-level dep，改個別 endpoint 自帶 auth 讓 guest 能 GET
- LINE webhook 加「ID」指令；新增 `line_critical_digest` 排程（台北 07/12/17 彙整 critical 到群組）
- WebSocket URL 改動態 `${window.location.host}/ws`（修全員「離線中」）；`fetched_after` tz bug 修正（GAS pullFromVM 早上 08:00 前看不到當日資料根因）

**目前 VM 狀態速覽**：
- Owner / admin / regular 帳號已建；Service Keys：`hourly_script`（admin，給本機 NLM 排程）、`Chrome Extension`（admin，給瀏覽器 extension）
- `LINE_TARGET_ID` 設為群組 ID（`Ca3a04162d6b77ae4bf91c96f942da655`）；`NotificationSetting.line=0`（即時推播停用），改靠 `line_critical_digest` 3 次/日彙整
- VM `.env` 內 `API_TOKEN` 已清空（legacy fallback 程式碼仍保留以備緊急回退）；本機 `scripts/.env.local` 用 `sk_mX-jyo...` service key

**已知設計取捨 / 仍未做**：
- 仍用 `verify=False` for httpx scrapers（19 處）— 移除需逐一測試各來源 SSL，跳過
- Extension manifest VM URL 仍是 HTTP `35.231.159.224`（要改 HTTPS 需建 Cloudflare named tunnel）
- WebSocket `/ws` 沒做認證 — 只廣播警報通知，敏感性低
- `GET /api/news/export` endpoint 還在但前端按鈕已移除（產出亂碼、實用價值低）
- `Alert.exposure_summary`（部位暴險比對）仍持續計算寫入，但 2026-07-07 RadarPage 改版後前端已無任何頁面顯示它；`POST /api/radar/alerts/{id}/analyze` 與 `/api/search/topic/analyze` 同樣目前無前端呼叫端（詳見上方 2026-07-07 changelog）

**部署備忘**：改 `backend/` → VM `git pull` + `sudo systemctl restart financial-radar`；改 `frontend/` → 加 `cd frontend && npm run build`。VM 用 `s9195000409898` 帳號，SSH key `C:\Users\User\.ssh\google_compute_engine`。

## 修改後 VM 同步提示規則

每次完成程式碼修改後，必須執行以下其中一項：

1. **需要更新 VM** — 在回應最後加一行：
   > 「此修改需要更新到 VM，是否現在執行 `git push` 並在 VM 上 `git pull && sudo systemctl restart financial-radar`？」

2. **不需要更新 VM** — 在回應最後加一行說明原因，例如：
   > 「此修改僅影響本地腳本（`scripts/`），不需更新 VM。」

**判斷基準：**
- 需要更新 VM：`backend/`、`frontend/`、`deploy/` 下的任何檔案修改
- 不需要更新 VM：`scripts/` 下的本地腳本、`CLAUDE.md`、`README.md`、純本地設定檔

## 認證 / RBAC（帳號密碼登入 + 4 級權限）

採用 **JWT + bcrypt** 帳號系統，**Service API Keys** 給非瀏覽器 client（Extension / scripts）。核心檔案：[backend/auth.py](backend/auth.py)、[backend/security.py](backend/security.py)、[backend/database.py](backend/database.py) 的 `User` / `ServiceApiKey` models。

### 角色階層
```
guest(0) < regular(1) < admin(2) < owner(3)
```

### 完整權限對照表
| 動作 / 端點 | guest | regular | admin | owner |
|---|:-:|:-:|:-:|:-:|
| `GET /api/health` | ✅ | ✅ | ✅ | ✅ |
| `POST /api/auth/login`、`GET /api/auth/me` | ✅ | ✅ | ✅ | ✅ |
| `POST /api/line/webhook`（HMAC 自驗）、`/ws` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/radar/alerts`、`/alerts/stats`、`/market`、`/api/radar/notebooklm/gemini/extension-report*` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/news/*`（articles / sentiment / sources / keywords / categories / export） | ✅ | ✅ | ✅ | ✅ |
| `GET /api/youtube/channels`、`/videos`、`/new-count` | ✅ | ✅ | ✅ | ✅ |
| `POST /api/news/fetch`，**`source_type=gn_only`**（只打 Google News RSS） | ✅ | ✅ | ✅ | ✅ |
| `POST /api/auth/change-password` | ❌ | ✅ | ✅ | ✅ |
| `GET /api/research/*`、`/raw-articles/*`、`/search/*`、`/topics/*` | ❌ | ✅ | ✅ | ✅ |
| `POST /api/feedback`（自己留言） | ❌ | ✅ | ✅ | ✅ |
| `PUT /api/youtube/videos/{id}/seen`、`/videos/mark-all-seen` | ❌ | ✅ | ✅ | ✅ |
| `GET /api/utils/resolve-url`、`POST /api/utils/resolve-stored-urls` | ❌ | ✅ | ✅ | ✅ |
| `POST /api/news/fetch`，**`source_type=sources_only`**（觸發大量爬蟲） | ❌ | ❌ | ✅ | ✅ |
| `POST /api/news/save-selected`、`PUT /api/news/articles/{id}` | ❌ | ❌ | ✅ | ✅ |
| `PUT/POST/DELETE /api/radar/alerts/*`（mark read / save / delete / 觸發分析） | ❌ | ❌ | ✅ | ✅ |
| `POST/PUT/DELETE /api/radar/market/watchlist`、`/conditions`（市場關注 CRUD） | ❌ | ❌ | ✅ | ✅ |
| `POST /api/radar/notebooklm-report`、`-yt-report`、`extension-report`、`gemini-analyze`、`scan` | ❌ | ❌ | ✅ | ✅ |
| `DELETE /api/radar/reports/{id}`（NLM/Gemini/Extension 通用刪報告） | ❌ | ❌ | ✅ | ✅ |
| `DELETE /api/news/articles`、`/raw-articles`、`/research`、`/feedback` | ❌ | ❌ | ✅ | ✅ |
| `POST /api/raw-articles/cleanup` | ❌ | ❌ | ✅ | ✅ |
| `POST/PUT/DELETE /api/youtube/channels`、`POST /channels/{id}/check`、`/check-all` | ❌ | ❌ | ✅ | ✅ |
| `POST/PUT/DELETE /api/settings/*`、`/topics/*`（整個 router 都 admin+） | ❌ | ❌ | ✅ | ✅ |
| `GET/POST/PUT/DELETE /api/users/*`（使用者管理）+ reset-password | ❌ | ❌ | ❌ | ✅ |
| `GET/POST/DELETE /api/service-keys/*`（Service Keys 管理） | ❌ | ❌ | ❌ | ✅ |

**`POST /api/news/fetch` 拆細認證**：因為訪客的「新聞資料庫」頁面要能用 Google News 搜尋，但又不能讓他們觸發大量 RSS / MOPS 爬蟲。endpoint 自己讀 `req.source_type`：`gn_only` 放行所有人、`sources_only` 用 `ctx.has_role("admin")` 擋。

**Service API Key 角色**：建立時 owner 指定 `admin` 或 `regular`（不能是 owner）。Extension / hourly script / sync_vm_settings 通常用 admin role 的 service key。

**側欄可見頁面**：
- guest：`/`（雷達）、`/news`（新聞 DB，可搜 GN）、`/analysis`（分析報告）、`/youtube`（YT 監控）
- regular：上述 + `/dashboard`（儀表板）、`/search`（主題追蹤）、`/reports`（研究報告）、`/feedback`、`/raw-articles`
- admin：上述 + `/settings`
- owner：上述 + `/users`、`/service-keys`

### 三模式認證 dependency（[backend/auth.py:get_current_auth](backend/auth.py)）
請求依序嘗試：
1. `Authorization: Bearer <jwt>` — 瀏覽器登入後
2. `X-API-Key: sk_xxx` — Service API Key（non-browser）
3. `X-API-Key: <legacy>` — 舊單一 API_TOKEN（過渡向後相容，視為 admin）
4. 都沒帶 → guest

`require_role("admin")` / `require_regular` / `require_owner` 為 dependency factory，套在 router 或單一 endpoint 上。**過期/無效 JWT 視同 guest**（不 raise 401）— 讓訪客體驗不被「token 失效」打斷，只在點到需登入功能才提示。

### Owner bootstrap
首次啟動 `users` 表為空時，從 env `OWNER_USERNAME` + `OWNER_PASSWORD` 自動建 owner 帳號（`_seed_defaults` 執行）。第一次登入後請改密碼，之後 env 留空也不影響（bootstrap 邏輯只在表空才跑）。

### Service API Keys（[backend/routers/service_keys.py](backend/routers/service_keys.py)）
- Owner 在前端 `/service-keys` 頁建立 / 撤銷
- Key 格式 `sk_<URL-safe 32>`；DB 只存 bcrypt hash + 前 8 字元 prefix
- **完整 key 只在建立當下回傳一次**，遺失只能撤銷重發
- 角色限定 `admin` 或 `regular`（不能是 owner）
- 撤銷 = `is_revoked=True`，下一個請求即 401

### 前端 AuthGate 流程（[frontend/src/components/Layout/AuthGate.jsx](frontend/src/components/Layout/AuthGate.jsx)）
1. 開頁 → 讀 localStorage `jwt` → 呼 `/api/auth/me` 確認還活著
2. 過期 → 後端回 200 guest → AuthGate `clearAuth()` + 渲染 children（訪客模式）
3. 點到 admin endpoint 收到 401 + 帶了 Bearer → axios interceptor 廣播 `auth-required` → AuthGate 跳登入彈窗
4. **沒帶 Bearer 的 401**（訪客背景 fetch 撞 admin endpoint）→ 靜默不擾，不彈登入
5. 403（已登入但角色不夠）→ 也不彈登入（這是權限不足，不是認證失效）

### 訪客背景 fetch 防呆
某些 guest-accessible 頁面（`RadarPage`、`DashboardPage`）有 useEffect 呼叫 admin 端點抓 metadata（如 `settingsAPI.getAIModel()` 顯示 AI 徽章）。**使用者體驗鐵則**：在這些頁面的 useEffect 開頭一定要 `if (!getCurrentUser()) return` 跳過，否則訪客一進首頁就被 401 推進登入彈窗。

### Sidebar 角色感知
`navItems` 每個 entry 可選 `requiresRole` 欄位，[Sidebar.jsx](frontend/src/components/Layout/Sidebar.jsx) 用 `hasRole(role, item.requiresRole)` 過濾顯示。目前設定：
- 無 requiresRole（訪客可看）：`/`、`/news`、`/analysis`、`/youtube`
- `regular`：`/search`、`/reports`、`/dashboard`、`/feedback`、`/raw-articles`
- `admin`：`/settings`
- `owner`：`/users`、`/service-keys`

### 頁面內按鈕角色感知（`hasRole` helper）
[services/api.js](frontend/src/services/api.js) 匯出 `hasRole(minRole)`，前端 ROLE_ORDER 與 backend `auth.py` 同步。**訪客 / regular 可瀏覽的頁面內，任何呼叫 admin endpoint 的按鈕都要包 `{isAdmin && ...}` 不顯示**，這樣訪客不會看到「點下去就 401 / 403」的死按鈕。已套用此模式的頁面：
- `RadarPage`：立即掃描、AI 深度分析、刪除單則 / 已讀、全部已讀、刪除已讀、收藏；`handleMarkRead` 開頭 `if (!isAdmin) return` 避免點卡片靜默 401
- `NewsDBPage`：抓取來源新聞（Google News 訪客可用、刻意不包）、儲存選取、收藏、刪除、「已收藏」篩選
- `AnalysisPage`：手動觸發 Gemini、刪除單份報告
- `YouTubePage`：+ 新增頻道、暫停/啟用/刪除頻道、立即偵測全部、偵測此頻道（給 `canAdmin`）；標記已看（給 `canRegular`）

### 永遠不擋的端點
- `GET /api/health`
- `POST /api/auth/login`、`GET /api/auth/me`（永遠回 200，guest 為合法狀態）
- `POST /api/line/webhook`（自有 HMAC 簽章）
- `/ws` WebSocket

### 啟用 / 撤銷整套帳號系統
**啟用**：VM `.env` 設 `JWT_SECRET=<token_urlsafe(64)>` + `OWNER_USERNAME=` + `OWNER_PASSWORD=` → restart → `users` 表自動建 owner。
**整套停用**：清空 `JWT_SECRET` 會讓 login 端點報錯。較合理的「降低控管」是只設 `API_TOKEN=<legacy>`、不設 JWT — 所有 client 都用 X-API-Key 走 legacy 路徑（admin 角色），但失去多帳號分權。

## 設定資料以 VM 為主

除非使用者特別指示「改本地」或「以本地為準」，否則 **VM 上的設定永遠是唯一的真實來源 (source of truth)**：

- 涉及 `monitor_sources`、`SystemConfig`、`Topic`、`NotificationSetting` 等 DB 內的設定資料時，預設要改 VM（不要先動本地 DB 再叫使用者同步）。
- 查詢「目前用的是哪個來源 / URL / 設定值」，要先看 VM（`ssh -i C:\Users\User\.ssh\google_compute_engine s9195000409898@<VM_IP>` 進入 `/opt/financial-radar`），不要根據本地 `data/financial_radar.db` 推論。
- 本地 DB 可能因長時間未同步而與 VM 不一致，引述本地 DB 內容時要明確標注「（本地，可能過時）」。
- 變更建議優先順序：(1) 引導使用者在 VM 設定頁 UI 上改；(2) SSH 進 VM 直接 SQL 更新；(3) 萬不得已才本地改 + `python scripts/sync_vm_settings.py http://<VM_IP>` 推上去。

### `_migrate_db()` 會覆寫部分 monitor_sources URL — 必須同步改預設值

`backend/database.py::_migrate_db()` 在每次服務啟動時會強制重整某些指定來源的 URL，
若只下 SQL 改 DB 不改程式碼預設值，**下次重啟必被回覆**。今天踩過的坑：手動 SQL 把
鉅亨網 - 美股改成 `wd_stock_all`，重啟後 migration 沒找到舊 URL，退而以名稱查找
並把 URL 寫回預設 `category/us_stock`。

修改任何下列 migration 區塊涵蓋的來源時，**必須同時改 `database.py` 內的預設常數**：
- `_rss_url_fixes`（鏡新聞、財訊、商周、經濟學人、Politico、自由時報等）
- `_cnyes_api`（鉅亨網台股 / 頭條 / 美股）
- `_ctee_migrate`（工商時報）
- `_broken_urls`（已停用清單，列在裡面就會被 `is_active=0`）
- 其他任何含 `UPDATE monitor_sources SET url=...` 或 `UPDATE monitor_sources SET is_active=...` 的常數列表

若新 URL 與遷移名單上某條既有 URL 不同，記得也把舊 URL 加進對應的 dedup / 停用清單，
避免遷移後留下無作用的孤兒列。

## Project Overview

金融即時偵測系統 (Financial Real-time Detection System) — a multi-module system for monitoring financial markets, aggregating news, tracking research papers, and matching position exposure. Built for senior financial analysts who need real-time alerts via LINE/Email/Web with event summaries, position exposure, and source links.

**Language:** All UI text and comments are in Traditional Chinese (繁體中文). AI analysis output should also be in Traditional Chinese.

## Deployment (Production)

The system runs on **Google Cloud e2-micro VM** (us-east1-d, always free). Production stack:

```
Internet → nginx (:80) → React static (frontend/dist/)
                       → FastAPI (:8000, via proxy)
                       → WebSocket (/ws)

LINE Webhook → Cloudflare Tunnel (HTTPS) → nginx → /api/line/webhook
```

- **Backend service**: `systemd` unit `financial-radar.service`, auto-starts on boot
- **Cloudflare Tunnel**: `systemd` unit `cloudflared.service`, provides HTTPS for LINE webhook (trycloudflare.com URL changes on VM reboot)
- **Deploy scripts**: `deploy/` — `setup.sh`, `deploy.sh`, `financial-radar.service`, `nginx.conf`
- **DB path on VM**: must use absolute path `sqlite:////opt/financial-radar/data/financial_radar.db` in `.env` (relative path fails under systemd)
- **Service user**: VM username is `s9195000409898` (not `ubuntu`) — service file `User=` must match
- **SSH key**: `C:\Users\User\.ssh\google_compute_engine` — use with `ssh -i` to connect to VM

### Update Production After Code Changes
```bash
# Local
git add . && git commit -m "..." && git push

# On VM (SSH)
cd /opt/financial-radar && git pull
sudo systemctl restart financial-radar
# Frontend changes also require:
cd frontend && npm run build && sudo systemctl restart financial-radar
```

## Commands

### Backend (FastAPI + Python 3.10+)
```bash
# Install dependencies
pip install -r backend/requirements.txt

# Start dev server (from project root)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Health check
curl http://localhost:8000/api/health

# Restart in background (bash)
pkill -f "uvicorn backend.main:app"; sleep 1
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
```

### Frontend (React 18 + Vite 6)
```bash
cd frontend
npm install
npm run dev      # Dev server on :5173, proxies /api and /ws to :8000
npm run build    # Production build to dist/
```

### Tests & Linting
本專案目前**無**自動化測試（pytest / vitest）與 lint 設定（ruff / eslint）。
驗證方式：直接啟動後端 `curl http://localhost:8000/api/health`，前端手動操作。

### Both (convenience scripts)
```bash
./start.sh       # Linux/Mac
start.bat        # Windows
```

## Architecture

```
Frontend (:5173) → Vite proxy → FastAPI Backend (:8000)
                                  ├── REST API (/api/*)
                                  ├── WebSocket (/ws) — real-time broadcasting
                                  └── APScheduler — 4 background jobs
```

`vite.config.js` also whitelists `*.ngrok-free.app` / `*.ngrok-free.dev` hosts for remote tunnelling.

### Modules (10 pages)

1. **即時雷達 (Radar)** `/` — Auto-scans RSS + Google News every 5min, creates alerts with position exposure computed server-side. Cards are a flat list of clickable article-title links (direct to source, no card expansion) — see 2026-07-07 changelog entry above for why `exposure_summary` and the alert-analyze endpoint currently have no display surface in this page.
2. **主題追蹤 (Topics)** `/search` — User-defined topics with boolean keywords. Radar auto-imports matching articles AND merges them into radar alerts.
3. **新聞資料庫 (News DB)** `/news` — Fetch returns a **preview** (not auto-saved). User selects which articles to save to SQLite + Google Sheets. Includes sentiment/heat dashboard. Source and keyword filter dropdowns; source list cross-references `MonitorSource` names, ungrouped sources show as "其他". Articles display `matched_keyword` tags inline.
4. **研究報告 (Research)** `/reports` — Daily auto-fetch from IMF, BIS, Fed, ECB, BOJ, BOE, NBER. Dual-mode: RSS for working feeds, **RePEc/IDEAS HTML scraping** for institutions with broken RSS (IMF, ECB, NBER). Same preview → select → save flow.
5. **市場儀表板 (Dashboard)** `/dashboard` — Market indicators, sentiment charts, heat map.
6. **YouTube 監控** `/youtube` — Monitors YouTube channels for new videos, stores in `YoutubeVideo` table with `is_new` flag.
7. **分析結果** `/analysis` — Displays AI analysis reports. **檔案總管式導覽**（不是分頁 tabs）：頂層 `ENGINES`（🧩 Extension / 🤖 Gemini / 📔 NotebookLM）→ 子層 `KINDS`（📰 新聞 / 📺 YouTube）→ 報告清單 → 單份報告，靠 `path` state（`[]` / `[engine]` / `[engine, kind]`）做麵包屑下鑽，開啟某份用 `viewing = {leafKey, id}`。`TAB_CONFIG` 以 `{engine}_{kind}` 為 key 共 **6 個 leaf**（`extension_news` / `extension_yt` / `gemini_news` / `gemini_yt` / `nlm_news` / `nlm_yt`）+ 手動觸發 Gemini 分析按鈕. Each history pill has a hover-revealed × delete button; single-report view has a 「🗑 刪除」 button in the header. Calls `DELETE /api/radar/reports/{id}` (generic — works for NLM/Gemini/Extension), which also re-points the relevant `SystemConfig.*_latest_report` to the next-newest row of the same `report_type` (or clears it if none) so LINE commands and other consumers don't see stale data. NLM reports from local `notebooklm_hourly.py` (auto, every 3h); Gemini reports from VM-side `gemini_analysis.py` (auto, every 3h); **Extension 分析** from the Chrome Extension (`extension/`, manual via popup, fully isolated from hourly — see "Chrome Extension" section); the news/YT split is filtered server-side by `source_title` prefix `[news]` / `[yt]` (推送時 `notebook_kind` 帶入). Lazy-loads from `GET /api/radar/notebooklm-report`, `GET /api/radar/notebooklm-yt-report`, `GET /api/radar/gemini-report`, `GET /api/radar/gemini-yt-report`, `GET /api/radar/extension-report?kind=news|yt`. Tab colours: NLM = primary（紫紅）, Gemini = blue, Extension = violet.
8. **意見回饋 (Feedback)** `/feedback` — User submits improvement suggestions with category (功能建議/問題回報/介面改善/其他意見). History list with delete. Backend: `Feedback` model in `database.py`, `routers/feedback.py` (`GET /api/feedback/`, `POST /api/feedback/`, `DELETE /api/feedback/{id}`).
9. **篩選前資料 (Raw Articles)** `/raw-articles` — 雷達在 RSS/MOPS/website/GN 各取得點 INSERT OR IGNORE 寫入 `RawArticle` 表的所有原始文章（任何篩選之前），滾動保留 7 天。每天 04:15 UTC 自動清理 7 天前資料 + `incremental_vacuum`。最終通過所有篩選的 URL 在掃描末尾標記 `filter_status='passed'`，讓使用者能區分哪些被指紋去重 / 排除關鍵字 / 財經篩選擋掉。頁面含總覽卡（總筆數 / 進雷達 / 被篩掉 / 最新抓取）+ 來源類型分布 + 搜尋（沿用 NewsDB normalize+n-gram 容錯）+ 篩選 + 列表（**來源篩選用下拉選單**，從 `GET /raw-articles/sources` 動態載入已出現過的來源 + 計數）。Backend：`RawArticle` model（`(source_url, title)` 部分 UNIQUE 索引、`fetched_at` / `source` 普通索引）、`routers/raw_articles.py`（GET /articles, /stats, /sources; DELETE /articles/{id}; POST /cleanup）、`scheduler/jobs.py` 中的 `_record_raw_articles`、`_mark_raw_articles_passed`、`cleanup_raw_articles`。設計原則：不存全文 body（只存 RSS summary 或前 500 字），單列 ~500 B–1.5 KB，7 天估 <100 MB。

**dedup 索引必須走 `_migrate_db()`，不能用 model 的 `index=True`**：歷史上 `Column(source_url, index=True)` 讓 `Base.metadata.create_all` 搶建非 UNIQUE 索引 `ix_raw_articles_source_url`，後續 migration 的 `CREATE UNIQUE INDEX IF NOT EXISTS` 看到同名就跳過、`INSERT OR IGNORE` 形同無效。雷達各 step（RSS / Pass A2 / GN / Topic Pass B）會對同一批文章重複呼叫 `_record_raw_articles`，沒有 UNIQUE 守門時每次掃就乘倍數（VM 觀察到 9k 筆膨脹成 30 萬筆）。修法：model 拿掉 `index=True`，migration 裡先 DELETE dup → DROP 舊普通索引 → CREATE UNIQUE INDEX `ix_raw_articles_url_title` ON `(source_url, title)` WHERE source_url 非空。新增任何 `(col, index=True)` 同時又在 migration 想建 UNIQUE 的欄位，請複製這個踩坑案例的處理方式。
10. **系統設定 (Settings)** `/settings` — Sources, notifications, Google Sheets, AI model, radar topics.

### Backend Layer Structure
- **`routers/`** — FastAPI endpoints. Each router has a `/api/{prefix}` path.
- **`services/`** — Business logic. Key services:
  - `ai_factory.py` — selects Gemini or Claude based on config
  - `exposure.py` — position keyword scoring
  - `finance_filter.py` — local financial relevance scoring (TF-IDF approximation, no API): `compute_finance_relevance(title, content) → float`. Three-tier vocabulary: `FINANCE_CORE` (×3 weight), `FINANCE_CONTEXT` (×1), `NON_FINANCE_INDICATORS` (−2 penalty). Formula: `(core×3 + context − non_fin×2) / sqrt(word_count)`, clipped to [0, 1].
  - `simple_ner.py` — rule-based entity extraction (stock codes, companies, central banks, currencies) used to enrich `exposure_summary` when no position match is found
  - `mops_scraper.py` — 公開資訊觀測站 material disclosure scraper. MOPS fully migrated to Vue SPA in late 2025; the old AJAX HTML endpoint (`mops/web/ajax_t05sr01`) is blocked by security policy. Uses new JSON API: `POST https://mops.twse.com.tw/mops/api/home_page/t05sr01_1` with `{"count": N, "marketKind": "sii"|"otc"}`. Dates in 民國 format (`115/04/11`). Fetches up to 100 items per market type (sii + otc). **URL includes date+time** (`?TYPEK=sii&co_id=2330&d=1150411&t=1050`) so multiple disclosures from the same company each get a unique URL (prevents dedup collision in `seen_urls`).
  - `cnyes_scraper.py` — 鉅亨網 JSON API fetcher. 主端點 `api.cnyes.com/media/api/v1/newslist/category/{category}`；支援的分類見模組 docstring（`tw_stock` / `us_stock` / `wd_stock` / `headline` / `forex` / 等）。`is_cnyes_api_url()` 同時匹配網頁分類頁 URL（`news.cnyes.com/news/cat/{slug}`），透過 `_resolve_api_url()` 內部轉成 API URL；`_PAGE_SLUG_MAP` 處理 slug ≠ API 代碼的例外（目前只有 `wd_stock_all` → `wd_stock`，因為網頁聚合頁 slug 帶 `_all` 後綴 API 不接受）。DB 端可填網頁 URL 讓使用者直觀辨識。
  - `worldbank_scraper.py` — World Bank JSON API fetcher. Uses `search.worldbank.org/api/v2/news?format=json`. Fields use `{"cdata!": "..."}` wrapper. Filters English-only in code (API `lang_exact` param is unstable).
  - `fsc_scraper.py` — 金管會 (FSC) HTML scraper. FSC RSS feed is broken (returns HTML), so scrapes `news_list.jsp` page with BeautifulSoup. ~15 news links per page. Dates in 民國 format.
  - `caixin_scraper.py` — 財新 Caixin Global HTML scraper. Caixin RSS returns 403, so scrapes `/news/` page. Article URLs contain date patterns (`/YYYY-MM-DD/`). ~25 articles per page.
  - `storm_scraper.py` — 風傳媒 sitemap scraper. **Currently unused**: storm.mg's CloudFront/WAF blocks GCP IP ranges (all paths return 403 from VM, even though local IPs get 200). Falls back to Google News `site:storm.mg when:3d` proxy. Code retained in case CDN policy changes.
  - `taisounds_scraper.py` — 太報 HTML scraper. No RSS; uses standard sitemap (`taisounds.com/sitemap.xml` with `lastmod`), then parallel-fetches `og:title` / `og:description` from each article page.
  - `linetoday_scraper.py` — LINE Today 國際 scraper. Next.js SSR page embeds article data in `__NEXT_DATA__` JSON — walks the object recursively to find dicts with `title + id + publishTimeUnix`. Article URL: `https://today.line.me/tw/v3/article/{id}`.
  - `udn_scraper.py` — 聯合新聞網分類頁 scraper. `udn.com/news/cate/` pages are server-side rendered HTML; BeautifulSoup finds `<a href="/news/story/...">` links with sibling `<time>` tags (YYYY-MM-DD HH:MM Taiwan time → UTC).
  - `fed_scraper.py` — 聯準會全站最新消息 scraper. Scrapes `federalreserve.gov/recentpostings.htm` (server-side rendered, no pagination), covering all content types: press releases, speeches, Beige Book, FEDS Notes, statistical releases, meeting notices. Parses `.eventlist__time time` (M/D/YYYY) + `.eventlist__event p` (type link + description). Returns `category="official"`, `source="聯準會 (Fed)"`. `is_fed_url()` matches `federalreserve.gov/recentpostings`.
  - `ctee_scraper.py` — 工商時報 RSS scraper. Fetches `ctee.com.tw/rss_web/livenews/{category}` (官方 livenews RSS, ~15 articles per refresh, 分鐘級新鮮度). Built as a custom scraper instead of generic RSS path because `<pubDate>` lacks timezone marker (e.g. `2026-05-06T11:57:13`) but is actually Taiwan local time — must convert TW+8 → UTC. `is_ctee_url()` matches `ctee.com.tw/rss_web` or `ctee.com.tw/livenews`; if a livenews page URL is given, auto-rewrites to the matching `rss_web` endpoint. Categories: `ctee` (綜合，預設), `policy`, `stock`, `finance`, `p-tax`, `industry`, `house`, `world`, `china`, `tech`, `life`. Replaces previous Google News `site:ctee.com.tw` proxy (1-3h lag).
  - `nownews_scraper.py` — NOWnews 今日新聞 Google News Sitemap scraper. Fetches `nownews.com/newsSitemap-daily.xml` — the sitemap embeds `<news:title>` and `<news:publication_date>` per `<url>` so no per-article fetch is needed. Returns ~50-60 articles within 2h on a busy day, freshness within 5-15 minutes. Replaces GN `site:nownews.com` proxy. `is_nownews_url()` matches `nownews.com` + `sitemap` substring. NowNews has no public RSS; the sitemap path is listed in `robots.txt`.
  - `treasury_scraper.py` — US Treasury 美國財政部新聞稿爬蟲. `home.treasury.gov/rss.xml` 內容主要是 admin/reference 頁面更新（Tribal/Capital Program summaries、FAQ），不是實際的新聞稿。改抓 `home.treasury.gov/news/press-releases` 的 server-side rendered HTML，每篇包在 `<div class="mm-news-row">` 內，含 `<time datetime="...">` 與 `<a href="/news/press-releases/sbXXXX">`。每頁約 16 篇新聞稿，涵蓋約 1-2 週。`is_treasury_url()` matches `home.treasury.gov` + (`press-releases` | `rss`).
  - `businessweekly_scraper.py` — 商業周刊「今日最新」HTML 爬蟲。商周提供的 cmsapi RSS（`cmsapi.businessweekly.com.tw/?CategoryId=...`）內容偏向 `/focus/`、`/style/` 子站，會跳過 `/business/` 與雜誌主刊。改抓 `https://www.businessweekly.com.tw/latest` 頁面，該頁面由 jQuery 動態載入，後端透過 `POST https://www.businessweekly.com.tw/latest/SearchList` (`{CurPage: 0|20|40}`) 取得 HTML 片段（每頁 20 篇 figure.Article-figure 區塊），解析標題、URL、`Article-date`（YYYY.MM.DD，無時間，當地 00:00 → UTC）與 `Article-author`。`_MAX_PAGES=3`，最多抓 60 篇；遇到 `IsLast=Y` 或文章日期早於 cutoff 即停止。`is_businessweekly_url()` matches `businessweekly.com.tw/latest`.
  - `yahoo_scraper.py` — Yahoo Finance / Yahoo News 多端點並發抓取器，兩種模式共用同一函式。Yahoo 的「總覽級」RSS 在 2026-05 觀察到都不新鮮：`finance.yahoo.com/{rss/topstories,news/rssindex}` 卡 2-3 天、`news.yahoo.com/rss/topstories` 落後 ~12 小時。但「子分類級」feeds 都是分鐘級新鮮度。模式：
    - **Finance 模式**（URL 含 `feeds.finance.yahoo.com`）：並發抓 `feeds.finance.yahoo.com/rss/2.0/headline?s=<ticker>&region=US&lang=en-US`，預設 ticker `^GSPC,^DJI,^IXIC,SPY,QQQ,AAPL,TSLA,NVDA`（三大指數+兩支 ETF+幾支權值股），每個 ticker 20 篇是 Reuters/Motley Fool/Bloomberg/Barron's 聚合。`source` 標為 `Yahoo Finance`。
    - **News 模式**（URL 含 `news.yahoo.com`）：並發抓 `news.yahoo.com/rss/<category>`，預設 category `world,us,business,tech`（每個 5 篇但都在 30 分鐘內，避開 `politics` 因更新較慢）。`source` 標為 `Yahoo News`。
    DB 端 URL 帶 query string 解析子端點列表：finance 用 `?s=<ticker,...>`、news 用約定別名 `news.yahoo.com/rss/multi?c=<category,...>`（`multi` 是 scraper 識別字、非真實 endpoint）。並發抓取後按 `(source_url, title)` 去重，finance 模式單次 ~90-130 unique 篇，news 模式 ~20 篇。`is_yahoo_url()` matches `feeds.finance.yahoo.com` / `finance.yahoo.com/topic/latest-news` / `news.yahoo.com/rss`。
  - **Website scraper dispatch** (`_fetch_website_source()` in `jobs.py`): URL-based routing via `is_*_url()` predicates → `fed_scraper` | `cnyes_scraper` | `worldbank_scraper` | `fsc_scraper` | `caixin_scraper` | `storm_scraper` | `taisounds_scraper` | `linetoday_scraper` | `udn_scraper` | `ctee_scraper` | `nownews_scraper` | `treasury_scraper` | `businessweekly_scraper` | `yahoo_scraper` | generic `web_scraper`. To add a new scraper: create `is_xxx_url()` + `fetch_xxx()`, add routing in `_fetch_website_source()`, and add test support in `settings.py` `test_rss_source()`.
  - `research_feed.py` — dual-mode RSS/HTML scraper for research institutions
  - `article_fetcher.py` — **full-body enrichment** for radar candidates. After dedup, runs `enrich_articles_with_full_body(articles, concurrency=5, timeout=5.0)` on the 5-30 surviving articles: parallel HTTP GET each `source_url`, extract `<article>`/`<main>` text and overwrite `article['content']`; also salvages `published_at` from JSON-LD `"datePublished"` / `<meta property="article:published_time">` / `<meta itemprop="datePublished">` / `<time datetime>` (in that order) when RSS didn't supply one (e.g. Nikkei Asia RSS 1.0 has no pubDate). Skips when content ≥ 500 chars AND `published_at` already set, or when URL is still `news.google.com` (unresolved). Failure is silent — falls back to RSS summary. **This is what makes exclusion-keyword filtering and severity assessment see real article body**, since RSS `summary` is usually only the title + first one or two sentences.
  - `source_health.py` — `mark_attempt(url, success, error=None)` writes `MonitorSource.last_attempt_at` / `last_success_at` / `last_error`. Called by every scraper's HTTP try/except branch (success → update both timestamps + clear error; failure → update attempt + set error, keep last_success_at). Best-effort: own session, swallows DB errors so health-tracking failures never break a scan. Used by `GET /api/settings/source-health` and the LINE 「來源」 command to surface silently-dead sources.
  - `google_news.py` — Google News RSS search + URL decode. Two-tier decode for GN article IDs: (1) base64 protobuf direct extraction for old format (no network), (2) **individual** `batchexecute` per article for new `AU_yq...` format — each article decoded independently to avoid batch response ordering issues that cause title/URL mismatch. `_DECODE_CONCURRENCY=5` limits parallel requests.
  - `rss_feed.py` — RSS parser + keyword filtering. `fetch_multiple_feeds(feeds, ...)` overrides each article's `source` field with `MonitorSource.name` as-is (no cleaning/stripping — user-defined names like "經濟日報 - 國際" are preserved verbatim). When `return_raw=True` returns `(filtered_articles, all_raw_articles)` tuple; raw pool used for topic cross-matching in Pass A2. Module-level `_parse_topic_groups(topic)` and `_extract_display_kw(topic, text_lower)` are imported by `jobs.py`. `_annotate_matched_terms(article, keywords)` — used in `fetch_all` mode: iterates ALL keywords, collects every term that appears (deduped), but only if the keyword's full boolean AND-condition is satisfied. `_resolve_gn_article_urls(articles)` — called after standard redirect resolution in `fetch_rss_feed()`; extracts article IDs from `news.google.com/rss/articles/CBMi...` URLs and decodes them via `google_news._resolve_google_news_urls()` (same two-tier decode). **Keyword matching helpers**: `_term_in_text(term, text_lower)` — uses word-boundary regex for pure-ASCII terms so "Coup" does not match "Couple"; CJK terms use substring match. `_strip_not_terms(topic)` — extracts `NOT term` / `NOT "multi word"` clauses from a keyword string before group parsing; returns `(cleaned_topic, [not_terms])`. Used by `_matches_topic()` (fail-fast if any NOT term appears in text), `_extract_display_kw()`, and `_annotate_matched_terms()`.
- **`scheduler/jobs.py`** — Nine async jobs: `radar_scan` (5min), `market_check` (60min), `daily_news_fetch` (daily, hour from `NEWS_SCHEDULE_HOUR` in server timezone — VM is UTC), `daily_research_fetch` (daily 10:00), `youtube_check` (30min, parallel asyncio.gather + Semaphore(5)), `mark_all_youtube_seen` (daily 23:00 UTC = 07:00 Taipei — bulk-clears `YoutubeVideo.is_new=False`), `gemini_analysis` (every 3h, first run 5min after startup), `cleanup_raw_articles` (daily 04:15 UTC), `line_critical_digest` (cron `hour=23,4,9` UTC = 台北 07:00 / 12:00 / 17:00 — 推送上次推送以來的 critical Alert 給 `LINE_TARGET_ID`，沿用 `send_line_broadcast`).
  - **`misfire_grace_time` is critical**: APScheduler defaults to 1 second, so when the asyncio event loop is busy with a long-running job (e.g. radar scan taking 5–30s), other jobs get silently skipped. **All jobs must set `misfire_grace_time=600` (interval) or `3600` (cron) + `coalesce=True`** so delayed triggers still execute and accumulated triggers collapse to one. Adding a new job without these = it WILL be silently skipped sometimes. Symptom: `journalctl` shows `Run time of job ... was missed by 0:00:03`, user reports "auto detection didn't run, manual trigger suddenly returns N items".
- **`database.py`** — SQLAlchemy ORM models + `_migrate_db()` for idempotent schema migrations + `_seed_defaults()` for initial data. Seeds only run when tables are empty. 15 models total (added `RawArticle` for 篩選前資料).
- **`scripts/`** — Auxiliary tools (none are part of the main app runtime):
  - `gas_digest.gs` — Google Apps Script digest
  - `perplexity_digest.py` — Perplexity API integration
  - `notebooklm_hourly.py` — local Windows Task Scheduler job (every 3 hours): pulls news articles and YouTube videos from API, imports to NotebookLM notebooks, saves analysis to `scripts/nlm_reports/`
  - `claude_yt_analyze.py` + `claude_yt_analysis_playbook.md` — **fallback** path for YT analysis when NLM auth is dead: `fetch` (new videos, local `.claude_yt_state.json` dedup) / `push` (Claude Code writes the analysis itself, posts to `extension-report` kind=yt). Driven by a `/loop`. Uses Claude tokens (the Extension v0.7 auto path is preferred — NLM-quality, near-zero tokens). Reads VM URL + service key from `scripts/.env.local`.
  - `skills/` — permanent NLM source files (`PROJECT_INSTRUCTIONS_v2.md`, `SKILL_*.md`). Loaded into each notebook once via `_ensure_skill_sources()` and never deleted. Identified by `[SKILL] ` title prefix.
  - `sync_vm_settings.py` — reads local SQLite DB and pushes all settings (system_config, monitor_sources, topics) to the production VM via REST API. Run: `python scripts/sync_vm_settings.py http://<VM_IP>`. Uses URL alias map to handle sources that changed URLs between local and VM.
  - `check_sources_health.py` — async health check for all monitor sources. Dispatches to the same scraper logic as the backend (rss, cnyes, worldbank, fsc, caixin, mops). Run: `python scripts/check_sources_health.py [http://<VM_IP>] [--active-only] [-v]`. Requires `pip install httpx feedparser beautifulsoup4`.
  - `backfill_published_at.py` — one-shot tool to re-enrich existing DB rows where `Article.published_at IS NULL`. Run on VM: `cd /opt/financial-radar && ./venv/bin/python scripts/backfill_published_at.py`. Reuses `services.article_fetcher.enrich_articles_with_full_body`, so success rate depends on whether each source's HTML carries JSON-LD / OG meta dates (works well for Nikkei, less so for FSC and 聯合新聞網 which use non-standard date markup).

### Key Design Decisions

- **AI is never auto-triggered** in scans or searches. The `analysis` field on Alert starts as `None`; on-demand trigger is `POST /api/radar/alerts/{id}/analyze` or `POST /api/search/topic/analyze`. **Currently no frontend page calls either** (RadarPage's button was removed 2026-07-07; SearchPage never had one wired) — the endpoints and `radarAPI.analyzeAlert()` / `searchAPI.analyzeTopic()` client methods still exist for a future UI or direct API use.
- **AI Factory pattern** (`services/ai_factory.py`): `get_ai_service()` returns either `gemini_ai` or `claude_ai` module based on `DEFAULT_AI_MODEL` config. Both expose identical interfaces: `analyze_news()`, `analyze_news_for_alert()`, `search_and_analyze()`, `analyze_market_signal()`. **Gemini is default** (free tier).
- **Signal conditions** use priority-based evaluation — first matching condition wins. Market alerts fire only on **state change** (prevents duplicates).
- **Position exposure** matching (`services/exposure.py`) uses keyword scoring: symbol match (+3), name match (+2), category match (+0.5).
- **Google Sheets** integration: Dual mechanism — **VM pushes instantly** via `append_news_via_gas()` (radar scan + daily fetch + user save-selected), **GAS `pullFromVM()` pulls every 30min** as backup. `GOOGLE_APPS_SCRIPT_URL` must be set on VM `.env` only; local `.env` should leave it **empty** to prevent local dev from pushing to Sheets. Service Account JSON is legacy fallback. Sheet1 = positions (read), Sheet2 = news archive (append). GAS payload fields: `入庫時間`, `標題`, `嚴重度`, `來源`, `關鍵字`, `網址`.
- **Research feed dual-mode** (`services/research_feed.py`): Detects URL pattern — `ideas.repec.org` URLs use HTML scraping (listing page → parallel detail page fetch for metadata); all other URLs use standard RSS/feedparser. This exists because IMF, ECB, and NBER have broken RSS feeds.
- **WebSocket** broadcasts four event types: `radar_alert`, `market_alert`, `daily_summary`, `research_summary`.

### Radar Scan Flow (`scheduler/jobs.py → _radar_scan_inner`)

Four article sources are collected into `new_articles` **before** any saving or early-return:

1. **RSS sources** — all active `MonitorSource` where `type in ("rss", "social")`, filtered by source keywords OR global `_global_topics` (union, not exclusive). `_global_topics = radar_topics + radar_topics_us + 所有 active Topic.keywords` — **Topic.keywords 必須併入**，否則 GN 啟用時 Pass A2 不跑，只命中主題追蹤關鍵字、不命中雷達關鍵字、來源 keywords 也沒命中的文章會被丟掉（fetch 預覽看得到、雷達卻沒存的最大破口）。`fetch_multiple_feeds(return_raw=True)` 也返回未過濾的 raw pool 給 Pass A2 用。
2. **MOPS** — active `MonitorSource` where `type="mops"`, fetches 公開資訊觀測站 material disclosures via `services/mops_scraper.py`
3. **General Google News** — each topic in `SystemConfig["radar_topics"]` (TW) + `SystemConfig["radar_topics_us"]` (US), `max_results=20`, `hours_back` from `SystemConfig["radar_hours_back"]` (default 24h). Skipped if `_skip_gn=True`. If `gn_critical_only=true`, each GN article is pre-assessed — non-critical articles are discarded before being added to `new_articles` (RSS articles are never filtered this way).
4. **Topic keyword searches** — every active `Topic` processes articles in two sub-passes:
   - **Pass A2** (new, RSS-only mode only): when `_skip_gn=True`, the raw unfiltered RSS pool is cross-matched against the topic's boolean keywords. Catches articles that passed RSS fetch but didn't match the radar topic filter.
   - **Pass B** (skipped when `_skip_gn=True`): dedicated Google News search for this topic using `_multi_search_topic()`. If `gn_critical_only=true`, non-critical GN results are dropped (but still saved to `TopicArticle`).

   Results from both passes are merged into `new_articles`, so topic-tracked articles **do** generate radar alerts.

**RSS priority mode**: if `radar_rss_min_articles > 0` and RSS has collected ≥ that many articles (and not a forced scan), Google News steps are skipped entirely. Controlled by `SystemConfig["radar_rss_min_articles"]` (default `"0"`, disabled). `radar_rss_only=true` also skips Google News unconditionally. Both cases set `_skip_gn = True`.

**`fetch_all` source mode**: `MonitorSource.fetch_all=True` bypasses keyword filtering entirely — all articles from that source enter `new_articles`. Keyword matching still runs via `_annotate_matched_terms` using the **union of source keywords + all radar topic keywords** to produce badge labels, but only for keywords whose full boolean AND-condition is satisfied (no partial-match badges). This ensures even sources with no configured keywords still show radar-topic badges when matched. Articles from `fetch_all` sources carry `fetch_all_source=True` in the article dict, which causes the finance filter to skip them (they pass unconditionally regardless of relevance score). Finance relevance is still computed for composite scoring.

**Finance filter** (optional, off by default): if `finance_filter_enabled=true`, articles scoring below `finance_relevance_threshold` (default 0.15) are dropped before saving. Articles with `fetch_all_source=True` are exempt. Even when disabled, `finance_relevance` is still computed per article for the composite score.

**Article scoring** (`_compute_article_scores()`): runs before `db.add(Article(...))` and writes five fields: `decay_factor = exp(-0.1 × hours_elapsed)`, `novelty_score = 1/(1 + similar_count)` (Jaccard ≥ 0.5 against `seen_content_fps`), `finance_relevance` (from filter above), `intensity_score = abs((pos−neg)/total)` using sentiment keywords, `composite_score = decay × novelty × max(relevance, 0.05) × (0.5 + 0.5 × intensity)`.

**Global exclusion keywords**: `SystemConfig["radar_exclusion_keywords"]` (JSON array) — applied after all 4 collection steps but before dedup/saving. Any article whose title+content contains an exclusion term (via `_term_in_text`) is dropped. Managed in SettingsPage "全域排除關鍵字" section.

After collection, articles pass through **three dedup layers** before saving:
1. In-memory exact URL + title match
2. DB check against `Article` table (URL + title)
3. **Content fingerprint** (`_article_fingerprint` → Jaccard similarity ≥ 0.65) — catches same story from different sources with different titles. `seen_content_fps` list is shared across all 4 steps.

**Full-body enrichment** (between dedup and exclusion filter, [jobs.py:687](backend/scheduler/jobs.py#L687)): `await enrich_articles_with_full_body(new_articles)` from `services/article_fetcher.py`. Replaces RSS-summary `content` with extracted main text, salvages `published_at` from HTML metadata. Adds 1-5s/scan but makes `radar_exclusion_keywords`, severity assessment, and DB-stored `Article.content` see real body text rather than just title + first sentence.

**RawArticle recording** — `_record_raw_articles(db, articles, source_type)` is called immediately after each fetch step (RSS raw pool / MOPS / each website source / each GN topic batch / Topic Pass B), inserting all fetched articles into `raw_articles` via `INSERT OR IGNORE` (URL unique). After all filtering, `_mark_raw_articles_passed(db, urls)` marks the survivors as `filter_status='passed'`. The 篩選前資料 page uses this to show what was filtered out. Don't store full body in `RawArticle` — only RSS summary or first 500 chars (saves 90% disk space).

If nothing new, scan exits. Otherwise: save to `Article` DB + `TopicArticle`, then create one Alert.

**Dedup key** format: `scan:{YYYYMMDDHH}:{md5(first_title)[:16]}` — same lead story in the same clock-hour is silently skipped. The `Alert.dedup_key` column has a `UNIQUE` constraint as a DB-level guard against `--reload` race conditions.

**`--reload` cross-process lock**: On startup, a 240-second DB-level timestamp lock in `SystemConfig["radar_scan_lock"]` prevents two uvicorn worker processes from scanning simultaneously. First scan fires 3 minutes after startup to let old process die.

**Topic keyword caps**: `_RADAR_MAX_QUERIES=10` queries per topic, `_RADAR_CONCURRENCY=3` parallel Google News requests.

### Alert Content Encoding

`Alert.content` is a newline-separated list of article lines, each with an embedded severity prefix:
```
{critical}[Reuters] 台股崩盤 (關鍵字：台股 OR 大盤)
{high}[Bloomberg] 降息預期升溫
{low}[Yahoo Finance] 市場小幅波動
```

`Alert.source_urls` is a JSON array where each URL has the same prefix: `{high}https://...`

The frontend (`RadarPage`) parses these with `parseSourceUrl()` and `splitArticleLines()` to render per-article severity badges and enable filtering by severity level.

### Severity Assessment

**Source-level floor + credibility**: `MonitorSource.fixed_severity` (VARCHAR, nullable) — acts as a **minimum severity floor** and **source credibility signal**:
- `critical` → always returns critical immediately (no dynamic assessment)
- `high` → floor is high + injects `source_weight_override=1.6` into dynamic assessment, making high keywords able to reach critical (e.g. 2 high keywords: `2.0×1.6×1.1=3.52≥3.5→critical`)
- `low` → floor only, no credibility boost
At scan start, a `_source_fixed_sev: dict[str, str]` map is built from active sources with this field set. The helper `_article_severity(a)` handles the three cases, then applies `max(dynamic, floor)` via `_SEVERITY_ORDER`. This applies everywhere severity is assessed: `_fmt_article_line`, `source_urls` construction, GN critical-only pre-filter, and GAS urgent-rows filter. The source list in SettingsPage shows a coloured badge (最低高風險 / 最低中風險 / 最低低風險) and a dropdown in the expanded view.

`_assess_severity_single()` in `scheduler/jobs.py` uses a **multi-dimensional scoring model**:

1. **Boolean rules** (highest priority) — user-configured `SystemConfig["severity_rules"]` e.g. `"暴跌 AND 台股" → critical`. First match wins.
2. **Multi-dimensional score** (keyword hits only if no rule matches):
   - `base_score`: critical=3.0, high=2.0 (after negation filtering)
   - **Negation filter** (`_has_negation_before`): keywords preceded by 不/沒/未/不會 etc. within 6 chars are excluded — "不會崩盤" does not trigger critical
   - **Source credibility** (`_get_source_weight`): Reuters/Bloomberg ×1.5, official sources (Fed/金管會) ×1.6, general ×1.0. **User-set high floor** → `source_weight_override=1.6` (same as official). **Unknown GN source penalty**: if `source_w == 1.0` AND the article came from Google News (`origin == "gn"`) AND the source name is not in `_known_source_names` (frozenset built from active `MonitorSource` names at scan start) → `source_w = 0.65`, making high/critical harder to trigger for low-authority outlets.
   - **Confirmation factor**: keyword in both title AND body → ×1.3
   - **Multi-keyword bonus**: each additional matched keyword → +0.1, max ×1.3
   - Threshold: ≥3.5→critical, ≥2.0→high, else→low
3. **Time decay** (`_apply_time_decay`): articles older than `SystemConfig["severity_decay_hours"]` (default 6h) are downgraded one level (critical→high, high→low).

Returns `critical`, `high`, or `low` only — `medium` is not used by the scan engine.

The frontend (`NewsDBPage`, `RadarPage`) mirrors keyword lists client-side for display purposes.

### Source Health Monitoring

Existed to solve the "silent failure" problem: WSJ `feeds.a.dj.com` froze in Jan 2025, ctee.com.tw `/feed` returned 000, Politico `economy.xml` stagnated — none reported anywhere outside `journalctl`.

**Tracking** — three columns on `MonitorSource` (added via `_migrate_db()` ALTER):
- `last_attempt_at` — every HTTP attempt (success or failure)
- `last_success_at` — only HTTP 200 (article count irrelevant; an empty feed within the time window is still "alive")
- `last_error` — failure message (truncated to 500 chars), cleared on next success

`backend/services/source_health.py::mark_attempt(url, success, error=None)` is called from every scraper's HTTP try/except. Match key is `MonitorSource.url`; for the one source where the DB URL ≠ scraper URL (MOPS uses legacy `mops/web/t05sr01` as identifier but actually calls `mops/api/home_page/t05sr01_1`), the scraper hardcodes the DB URL alias and only marks success if **either** sii or otc API returned data.

**Threshold** — `SystemConfig["source_health_threshold_hours"]` (default `"48"`, range 1-720). Sources where `last_success_at < now - threshold` OR `last_success_at IS NULL` (active sources never tried yet) count as stale.

**Surfacing** — three places:
1. `GET /api/settings/source-health` — JSON summary (`healthy_count`, `stale_count`, `unknown_count`, full `stale[]` list with `hours_since_success` per source). `GET/PUT /api/settings/source-health-threshold` for the threshold itself.
2. LINE bot `來源` command — `_build_health_reply(db)` returns formatted text listing stale sources with age + error.
3. SettingsPage source list — colour-coded dot before each source name (green if last_success < threshold/2, yellow if half-to-full, red if over or never). `computeSourceHealth(source, threshold)` helper. Threshold input UI in the radar settings panel ("來源健康監控閾值").

**Important caveat**: sources fetched only by `daily_research_fetch` (research papers from Fed/IMF/BIS/etc., once per day at 10am UTC) will show as stale during the ~22h between fetches. This is expected and not a real failure.

### `SystemConfig` — Runtime Config Store

Besides app settings in `.env`, many runtime preferences are stored in `SystemConfig` (key/value table):

| Key | Description |
|-----|-------------|
| `radar_topics` | JSON array of general Google News search terms (TW/Chinese) |
| `radar_topics_us` | JSON array of US/English Google News search terms |
| `radar_hours_back` | Hours back for Google News search (default 24) |
| `radar_interval_minutes` | Radar scan interval in minutes (overrides `.env`, reloaded at startup) |
| `radar_rss_only` | `"true"` to skip Google News and only use RSS sources |
| `severity_critical_keywords` | User-overridable critical keyword list (JSON) |
| `severity_high_keywords` | User-overridable high keyword list (JSON) |
| `severity_rules` | Boolean severity rules (JSON array of `{condition, severity}`) |
| `severity_decay_hours` | Hours after which severity is downgraded one level (default 6) |
| `radar_scan_lock` | ISO timestamp — cross-process dedup guard |
| `line_last_reply_at` | ISO timestamp — last time LINE news query was answered (unread baseline) |
| `line_last_yt_reply_at` | ISO timestamp — last time LINE YouTube query was answered (unread baseline) |
| `line_last_digest_at` | ISO timestamp — last time `line_critical_digest` 排程作業跑完（07/12/17 台北彙整推送），讀此值決定該推哪些新 critical Alert |
| `radar_rss_min_articles` | If RSS collects ≥ N articles, skip Google News (default `"0"` = disabled) |
| `finance_filter_enabled` | `"true"` to drop articles below relevance threshold (default `"false"`) |
| `finance_relevance_threshold` | Min finance relevance score to keep article (default `"0.15"`) |
| `gn_critical_only` | `"true"` to pre-filter Google News results to critical severity only; RSS articles unaffected (default `"false"`) |
| `radar_exclusion_keywords` | JSON array of terms — any article containing one is dropped from all sources after collection |
| `radar_topic_categories` | JSON array of `{name, lang, keywords}` — named keyword categories for SettingsPage UI; flattened to `radar_topics`/`radar_topics_us` on save |
| `nlm_latest_report` | Full Markdown text of the latest NotebookLM news analysis report (written by `notebooklm_hourly.py` via `POST /api/radar/notebooklm-report`) |
| `nlm_report_generated_at` | ISO timestamp of when the NLM news report was generated |
| `nlm_report_source_title` | Source title string used when the news report was created in NotebookLM |
| `nlm_yt_latest_report` | Full Markdown text of the latest NotebookLM YouTube analysis report |
| `nlm_yt_report_generated_at` | ISO timestamp of when the YT report was generated |
| `nlm_yt_report_source_title` | Source title string used when the YT report was created |
| `extension_latest_report` | Latest Chrome Extension manual analysis report (Markdown). Written by `POST /api/radar/extension-report` from the extension's `background.js` |
| `extension_report_generated_at` | ISO timestamp of when the extension report was generated |
| `extension_report_source_title` | Source titles batch label, prefixed with `[news]` or `[yt]` for the kind |
| `extension_report_kind` | `"news"` 或 `"yt"`, indicating which notebook the manual report came from |
| `source_health_threshold_hours` | Source health monitoring threshold in hours (default `"48"`, range 1-720). Sources whose `last_success_at` is older than this are flagged as stale. |

### LINE Webhook Command System (`routers/line_webhook.py`)

Bot only responds to specific commands — all other messages are silently ignored:

| Input pattern | Response |
|---------------|----------|
| `ID`（大小寫不拘）| 回覆當前 event source 的類型與 ID（`groupId` / `roomId` / `userId`），方便取得群組 ID 設定 `LINE_TARGET_ID` |
| `分析` / any text containing `分析` | Latest **Extension** news analysis report（`NlmReport` 表最新 `extension_manual` + `[news]` 前綴，via `_get_latest_extension_report(db, "news")`） |
| `通知` | Unread critical news alerts since last query (updates `line_last_reply_at`) |
| `通知1天` / `通知今日` / `通知3小時` | Critical news from that time range |
| `yt` / `YT` / `yt通知` | Unread YouTube videos since last query (updates `line_last_yt_reply_at`) |
| `yt分析` | Latest **Extension** YouTube analysis report（`NlmReport` 表最新 `extension_manual` + `[yt]` 前綴） |
| `yt1天` / `yt今日` / `yt3小時` | YouTube videos from that time range |
| `來源` / `健檢` (text containing `來源`) | 來源健康狀態：超過閾值未成功的來源清單（`_build_health_reply`） |
| anything else | no reply |

Detection priority: `is_id = user_text.strip().upper() == "ID"` → `is_yt = not is_id and user_text[:2].lower() == "yt"` → `is_analysis = not is_id and not is_yt and "分析" in user_text` → `is_health = not is_id and not is_yt and not is_analysis and "來源" in user_text` → `is_news = not is_id and not is_yt and not is_analysis and not is_health and "通知" in user_text`. Inside the `is_yt` branch, `yt分析` (i.e. `"分析" in remainder`) takes priority over the video list. The `分析` command takes priority over `通知` so "分析通知" triggers news analysis, not news. Markdown from the NLM report is stripped by `_md_to_plain()` before sending. Report is split into ≤5 LINE messages of ≤4800 chars each. Article titles in news notifications are capped at 80 characters (truncated to 78 + `…`) in `_parse_articles()` — prevents social media posts (e.g. Trump tweets from Nitter) from flooding the notification with full post text.

**Scheduled active push** (`line_critical_digest` in `scheduler/jobs.py`)：每天 UTC 23:00 / 04:00 / 09:00（= 台北 07:00 / 12:00 / 17:00）執行一次，撈出 `SystemConfig.line_last_digest_at` 以來的所有 critical `Alert`，透過 `send_line_broadcast` 推送到 `LINE_TARGET_ID`（設為群組 ID 時走 pushMessage 只送該群組，不會 broadcast 全部好友）。即使無新警報也會更新 `line_last_digest_at` 時間戳，避免下輪重複推送舊資料。沿用 webhook 端的 `_build_news_reply` 格式（最多 5 則訊息，每則 30 則文章）。

### Database (SQLite)

Seventeen models in `backend/database.py`: `Article`, `Alert`, `MarketWatchItem`, `SignalCondition`, `MonitorSource`, `NotificationSetting`, `Topic`, `TopicArticle`, `ResearchReport`, `SystemConfig`, `YoutubeChannel`, `YoutubeVideo`, `Feedback`, `NlmReport`, `RawArticle`, `User`, `ServiceApiKey`. The DB file lives at `data/financial_radar.db`. To re-seed defaults, delete the DB file and restart.

**`User`**: `username` (unique)、`password_hash` (bcrypt 12-round)、`role` (`regular` / `admin` / `owner`)、`is_active`、`must_change_password`、`last_login_at`。

**`ServiceApiKey`**: `name`（顯示用）、`key_prefix`（前 8 字元 `sk_xxxxxx`，方便辨識，**不機密**）、`key_hash`（bcrypt over full key）、`role`、`created_by_user_id`、`last_used_at`、`is_revoked`。**完整 key 不存 DB**，建立時只回傳一次給 owner。

`YoutubeVideo.is_new` — `True` until user marks as seen. Used by LINE webhook for unread YT queries.

`MonitorSource.type` field values: `rss`, `website`, `social`, `newsapi`, `research`, `person`, `mops`. Research sources use `type="research"` and are fetched separately from news RSS sources. `mops` sources are fetched via `services/mops_scraper.py`. `website` sources are routed by `_fetch_website_source()` to specialized scrapers (fed, cnyes, worldbank, fsc, caixin, storm, taisounds, linetoday, udn) or a generic web_scraper fallback.

**Two-tier freshness architecture**: Direct RSS/scraper sources provide <1h freshness (Reuters, Bloomberg, Fed, 鉅亨網, 聯合新聞網, 工商時報 livenews, NowNews sitemap, WSJ Markets, Politico Morning Money, etc.). Google News `site:` search sources are now reserved for outlets that fully block direct scraping (IMF — Akamai-blocked) or whose direct feeds are stale/broken (財訊 — wealth.com.tw RSS serves 30 entries with the same stale 4-month-old `pubDate`). Multi-publisher keyword GN searches (e.g. PBOC monetary policy across all outlets) are also kept as GN. All GN `site:` searches use `when:3d` (not `when:7d`) for tighter time windows.

**Scraping limitations**: IMF (`imf.org`) is fully blocked by Akamai Bot Manager (all endpoints return 403) — uses Google News `site:imf.org when:3d` RSS as proxy. 風傳媒 (`storm.mg`) — CloudFront/WAF blocks GCP IP ranges (all paths return 403 from VM, 200 from local), forced back to GN proxy `site:storm.mg when:3d`. 商周 (`businessweekly.com.tw`) — `cmsapi.businessweekly.com.tw` RSS feed 內容只覆蓋 `/focus/`、`/style/` 子站（漏掉 `/business/` 與雜誌主刊），改用 `businessweekly_scraper.py` 抓 `/latest/SearchList` AJAX 端點（每頁 20 篇）。 財訊 (`wealth.com.tw`) — `/rss` returns a feed but every entry shares the same 4-month-old `pubDate` (CMS export bug); kept on GN proxy `site:wealth.com.tw when:3d`. Politico's `economy.xml` feed has stagnated (single stale entry) — radar now uses `morningmoney.xml` (daily 8am ET financial-policy newsletter, ~30 entries) instead. WSJ's `feeds.a.dj.com` froze in Jan 2025 — radar now uses `feeds.content.dowjones.io/public/rss/RSSMarketsMain` (>60 fresh entries). UDN financial RSS (`udn.com/rssfeed`) returns valid XML but empty entries — use the category page HTML scraper (`udn.com/news/cate/2/6644` via `udn_scraper.py`) instead. `money.udn.com/rssfeed` works for the finance sub-site.

`MonitorSource.fetch_all` — boolean (default `False`). When `True`, skips keyword filtering so all articles from the source enter the radar; keyword badges are still annotated but only when the full boolean condition matches. Applies to **all source types** including `mops`. Added via `_migrate_db()` `ALTER TABLE`.

`MonitorSource.is_deleted` — boolean (default `False`). Soft delete: when user deletes a source, `is_deleted=True` and `is_active=False` are set instead of row deletion. The URL persists in DB so `_seed_defaults()` / `_migrate_db()` INSERT checks find it and skip re-adding. All MonitorSource queries in `jobs.py`, `settings.py` filter `is_deleted == False`.

`MonitorSource.sort_order` — integer (default `0`). User-controlled display order in SettingsPage; lower = earlier. Initialized from `id` order on first migration. Updated via `PUT /api/settings/sources/reorder` (list of IDs in desired order).

`MonitorSource.fixed_severity` — `VARCHAR`, nullable (default `None`). Dual role as severity floor and source credibility signal: `"critical"` → always critical (skip dynamic); `"high"` → floor high + `source_weight_override=1.6` enabling high keywords to reach critical; `"low"` → floor only. Final severity = `max(floor, dynamic)`. Set via dropdown in SettingsPage expanded source view.

`MonitorSource.last_attempt_at` / `last_success_at` / `last_error` — health tracking columns (DATETIME, DATETIME, VARCHAR(500), all nullable). Written by `services/source_health.py::mark_attempt()` from inside each scraper's HTTP try/except. See "Source Health Monitoring" section above.

`TopicArticle.add_source`: `"radar"` (added by scheduler) or `"manual"` (added by user search).

`Article` has six extra columns added via `_migrate_db()`: `composite_score`, `finance_relevance`, `novelty_score`, `decay_factor`, `intensity_score` (all `REAL`, nullable, computed by `_compute_article_scores()` in `jobs.py` at save time) + `matched_keyword VARCHAR` (nullable, set from preview data when user saves selected articles via `POST /api/news/save-selected`).

### Frontend Structure

- **Pages:** `RadarPage`, `SearchPage`, `NewsDBPage`, `ReportsPage`, `DashboardPage`, `YouTubePage`, `AnalysisPage`, `FeedbackPage`, `SettingsPage`
- **Responsive layout**: `RadarPage` has separate mobile (`sm:hidden`) and desktop (`hidden sm:flex`) card layouts. Mobile: date+delete on top row, title below full-width, keyword tags limited to 2. Desktop: original horizontal flex (title+article lines in `flex-1`, date+delete on right as `shrink-0`). Global layout: sidebar `hidden md:flex`, mobile bottom tab bar `md:hidden` with "更多" panel for secondary pages.
- **API client:** `frontend/src/services/api.js` — Axios instance with 60s timeout, exports `radarAPI`, `searchAPI`, `newsAPI`, `settingsAPI`, `topicsAPI`, `reportsAPI`, `rawArticlesAPI`, `youtubeAPI`, plus `resolveUrl()` utility. `radarAPI` includes NLM (`getNlmReport / getNlmYtReport / listNlmReports / getNlmReportById`), Gemini (`getGeminiReport / getGeminiYtReport / listGeminiReports / getGeminiReportById / triggerGeminiAnalysis`), and **Extension** (`getExtensionReport / listExtensionReports / getExtensionReportById`) endpoints. **`resolveUrl()` 重要行為**：只在 URL 含 `news.google.com` 才打 backend `/api/utils/resolve-url`（HTTP redirect 解析），其他網域直接 pass-through 不出網路。理由：雷達掃描階段 `_resolve_gn_article_urls()` 已用 batchexecute 把 GN URL 解碼成最終網址再寫進 DB，DB 內 99% 都是原始連結；以前每個複製動作對 N 個 URL 都打 backend、每個最多 10s 等待，56 個並行就拖很久。`copyToClipboard(text)` utility: uses `navigator.clipboard.writeText()` in HTTPS/localhost, falls back to `document.execCommand('copy')` for HTTP (VM).
- **Real-time:** `useWebSocket` hook subscribes to backend WebSocket for live alerts. Default URL is **dynamic** — `${ws|wss}://${window.location.host}/ws`，避免寫死 `ws://localhost:8000/ws` 害部署到 VM IP 的使用者瀏覽器去連自己的 127.0.0.1 而全員顯示「離線中」。生產 nginx 與 dev vite.config 都有 `/ws` proxy。
- **Styling:** Tailwind CSS dark theme, custom classes `card`, `card-hover`, `btn-primary`, `btn-secondary`, `btn-danger`, `input` defined in `index.css`.
- **Severity display** (`NewsDBPage`): `assessSeverity(title, content)` runs client-side with the same keyword lists as the backend. `SeverityBadge` renders text pills (緊急/高/低). Not a server field — computed on render.
- **SettingsPage source list**: drag handle (`⠿`) for drag-to-sort (calls `PUT /sources/reorder`); hover name to reveal inline rename input (Enter/blur saves, Escape cancels). All source types including MOPS have a `fetch_all` toggle and a `fixed_severity` dropdown (動態評估 / 高風險 / 中風險 / 低風險). Keyword category manager uses `CAT_COLORS` (8 colours) — clicking a keyword pill opens a popover to assign it to a named category. Source expanded view includes a type dropdown (RSS / 網頁爬蟲 / 社群) for non-mops/research sources.
- **SettingsPage radar keywords**: Category-based structure — keywords are organized into named categories (`[{name, lang: "tw"|"en", keywords: [...]}]`), stored in `SystemConfig["radar_topic_categories"]` via `GET/PUT /api/settings/radar-topic-categories`. On save, TW categories flatten to `radar_topics`, EN categories to `radar_topics_us`. Each category renders as a coloured card (`CAT_COLORS`, 8 colours) with TW/EN badge; simple keywords as pills, boolean combos via `GroupedKeywordCard`. Backward-compatible: old flat lists auto-migrate to a single "未分類" category on load. `stripNotTerms(kw)` extracts `NOT term` / `NOT "multi word"` clauses from boolean keyword strings; `serializeGroups(groups, notTerms)` appends them at the end. Boolean keyword cards show NOT terms as red chips; the edit panel has a dedicated "排除詞（NOT）" input section. Global exclusion keywords are managed in a red-bordered section below the categories — saved alongside topics via `updateRadarTopics(..., exclusion_keywords)`. `parseGroupedKeyword(kw)` calls `stripNotTerms` before regex parsing so NOT clauses don't break group detection.
- **AnalysisPage** (`/analysis`): **檔案總管式導覽**（非分頁）。`ENGINES`（extension / gemini / nlm）× `KINDS`（news / yt）下鑽至報告；state 為 `path`（`[]` / `[engine]` / `[engine, kind]`）+ `viewing`（`{leafKey, id}`）。`TAB_CONFIG` 以 `{engine}_{kind}` 為 key，共 **6 個 leaf**（`extension_news` / `extension_yt` / `gemini_news` / `gemini_yt` / `nlm_news` / `nlm_yt`），每個 leaf 形狀為 `{emptyMsg, emptyHint, getById, group}`；`group` 是 `'nlm'`（primary 紫紅）/ `'gemini'`（blue）/ `'extension'`（violet），驅動全部配色。`histories` state 一次載入全部 6 個 leaf 的歷史清單供下鑽選日期。 `renderReport()` renders Markdown headings, dividers, bold text; `renderInline()` handles `**bold**` and URLs in the same line; `linkify()` converts bare URLs to `<a>` links. Shows `generated_at` timestamp and `source_title` metadata. Empty state shown when no report exists. All `generated_at` timestamps are tagged with `Z` by `_iso_utc()` in `radar.py` so JavaScript interprets them as UTC, not local time.
- **Routing constraint**: `PUT /api/settings/sources/reorder` must be declared **before** `PUT /api/settings/sources/{source_id}` in `settings.py` or FastAPI will match `"reorder"` as a source ID.

## Configuration

Copy `.env.example` to `.env`. Key variables:
- `GEMINI_API_KEY` — Recommended (free tier), default AI engine
- `GEMINI_MODEL` — Default `gemini-2.5-flash`
- `DEFAULT_AI_MODEL=gemini` — Switch to `claude` to use Anthropic instead
- `ANTHROPIC_API_KEY` — Required only if using Claude as AI engine
- `NEWS_API_KEY` — For NewsAPI headline fetching
- `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_CHANNEL_SECRET` — LINE Bot webhook (passive reply, free). `LINE_TARGET_ID` left empty disables active push while keeping passive reply active.
- `LINE_NOTIFY_TOKEN` — Legacy LINE Notify (deprecated, use Messaging API instead)
- `GOOGLE_APPS_SCRIPT_URL` — Preferred method for Google Sheets write (GAS Web App). **VM-only**；local `.env` 留空，避免 local dev 把資料推到 Sheets
- `GOOGLE_SHEETS_CREDENTIALS_FILE` + `GOOGLE_SHEETS_SPREADSHEET_ID` — Legacy method (Service Account JSON)
- `GOOGLE_SHEETS_POSITION_SHEET` / `GOOGLE_SHEETS_NEWS_SHEET` — 工作表名稱（預設 `positions` / `news_archive`）
- `RADAR_INTERVAL_MINUTES` — 雷達掃描間隔（預設 5；同時存於 `SystemConfig["radar_interval_minutes"]`，重啟時從 DB 讀取覆蓋 env）
- `MARKET_CHECK_INTERVAL_MINUTES` — 市場監控間隔（預設 60）
- `NEWS_SCHEDULE_HOUR` / `NEWS_SCHEDULE_MINUTE` — 每日新聞排程執行時間（VM 為 UTC，預設 2:00 UTC = 台北 10:00）
- `JWT_SECRET` — JWT 簽章密鑰（必填，啟動 owner 帳號功能必備）。產生：`python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `JWT_EXPIRE_HOURS` — JWT 有效期（預設 24）
- `OWNER_USERNAME` / `OWNER_PASSWORD` — 首次啟動 bootstrap owner 帳號用；建好後可清空
- `API_TOKEN` — Legacy 過渡期單一 token（向後相容，視為 admin），建議遷移到 Service Keys 後移除
- `ENVIRONMENT` — `production` 時不掛 CORS middleware（dev 自動掛 `localhost:5173/3000`）

## API Route Prefixes

| Prefix | Router | Purpose |
|--------|--------|---------|
| `/api/radar` | `routers/radar.py` | Alerts CRUD, market data, watchlist, signal conditions. NLM: `POST/GET /notebooklm-report`, `POST/GET /notebooklm-yt-report`. Gemini: `GET /gemini-report`, `GET /gemini-yt-report`, `GET /gemini-reports?report_type=`, `GET /gemini-reports/{id}`, `POST /gemini-analyze` (manual trigger). **Extension** (Chrome ext 手動推入): `POST/GET /extension-report?kind=news\|yt`, `GET /extension-reports?kind=news\|yt`, `GET /extension-reports/{id}` — `kind` 篩選依 `source_title` 前綴 `[news]` / `[yt]`（推送時 `notebook_kind` 帶入，舊資料無前綴歸 news）。Completely isolated from hourly: writes `NlmReport(report_type="extension_manual")` + `SystemConfig["extension_*"]` keys, never touches `nlm_latest_report` / `nlm_yt_latest_report`, so LINE「分析」指令一直拿到 hourly 的最新版. **`DELETE /reports/{id}`** — 通用刪除（NLM / Gemini / Extension 任一份 `NlmReport`），刪掉的若是該 type 目前最新的，會把對應的 `SystemConfig.*_latest_report` 系列重新指向同 type 下一筆最新；沒有下一筆就清空。All reports stored in `NlmReport` table + `SystemConfig`. |
| `/api/search` | `routers/search.py` | Topic search, AI analysis, positions |
| `/api/news` | `routers/news_db.py` | Article CRUD, fetch preview, save-selected, sentiment. **Router 不掛 dep**，個別 endpoint 自帶 auth：GET 全開（guest 可讀）、`PUT /articles/{id}` / `POST /save-selected` / `DELETE` 為 admin。`POST /fetch` 支援 `source_type`: `"sources_only"`（RSS + social + website + MOPS — admin only，會觸發大量爬蟲）或 `"gn_only"`（Google News — guest 也可用，函式內依 `source_type` 動態判斷而非 router-level dep）。When no query, uses radar_topics + active Topic keywords. **Search 容錯邏輯**：`_normalize_query_text()` 對 query 與被比對文字做 NFKC（全形→半形）+ 移除空白 + lower，讓「美股收紅！」與「美股收紅!」視為相同；`_split_query_terms()` 切 ASCII↔CJK 邊界後對 ≥6 字 CJK 段補 4-gram、≥12 字補 6-gram，讓貼整段標題能由部分文字命中。OR 比對：任一 term 為 substring 即過。Boolean topics dispatched via `_gn_fetch_topic()` → `_multi_search_topic`. `GET /sources` returns configured source names + `__other__` with counts; `GET /keywords` returns unique `matched_keyword` values with counts. `GET /articles` accepts `source` and `keyword` query params for filtering. `fetched_after` query param 帶 tz 時 endpoint 內會先轉成 naive UTC 再比對（否則 SQLite 字串比較會把跨日邊界的文章誤排除）。|
| `/api/topics` | `routers/topics.py` | Topic CRUD, per-topic articles, Google News search+import |
| `/api/research` | `routers/research.py` | Research institutions, reports CRUD, fetch preview, save-selected |
| `/api/youtube` | `routers/youtube.py` | YouTube channel CRUD, video fetch, mark-as-seen. **Router 不掛 dep**：GET（channels / videos / new-count）全開、`PUT /videos/{id}/seen` 與 `/mark-all-seen` 為 regular（登入即可），`POST /channels` / `PUT/DELETE /channels/{id}` / `POST /channels/{id}/check` / `/check-all` 為 admin |
| `/api/line/webhook` | `routers/line_webhook.py` | LINE Bot webhook receiver (POST only, signature-verified) |
| `/api/settings` | `routers/settings.py` | Monitor sources (including `fetch_all`, `sort_order`, `last_success_at`/`last_attempt_at`/`last_error` fields), notifications, Google Sheets, AI model config, finance filter toggle+threshold, RSS priority threshold, GN critical-only toggle, radar exclusion keywords. `PUT /sources/reorder` — bulk sort_order update (list of IDs, must be registered **before** `PUT /sources/{id}` to avoid FastAPI routing conflict). `POST /sources/{id}/test-rss` supports all types: `mops`, `website` (dispatches to fed/cnyes/worldbank/fsc/caixin/storm/taisounds/linetoday/udn/ctee/nownews/treasury scrapers via same `is_*_url()` routing), and `rss`/`social`. The stale-warning logic uses the **latest** entry across `entries[:20]` (not `entries[:3]` as before — that bug caused false alarms on daily-newsletter feeds like Politico Morning Money). `GET /radar-topics` response includes `exclusion_keywords` field; `PUT /radar-topics` accepts it. **Source health**: `GET /source-health` returns `{threshold_hours, healthy_count, stale_count, unknown_count, stale[]}`; `GET/PUT /source-health-threshold` for the threshold (1-720 hours). |
| `/api/feedback` | `routers/feedback.py` | User feedback CRUD (GET list, POST create, DELETE by id) |
| `/api/raw-articles` | `routers/raw_articles.py` | 篩選前資料：`GET /articles`（list/search/filter，沿用 news_db 的 normalize+n-gram 容錯）、`GET /stats`（總筆數 / passed / not_passed / by_source_type / by_source）、`GET /sources`、`DELETE /articles/{id}`、`POST /cleanup?days=N`（手動清理 N 天前資料）。 |
| `/api/auth` | `routers/auth_router.py` | `POST /login`、`GET /me`（永遠 200，guest 為合法狀態）、`POST /change-password` |
| `/api/users` | `routers/users.py` | **owner only**。GET 列表 / POST 建 / PUT 改 role+is_active / POST `{id}/reset-password`（產一組臨時密碼回傳一次）/ DELETE。防呆：不能刪自己、不能刪/降權最後一個 owner |
| `/api/service-keys` | `routers/service_keys.py` | **owner only**。建立 service key 時 `full_key` 只回傳一次（DB 只存 bcrypt hash）。撤銷 = `is_revoked=True`，下個請求即 401 |
| `/api/utils/resolve-url` | `main.py` | Follow redirects, return final article URL. SSRF 防禦：`is_safe_public_url()` 阻擋 RFC1918 / loopback / link-local（含 GCP metadata 169.254.169.254）|
| `/api/utils/resolve-stored-urls` | `main.py` | One-time background job: resolve all Google News redirect URLs in DB. SystemConfig `resolve_stored_urls_lock` 60 秒重入鎖 |
| `/ws` | `main.py` | WebSocket for real-time broadcasts |

## NotebookLM Local Automation (`scripts/notebooklm_hourly.py`)

Runs on the **local Windows machine** via Task Scheduler (not on the VM). Requires `pip install notebooklm-py requests beautifulsoup4` and `notebooklm login` (browser-based auth, saves to `~/.notebooklm/storage_state.json`; re-run when auth expires).

**Deployed copy ≠ repo copy**: Task Scheduler runs a **separate deployed copy at `C:\nlm_scripts\`** (mirrors repo `scripts/`, has its own `.env.local` / `.nlm_state.json`), NOT the repo `scripts/`. Two tasks: **「NotebookLM 金融分析」** (runs `python -X utf8 C:\nlm_scripts\notebooklm_hourly.py`, every ~3h — supports `--news-only` / `--yt-only` to split) and **「NLM Cookie KeepAlive」** (`--cookie-refresh`, every 45 min). Inspect via PowerShell `Get-ScheduledTask` / `Get-ScheduledTaskInfo`; last-run result `0xC000013A` = killed, check `C:\nlm_scripts\nlm_reports\run.log`.

**Operational reality — headless auth keeps fully expiring**: despite the keepalive task, Google periodically invalidates the headless session entirely (`run.log`: 「認證已完全過期…請手動執行 notebooklm login」), silently stopping all NLM hourly analysis (news + YT) until a human re-runs `notebooklm login` (interactive Google sign-in — cannot be automated). This is why the **Chrome Extension v0.7 定時自動分析** (in-browser, live session, no login) and **VM-side Gemini analysis** (no browser at all) exist as more robust alternatives. The three YT-analysis paths (NLM hourly → 📺 NLM YouTube, VM Gemini → 📺 Gemini YouTube, Extension auto → 🧩 Extension YT) coexist independently.

The script handles **two separate notebooks**: news analysis (`NOTEBOOK_ID`) and YouTube analysis (`NOTEBOOK_ID_YT`). Each is an independent flow run sequentially in the same script invocation.

**Skill sources** (`scripts/skills/`): Permanent `.md` files (analysis team framework) loaded into each notebook once and never deleted. Identified by `[SKILL] ` title prefix. `_ensure_skill_sources(client, notebook_id)` lists existing sources, adds any missing `[SKILL]*` files; `_cleanup_news_sources(client, notebook_id)` deletes all non-`[SKILL]` sources before each run (removes stale news while keeping framework intact).

**State tracking**: `.nlm_state.json` stores `news_last_run` and `yt_last_run` (separate ISO timestamps). On each run, if the gap since last run exceeds `HOURS_BACK`, the script fetches from that timestamp (catchup mode). Manual runs with `--hours`/`--since` flags do NOT update state; all other runs do.

**News analysis flow**:
1. Step 0: `_ensure_skill_sources()` then `_cleanup_news_sources()` to reset news sources
2. Fetch articles from `GET /api/news/articles?limit=500&fetched_after=<cutoff>` → client-side severity filter
3. `_add_source_with_fallback(client, notebook_id, url, title, requests)` for each article: tries `add_url(wait=False)` first; on failure, fetches page HTML and `add_text()` as fallback
4. `add_text(NOTEBOOK_ID, summary_md, wait=True)` — full article list with metadata
5. `generate_report(ReportFormat.CUSTOM, language="zh-TW", custom_prompt=_build_news_prompt(len(articles)))`
6. `wait_for_completion(NOTEBOOK_ID, task_id, timeout=300)`
7. `download_report(...)` → saves to `scripts/nlm_reports/YYYYMMDD_HHMM.md`
8. `POST /api/radar/notebooklm-report` → pushes to VM

**`_build_news_prompt(article_count)`** selects one of two prompt versions based on article count. Both versions use the full analysis team framework (references `[SKILL] PROJECT_INSTRUCTIONS_v2` and `[SKILL] SKILL_*`). Output format is identical for both:
- `< 10` articles → max **1 category**; `≥ 10` articles → max **2 categories**
- Fixed 3-point structure per category: `1. **事件描述**` / `2. **市場與國別影響**` / `3. **後續分析**`
- Footer: `### 關鍵來源` with `- 一-1. 標題（URL）` per point

**YouTube analysis flow**:
1. Step 0: `_ensure_skill_sources()` then `_cleanup_news_sources()` on `NOTEBOOK_ID_YT`
2. `_is_youtube_short(video_id, requests)` — HEAD `/shorts/{id}`, 200 → Short (add with 1 analysis point only)
3. Fetch and add video URLs via `_add_source_with_fallback`; max 15 videos
4. `generate_report(...)` with `custom_prompt`: per-video `一、【頻道名稱】影片標題`; Shorts get 1 point, regular videos get 3; same team framework reference
5. Download and push to `POST /api/radar/notebooklm-yt-report`

**CLI flags**: `--hours N`, `--since "MM/DD HH:MM"` (Taiwan time), `--severity critical|high`, `--news-only`, `--yt-only`, `--no-save-state`. Manual `--hours`/`--since` use `published_at` filter for YT (not `is_new` flag).

Config in `scripts/.env.local` (copy from `scripts/.env.local.example`): `API_BASE_URL=http://35.231.159.224` (VM IP, no port — nginx proxy), `NOTEBOOK_ID`, `NOTEBOOK_ID_YT`, `HOURS_BACK=3` (matches 3-hour Task Scheduler interval), `MIN_SEVERITY=low`, `RESULT_PUSH_LINE`.

**notebooklm-py 0.3.4 API**: `async with await NotebookLMClient.from_storage() as client:` — note the double `await`. Sub-clients:
- `client.sources` — `add_text`, `add_url(wait=False for async)`, `add_file`, `list(notebook_id)`, `delete(notebook_id, source_id)`
- `client.artifacts` — `generate_report(report_format, language, custom_prompt)`, `wait_for_completion(notebook_id, task_id, timeout)`, `download_report(notebook_id, output_path, artifact_id)`. `ReportFormat` values: `BRIEFING_DOC`, `STUDY_GUIDE`, `BLOG_POST`, `CUSTOM`.
- `client.chat` — `ask` → `AskResult.answer` (use for Q&A, not for structured reports)
- `client.notebooks` — `list`, `create`, `get`

**Cookie refresh** (`_refresh_cookies_playwright()`): Before each run, opens `notebooklm.google.com` via Playwright **headed** (not headless — Google blocks headless Chromium with redirect to login page). Loads existing `storage_state.json`, waits 3s for short-lived `__Secure-*PSIDRTS` cookies to refresh, saves back. Runs in a separate thread with `ProactorEventLoop` (Playwright requirement on Windows) to avoid conflict with the main `SelectorEventLoop`. If refresh fails, script still attempts `NotebookLMClient.from_storage()` — may work if cookies haven't fully expired yet.

**Safe print wrapper**: Global `print()` is overridden to catch `OSError: [Errno 22]` — Windows Task Scheduler runs without a console, causing stdout writes to fail. The wrapper silently drops output on pipe errors; all important messages also go through `_log` (FileHandler to `nlm_reports/run.log`).

**`--cookie-refresh` mode**: Lightweight flag that only runs `_refresh_cookies_playwright()` then exits. Used by a separate Task Scheduler task "NLM Cookie KeepAlive" every 45 minutes to keep `__Secure-*PSIDRTS` cookies alive between 3-hour analysis runs (PSIDRTS cookies expire in seconds; 3-hour gaps consistently cause auth failure).

## Gemini Auto-Analysis (`backend/services/gemini_analysis.py`)

Runs on the **VM** via APScheduler (every 3 hours, first run 5 min after startup). Uses Gemini API directly — no local machine dependency.

**Two analysis jobs** in one scheduler entry (`gemini_analysis` in `jobs.py`):
1. `run_gemini_news_analysis(hours_back=3)` — queries `Article` table for recent articles, filters by severity, builds prompt with analyst roundtable framework, saves to `NlmReport(report_type="gemini_news")` + `SystemConfig["gemini_latest_report"]`
2. `run_gemini_yt_analysis(hours_back=3)` — queries `YoutubeVideo` table, same flow, saves as `report_type="gemini_yt"` + `SystemConfig["gemini_yt_latest_report"]`

**Cooldown guard** (in `scheduler/jobs.py`): Before running, reads `gemini_report_generated_at` from `SystemConfig`; skips if < 2.5 hours elapsed — prevents repeated triggers on `--reload` service restarts.

**Retry mechanism** (`_call_gemini_with_retry`): 503 (model overload) and 429 (quota exhausted) trigger automatic retry with backoff delays of 30s → 60s → 120s, up to 3 retries. `gemini-2.5-flash` free tier has a 20 requests/day limit.

**Auto-shrink**: If article count exceeds 120, automatically filters to `high`+ severity only to stay within token limits.

**`_iso_utc()` in `radar.py`**: All NlmReport datetime fields are serialized via `_iso_utc(dt)` which appends `Z` if absent — ensures JavaScript interprets the timestamp as UTC, not local time (SQLite stores naive UTC datetimes that `isoformat()` would return without timezone marker).

**`youtube_feed.py` UTC fix**: `_parse_published()` uses `calendar.timegm()` (not `time.mktime()`) to convert `published_parsed` struct from feedparser — feedparser returns UTC structs, `mktime()` would treat them as local time causing an 8-hour offset. `_video_dict()` in `youtube.py` also appends `Z` to `isoformat()` output for the same reason.

## Chrome Extension (`extension/`) — 手動 NotebookLM 分析

MV3 Chrome 擴充功能，仿照「NotebookLM 網頁匯入器」UIUX（淺色介面、動態 notebook 下拉、黑白 SVG 圖示系統），給使用者**手動**對 NotebookLM 做七件事（v0.5.0+）：(1) **新增目前頁面至筆記本**（primary 黑底大鈕；`chrome.tabs.query` 抓 active tab URL → 走單 URL `import_urls`）、(2) 匯入剪貼簿 URL、(3) 清空 sources（保留 `[SKILL] ` 前綴的框架檔）、(4) 產生分析報告 → 推送 VM、(5) 一鍵把 (3)(2)(4) 串起來、(6) **開啟所選 notebook**（`chrome.tabs.create` 開 `https://notebooklm.google.com/notebook/<id>`）、(7) **+ 建立新筆記本**（v0.5 用真正的 NLM `CREATE_NOTEBOOK` RPC，建好自動 refresh 下拉並選中）。**與 hourly 自動排程完全獨立**：不寫入 `nlm_latest_report` / `nlm_yt_latest_report` / `gemini_*` 任何 SystemConfig，LINE「分析」指令永遠拿到 hourly 的最新版。

**`chrome.storage.local` 使用的 key 清單**（popup/background 雙方約定，勿擅自改名）：
- `lastNotebookId`：上次選的 notebook ID，popup 開啟自動選回
- `cachedNotebooks_v2`：notebook 清單快取 `[{id, title}]`，渲染時先用快取、背景 refresh
- `lastKind`：上次選的 kind (`news`/`yt`/`none`)
- `savedPrompts`：使用者儲存的提示詞收藏 `[{id, name, content}]`
- `selectedPromptId`：目前選用的提示詞 ID（`null` = 用 options 預設）
- `vmBaseUrl`、`apiToken`、`newsPrompt`、`ytPrompt`、`nonePrompt`、`skipVmPush`：在 options.html 設定
- **v0.7 定時自動分析（新聞 + YT）**設定（options.html）：`autoIntervalHours`（共用間隔，向後相容舊 `autoYtIntervalHours`）；新聞 `autoNewsEnabled`/`autoNewsNotebookId`/`autoNewsNotebookTitle`、YT `autoYtEnabled`/`autoYtNotebookId`/`autoYtNotebookTitle`
- 自動分析執行狀態 / 去重：新聞 `autoNewsAnalyzedKeys`（去重 key = source_url）/`autoNewsLastRun`/`autoNewsLastResult`、YT `autoYtAnalyzedIds`（去重 key = video_id）/`autoYtLastRun`/`autoYtLastResult`（皆保留最近 500 筆）

**v0.4 → v0.5 重大變更**：
- **動態 notebook 下拉**取代固定「新聞 / YT radio」：popup 開啟時呼 `list_notebooks` 透過 NLM `LIST_NOTEBOOKS` RPC（`wXbhsf`）拉所有 notebooks，記憶 `lastNotebookId` 在 `chrome.storage.local`，下次開啟自動選回。先用 `cachedNotebooks` 渲染、背景 refresh 拉新清單，避免每次開 popup 空白等 1-2 秒
- **建立新筆記本走真正 RPC**：`CREATE_NOTEBOOK` (`CCqFvf`) — params 結構 `[title, null, null, [2], [1]]`，回 `[id, [..., title at idx 4, ...]]`。建好回傳 `{id, title}` 進 popup 端 `chrome.storage.local.lastNotebookId` 然後 `loadNotebooks({forceRefresh:true})` 自動選中
- **報告類型獨立**：notebook 跟 kind 解耦 — popup 上方下拉選 notebook（操作目標），下方一排小 chip 選 `📰 新聞 / 📺 YT / 🚫 不推送`（互斥）。推 VM 時帶 `notebook_kind`，影響 VM 端 `extension-report?kind=` 分流
- **「🚫 不推送」用獨立提示詞**（v0.6.2）：以前選「🚫 不推送」會 fallback 用新聞 prompt（pickPrompt 寫成「kind==='yt' 用 yt prompt，其他用 news」是 bug）。修正：`pickPrompt` 加 `kind === 'none' → settings.nonePrompt` 分支；options 加「🚫 不推送 自訂提示詞」textarea，**預設空白**；空字串送進 `client.generateReport` 後 lib 內 `customPrompt || 'Create a report based on...'` fallback 到 NLM 內建預設報告 prompt
- **提示詞收藏 + 黑白 SVG 圖示 + UI 整合**（v0.6.3）：所有 emoji 按鈕圖示改為 `<svg symbol>` 黑白 stroke 系統（13 個 symbols，popup.html 頂部定義）；kind chip 預設改為「不推送」，順序前移；匯入/清空/分析三顆批次按鈕整合成一列 `actions-row3`；新增 ✏️（`#btn-prompt-settings`）→ `position: fixed` 右側書籤式抽屜 `#pp-panel`，可新增/刪/選提示詞；選中的 content 在 `generateAndPushForTask` 優先用 `task.customPrompt`（override options 的預設 prompt）；`import_urls` 成功判定改為 `succeeded > 0`（寬鬆，任一 URL 成功即 ✅）
- **CSS 全部換淺色**：白底 / 深灰文字 / 黑底主 CTA / 灰邊 outline 次按鈕 / divider 分批次操作區
- **`options.html` 移除 `notebookIdNews` / `notebookIdYt`**：不再需要、新使用者一進 popup 就動態列出選

**RPC 反向工程來源**：[notebooklm-py docs/rpc-reference.md](https://github.com/teng-lin/notebooklm-py/blob/main/docs/rpc-reference.md)。`lib/notebooklm.js` 加 `listNotebooks(signal)` + `createNotebook(title, signal)` 兩個方法，沿用既有 `_rpcCall` 走 batchexecute。listNotebooks 解析（從 `notebooklm-py types.py Notebook.from_api_response` 抄出）：`entry[0]` = title（string）、`entry[2]` = id（string）。**注意**：`rpc-reference.md` 文件寫的是 `entry[0]=id, entry[1][4]=title`，是錯的 — 實際 response 以 title 為 `entry[0]`，lib 裡有 `.replace(/^thought\n/, '').trim()` 去掉前置雜訊。

`manifest.json::permissions` 加 `"tabs"` 是給「匯入目前頁面」用（`chrome.tabs.query({active:true,currentWindow:true})` 讀 URL）；要的不只是 `activeTab`，因為 activeTab 只在使用者點 extension icon 那一刻授權同分頁，跨 popup 互動不夠用。

### 認證模型 — 大幅簡化於 hourly 腳本

直接吃**瀏覽器既有的 NotebookLM 登入 cookies**：`background.js` 進入點先 `fetch('https://notebooklm.google.com/')`，從 HTML regex 抽出 `SNlM0e`（CSRF）+ `FdrFJe`（session ID），再以瀏覽器自動帶上的 cookies 呼叫 `batchexecute` RPC。**不需** `~/.notebooklm/storage_state.json`、Playwright headed 模式、PSIDRTS cookie 保活那些 hack（hourly 腳本仍需要那套，因為它跑在無頭 Python 環境）。

### 結構

| 檔案 | 角色 |
|---|---|
| `manifest.json` | MV3，permissions: `storage` / `clipboardRead` / `notifications` / `alarms`；host_permissions: `notebooklm.google.com` + VM URL |
| `popup.html/js/css` | 工具列 popup UI：notebook 下拉、kind chip（不推送預設）、✏️ 提示詞收藏、「新增目前頁面」+ 建立新筆記本、批次操作三合一列（匯入/清空/分析）+ 一鍵、task 清單、固定右側 `#pp-panel` 書籤抽屜。所有按鈕圖示用 SVG symbol（popup.html 頂部 `<svg display:none>` 定義 13 symbols）|
| `options.html/js` | 設定頁：notebook ID（新聞 / YT）、VM URL、自訂提示詞、`skipVmPush` 勾選 |
| `background.js` | Service worker — 統一處理 NotebookLM API + 推送 VM + 桌面通知；popup/options 都透過 `chrome.runtime.sendMessage` 委派 |
| `lib/notebooklm.js` | `class NotebookLMClient` — 從 `notebooklm-py` 0.3.4 抄出的 batchexecute RPC 客戶端（`init` / `listSources` / `addUrlSource` / `addTextSource` / `deleteSource` / `generateReport` / `waitForCompletion` / `downloadReport`），含 chunked response 解碼（strip `)]}'\n` → 解析 byte-count + JSON 交替 → 抽 `wrb.fr` rpcId 對應結果） |
| `INSTALL.md` | 給拿到 zip 的使用者照著做的安裝 / 使用 / 故障排除手冊 |
| `README.md` | 給開發者看的設計說明 + 故障排除 |

對應的打包腳本：`scripts/package_extension.sh`（純 Python 不依賴 zip 命令）→ 產出 `dist/nlm-helper-v{version}.zip`，從 `manifest.json` 抓版本號自動命名。

### MV3 Service Worker idle timeout — 必修陷阱

**問題**：MV3 service worker 30 秒沒事做就會被 Chrome 殺掉。當使用者按下「匯入幾十個 URL」或「產生分析報告」（涉及 `waitForCompletion` 內每 2-10 秒輪詢），popup 關掉後 SW 在 sleep 期間就死了，迴圈當場斷掉，使用者看到的就是「匯入到一半就停」。

**修法（[extension/background.js](extension/background.js#L74)）**：
```
chrome.alarms.create('nlm-keepalive', { periodInMinutes: 0.4 })  // 每 24 秒喚醒
```
搭配 `withKeepalive(fn)` wrapper：每個長操作開始前 startKeepalive、結束後 stopKeepalive；引用計數讓巢狀（一鍵流程內呼三個動作）也安全。

**配套保險**：
- 每個 URL 包 `withTimeout(promise, PER_URL_TIMEOUT_MS)`（目前 **60s**，PDF 用 `PDF_TIMEOUT_MS=90s`），單個卡死的 URL 不會凍結整批
- v0.5.2 之前：連續呼叫之間 sleep 300ms 避免 rate limiting；**v0.5.3 改 worker pool 並行**：`IMPORT_CONCURRENCY=3`、`CLEAR_CONCURRENCY=5`，N 個 worker 從共享 `nextIndex` 取下個 URL 處理，沒有 sleep（worker 之間自然錯開）。實測 116 URL 從 ~2 分鐘 → ~30 秒（~4x 加速）。Cancel 仍可隨時生效 — worker 開頭 `if (_cancelRequested) return`，外層 `Promise.all` 收完所有 worker 後 `checkCancel()` 統一拋 CancelError 走「已取消」路徑

### 多任務並行（v0.6.0+）

使用者一次看好幾篇研究報告，想分別匯入到不同 notebook 並各自分析。v0.5 之前 popup 是「單任務」設計（`lastRun` 單 slot、global `_cancelRequested`），第二個動作會卡住第一個。v0.6 改成 task-based：

**核心抽象 `Task` class**（[extension/background.js](extension/background.js)）：每個動作（匯入剪貼簿、匯入目前頁、清空、分析、一鍵）都建一個 Task instance。Task 持有：
- `id` (`task_<ts>_<rand>`)、`label`（「匯入頁面」/「清空 sources」/「產生分析報告」/「一鍵 清空→匯入→分析」）
- `notebookId` + `notebookTitle`（從 `cachedNotebooks_v2` cache 查得）、`kind` (`news/yt/none/null`)
- 進度欄位 `phase / current / total / message / startedAt / finishedAt / ok / cancelled / summary / error`
- **自有的 `AbortController`** + `_cancelRequested` flag — 取消只影響這個 task，不會牽連其他並行 task
- `task.setState(patch)` 修改欄位 + 持久化 + 廣播；`task.checkCancel()` / `task.signal` 由核心函式內呼叫

`_tasks: Map<id, Task>` 是 module-level registry。`chrome.storage.local.tasks` 持久化 serialized 陣列；SW 重啟時自動把所有 in-flight task 標成 cancelled（重啟後 promise chain 必然斷掉，UI 不該顯示永遠卡住）。Done task 30 分鐘後自動從 `_tasks` 移除（避免無限長）。

**訊息協定**：`task_update` / `task_remove`（broadcast）取代舊的 `progress`。`list_tasks` 給 popup 開啟時還原。`cancel_task {taskId}` / `cancel_all_tasks` / `dismiss_task {taskId}` 三個取消相關 action。

**核心函式簽名**：`importUrlsToTask(task, urls)` / `clearSourcesForTask(task)` / `generateAndPushForTask(task)` / `runCombinedForTask(task, urls)` — 全部吃 task 物件。Worker pool 內 `if (task.isCancelled()) return` 取代以前的 `if (_cancelRequested)`。

**Message handler 立即回 taskId**：`runTaskInBackground(task, coreFn, onSuccess, errorTitle)` 包裝 — 不 await 內部 async IIFE，所以 message handler 收到請求後 `sendResponse({ ok:true, taskId })` 立刻回，task 在背景跑。Popup 不會卡在 await bgSend，使用者可立刻開下一個 task。

**Popup UI**（[extension/popup.html](extension/popup.html) + [extension/popup.js](extension/popup.js)）：原本的「單一狀態框」改成 task list — `<div class="task-row">` 每個 task 一 row，含 icon (`⏳/✅/⛔/❌`)、label、elapsed、`✋ 取消此任務` / `✕ 移除` 兩顆按鈕（active 顯前者、done 顯後者）。`<template id="task-row-template">` 用 `cloneNode` 產 row。Popup 維護 `taskRows: Map<taskId, {rowEl, task}>` 本地副本，每秒 tick 更新 active 的 elapsed。`✋ 全部取消`（紅色小 chip）只在 active task ≥ 2 時顯示。

**動作按鈕都不再 disable**：使用者可以連續點「📌 匯入目前頁面」(N 次切不同分頁)，每次都開新 task；對同一個 notebook 同時跑多個動作也不擋（NLM 端有自己的內部 queue）。

**Toast 取代舊的「請先選 notebook」status 提示**：popup 底部 `.toast` 浮動短訊 2.5s 自動消失。

### 取消執行（v0.3.3+，仍適用 v0.6 並行架構）

長操作（特別是匯入大批 URL 或等 NLM 跑 200+ sources 的 polling）使用者可能想中途中斷。早期版本沒這功能，只能去 `chrome://extensions/` 按 refresh 強殺 SW，但這會讓 NLM 端 sources 卡半路（已 add 的留著、迴圈中斷）、popup UI 也回不到乾淨狀態。

**v0.3.2 → v0.3.3 演進**：v0.3.2 只有 flag-based cancel，使用者反映按了沒效 — 因為當下正卡在 `client.addUrlSource(...)` 等 NLM 回應的 fetch 內，flag 要等該 fetch 處理完才被下個迴圈迭代讀到，使用者觀感「按了沒反應」。v0.3.3 改成雙層機制：

1. **`_cancelRequested` flag + `checkCancel()`**：迴圈下次迭代讀到即拋 `CancelError`。檢查點分布：
   - `importClipboardUrls` / `clearSources` 每次迭代**開頭與結尾**（結尾的 check 處理「當前 URL 處理完正要 sleep」場景）
   - `generateAndPushReport` 的 `waitForCompletion` `onTick` 內（每輪 polling，2-10s 間隔）— 需要 [lib/notebooklm.js](extension/lib/notebooklm.js) 把 `onTick` 改成 `await onTick(...)` 讓 onTick 內 throw 能冒出
   - `runCombined` 三階段之間
   - 所有 `sleep` 改用 `cancellableSleep(ms)`（內部每 100ms `checkCancel()`），讓使用者按取消後最多等 100ms
2. **`_currentAbortController` + `signal` 傳遞**：`requestCancel()` 同時 `controller.abort()`，正在飛的 NLM RPC fetch 立即 reject 為 `AbortError`。`NotebookLMClient` 每個方法都加 `signal` 參數透傳給 `_rpcCall` → fetch options。`waitForCompletion` 也接 `opts.signal`、內部 sleep 拆 100ms 切片 + `signal.aborted` 檢查。VM push 的 fetch 也帶 signal。
3. **`isCancelError(e)`** 同時辨識 `CancelError` 與 fetch `AbortError`，走灰色「已取消」路徑（不是紅色 err）。

`startRun()` 開頭 `resetCancel()` 把 flag 歸零 + 建立**新** `AbortController`（前次 abort 過的 controller 不能重用 — signal 一旦 aborted 就永遠 aborted）。`cancel_run` message handler 只設旗標 + abort、立即回 `{ok:true}`，不在這邊呼 `finishRun`（讓正在跑的迴圈自己拋、由各 action 統一處理，避免 race）。

**UI**：popup 取消按鈕 [popup.html](extension/popup.html) `#btn-cancel`，預設 `hidden`；`renderRunState()` 只在 phase 屬於 `ACTIVE_PHASES` 時 `showCancel(true)`，`done` 立即藏。按下去後文字改「⏳ 取消中…」+ disable，5 秒後文字復原（防止 SW 萬一卡住、按鈕還能再按）；實際狀態還原靠 background 廣播 `done(cancelled=true)` progress 訊息。

**限制**：NLM artifact 一旦 generate 開始，伺服器端任務還是會跑完（extension 只是不再等它），UI 在分析取消時顯示「⛔ 分析已取消（NLM 端任務可能仍在背景跑）」。已 add 的 sources 也留在 notebook（取消是中止流程，不是 rollback）。

### 進度持久化 — popup 關閉重開能還原

每一步都把 `{phase, label, current, total, message, startedAt, finishedAt?, ok?, error?}` 寫進 `chrome.storage.local.lastRun` 並透過 `chrome.runtime.sendMessage({action:'progress', state})` 廣播。Popup 收到廣播即時刷新；popup 重新開啟時呼 `get_last_run` 還原；popup 內每秒 tick 一次更新「已 Xs」計時。`phase` 集合 `{starting, clear, import, generate, download, push, combined-start, between, done}`，`renderRunState()` 看 phase 決定 UI（進行中 / 已完成 / 待機）。

### 一鍵流程的成功標準 — 寬鬆判定

`run_combined`（清空 → 匯入 → 分析）的成功標準是 **`generate.skipped || generate.pushed`**，不要求 import / clear 都 0 失敗。理由：NLM 對 200+ sources 偶發個位數 URL 失敗（4/193 之類），整體分析報告仍能正常產出且推送到 VM、進到「分析結果」頁——這種情況硬判失敗是誤報。改為「分析有產出且推送成功」即算成功，匯入 / 清空有失敗只在標題加「（含警告）」。**單獨**呼叫 `import_urls` / `clear_sources` 時仍維持嚴格判定（任一失敗即失敗），因為使用者明確只想做這一件事。

### `waitForCompletion` 超時 — 600s

`generateAndPushReport()` 等待 NotebookLM 產生報告的超時是 600 秒（10 分鐘），不是 300 秒。200+ sources 時 NLM 經常超過 5 分鐘還在跑，300s 會把好好的執行誤判為超時。改參數時注意 popup 顯示也要對齊（`message` 寫的「上限 N s」）。

### PDF 匯入 timeout — 90s

`addUrlSource` RPC 是同步的：NLM 伺服器在回傳之前會先 HTTP 抓取並初始驗證該 URL 的內容。一般網頁用 `PER_URL_TIMEOUT_MS = 60_000`（60s，World Bank 等政府網站頁面複雜，30s 不夠）；PDF 另用 `PDF_TIMEOUT_MS = 90_000`（NLM 需下載整個檔案）。`background.js` 的 `isPdfUrl(url)` 偵測 `.pdf` 結尾；`importUrlsToTask` worker 自動切換，不需呼叫方感知。若以後遇到其他慢 URL 類型（如大型 PPTX），套用相同模式新增類型判斷 + 對應常數。

### `skipVmPush` 設計（給沒有自架 VM 的使用者用）

Options 頁有「不推送到 VM（純本機模式）」勾選，存 `chrome.storage.local.skipVmPush`。`generateAndPushReport()` 跑完下載報告後讀此 flag：勾起來就直接顯示在 popup（不打 VM），沒勾才 POST 到 `${vmBaseUrl}/api/radar/extension-report`。**分發 zip 給朋友時必須叮嚀對方勾起來**，不然他們的報告會推到你的 VM 雷達系統。

### 分發策略（已決：方式 C — zip + Load unpacked）

開發者帳號費 $5 + Chrome Web Store 一週審查不划算（且 NotebookLM 內部 RPC 反向工程可能被 reviewer 質疑），先用 zip 分發：
1. `bash scripts/package_extension.sh` → `dist/nlm-helper-v{ver}.zip`
2. 對方收到 zip → 解壓 → `chrome://extensions/` → 開發人員模式 → 載入未封裝項目 → 選資料夾
3. 對方 options 設定自己的 notebook ID + 勾「不推送到 VM」（如不需要推 VM）
4. 對方需自行登入 NotebookLM（每個使用者用自己帳號）

更新版本：bump `manifest.json::version` → 重新打包 → 對方下載新 zip 蓋掉舊資料夾 → `chrome://extensions/` 按重新整理；`chrome.storage.local` 內的設定不會被清掉。

### 改動 Extension 時的注意事項

- **改 NotebookLM RPC**（`lib/notebooklm.js` 的 RPC ID 常數 + 各方法 params 結構）：對應 `notebooklm-py` 同版本（pip show notebooklm-py 看 0.3.x），若 Google 改了內部 API、`notebooklm-py` 升版時，這邊要同步抄
- **改 background → popup 訊息協定**：popup.js 的 `bgSend()` + `onMessage` 監聽要一起改；`progress` 廣播 state 結構保持向後相容比較好
- **新增 chrome permission**：對方升級時 Chrome 會強制停用 extension 直到使用者手動重新啟用，盡量避免無意義加 permission
