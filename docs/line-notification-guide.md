# LINE 通知功能說明

## 架構說明

```
使用者傳訊息給 LINE Bot
        ↓
LINE 呼叫 Webhook URL（VM 上的 /api/line/webhook）
        ↓
系統判斷指令類型
        ↓
用 Reply API 回覆（完全免費，不計入每月 200 則配額）
```

### 主動推播 vs 被動回覆

| 類型 | 說明 | 費用 |
|------|------|------|
| 主動推播 | 系統偵測到緊急事件時自動發送 | 每月 200 則免費 |
| 被動回覆 | 使用者傳訊息，Bot 回覆 | 完全免費，無上限 |

---

## 指令清單

### 新聞指令

| 指令 | 說明 |
|------|------|
| `通知` | 查詢未讀緊急新聞（自上次查詢後的新內容） |
| `通知1天` | 過去 1 天的緊急新聞 |
| `通知今日` / `通知今天` | 今日的緊急新聞 |
| `通知3小時` | 過去 3 小時的緊急新聞 |

### YouTube 指令

| 指令 | 說明 |
|------|------|
| `yt` / `YT` / `yt通知` | 查詢未讀 YouTube 影片 |
| `yt1天` | 過去 1 天的 YouTube 影片 |
| `yt今日` / `yt今天` | 今日的 YouTube 影片 |
| `yt3小時` | 過去 3 小時的 YouTube 影片 |

> 其他任意訊息 → Bot **不回應**

---

## 設定方式

### 1. 環境變數（.env）

```env
LINE_CHANNEL_ACCESS_TOKEN=your_token   # 必填（推播＋回覆都需要）
LINE_CHANNEL_SECRET=your_secret        # 必填（Webhook 簽名驗證）
LINE_TARGET_ID=                        # 留空 = 停用主動推播
LINE_NOTIFY_MIN_SEVERITY=critical      # 主動推播門檻
```

### 2. LINE Developers Console

1. 前往 [developers.line.biz](https://developers.line.biz/)
2. 選 Provider → Messaging API Channel
3. **Messaging API** 分頁 → **Webhook URL**
4. 填入：`https://[你的域名]/api/line/webhook`
   （LINE 要求 HTTPS，需要設定域名與憑證）
5. 開啟 **Use webhook** 開關
6. 點 **Verify** 測試連線

---

## 停用主動推播保留被動回覆

在系統設定頁面 → 通知設定 → 關閉 LINE 通知開關

或在 `.env` 將 `LINE_TARGET_ID` 留空，系統就不會主動推送。
被動回覆（使用者傳訊觸發）不受影響。

---

## HTTPS 設定（LINE Webhook 必要）

LINE 只接受 HTTPS 的 Webhook URL，有兩種方式：

### 方式 A：購買域名 + Let's Encrypt（建議）
- 費用：域名約 $3-10 美元/年
- 設定後網址格式：`https://你的域名/api/line/webhook`

### 方式 B：Cloudflare Tunnel（完全免費）
- 不需要域名，自動產生 HTTPS 網址
- 網址格式：`https://xxx.trycloudflare.com/api/line/webhook`
- 缺點：重啟 cloudflared 後網址會變動（付費版可固定）
