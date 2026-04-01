# 系統網址說明

## 網址總覽

| 網址 | 環境 | 用途 | 穩定性 |
|------|------|------|--------|
| `http://localhost:5173` | 本機開發 | 前端開發伺服器 | 本機開著才有效 |
| `http://localhost:8000` | 本機開發 | 後端 API | 本機開著才有效 |
| `http://34.23.154.194` | 雲端（正式） | 系統主網頁 | 永久固定 |
| `https://donate-collections-smooth-educational.trycloudflare.com` | 雲端（HTTPS 通道） | LINE Webhook 專用 | VM 重啟後會變 |

---

## 各網址詳細說明

### 本機開發環境

#### `http://localhost:5173`
- **用途**：前端 React 開發伺服器（Vite）
- **啟動方式**：`cd frontend && npm run dev`
- **限制**：只有你自己的電腦可以連，電腦關機即失效
- **適合**：開發新功能、測試 UI 改動

#### `http://localhost:8000`
- **用途**：後端 FastAPI 直接存取（含 API 文件）
- **啟動方式**：`python -m uvicorn backend.main:app --reload`
- **API 文件**：`http://localhost:8000/docs`
- **限制**：同上，僅本機可用

---

### 雲端正式環境

#### `http://34.23.154.194` ← 給使用者的主網址
- **用途**：系統正式網頁介面
- **伺服器**：Google Cloud VM（us-east1-d，美國）
- **服務**：nginx 提供前端靜態檔案，並將 `/api/` 轉發到後端
- **穩定性**：IP 固定，24 小時運作，不受本機狀態影響
- **費用**：永久免費（Google Cloud Always Free 方案）
- **限制**：http（非 https），瀏覽器會顯示「不安全」警告，但功能正常

#### `https://donate-collections-smooth-educational.trycloudflare.com` ← LINE Webhook 專用
- **用途**：LINE Bot Webhook 接收端點（LINE 平台要求 HTTPS）
- **實際指向**：同一台 VM 的 port 80（透過 Cloudflare Tunnel 加密）
- **穩定性**：⚠️ VM 重啟後網址會改變，需重新更新 LINE Console
- **費用**：免費（Cloudflare Tunnel 免費方案）
- **使用者需要知道嗎**：不需要，只有 LINE 平台會呼叫此網址

---

## 架構圖

```
使用者瀏覽器
    │
    ▼
http://34.23.154.194         ← 系統網頁入口
    │
    ▼
Google Cloud VM（nginx）
    ├── / → 前端靜態檔案（React）
    ├── /api/* → FastAPI 後端（port 8000）
    └── /ws → WebSocket（即時更新）

LINE Bot
    │
    ▼
https://donate-...trycloudflare.com/api/line/webhook
    │（Cloudflare Tunnel 加密）
    ▼
Google Cloud VM（同一台）
    └── /api/line/webhook → LINE Webhook 處理
```

---

## 未來升級：購買域名後

買域名後（如 `radar.example.com`）可以統一成：

| 目前 | 升級後 |
|------|--------|
| `http://34.23.154.194` | `https://radar.example.com` |
| `https://donate-...trycloudflare.com/api/line/webhook` | `https://radar.example.com/api/line/webhook` |

兩個功能合一，使用者和 LINE 都用同一個網址，且支援 HTTPS。

---

## VM 重啟後更新 LINE Webhook 步驟

當 VM 重啟導致 Cloudflare 網址改變時：

```bash
# 1. SSH 連進 VM 查看新網址
sudo journalctl -u cloudflared -n 20 --no-pager | grep trycloudflare

# 2. 複製新網址，格式如：
#    https://xxxx-xxxx-xxxx-xxxx.trycloudflare.com

# 3. 前往 LINE Developers Console → Messaging API → Webhook URL
# 4. 更新為：https://新網址/api/line/webhook
# 5. 點 Verify 確認
```
