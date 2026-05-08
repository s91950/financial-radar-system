# 金融雷達 NotebookLM 助手 — 安裝說明（給其他使用者）

> 這是 Chrome / Edge 擴充功能，三 / 四顆按鈕讓你**手動**對 NotebookLM 做：
> 匯入剪貼簿 URL、清空 sources（保留 [SKILL] 框架）、產生分析報告、一鍵把這三件事串起來。
>
> 認證是直接吃**你瀏覽器既有的 NotebookLM 登入 cookies**，不需要任何 OAuth / API key。

## 安裝步驟（約 1 分鐘）

1. **解壓縮** 收到的 `nlm-helper-v0.x.x.zip`，得到 `extension/` 資料夾（請放在不會隨便刪掉的位置，例如 `C:\Tools\nlm-helper\`）
2. 開 Chrome 或 Edge，網址列輸入 `chrome://extensions/`（Edge 是 `edge://extensions/`）
3. **右上角開啟「開發人員模式」**（Edge 是「開發人員模式」一樣，左下或右上）
4. 點「**載入未封裝項目**」(Load unpacked)，選擇剛剛解壓縮出的那個 `extension/` 資料夾
5. 工具列右上的 puzzle icon → 把「金融雷達 NotebookLM 助手」釘選（pin）出來方便使用
6. **第一次先點齒輪「設定」**：填入你自己的 notebook ID（從 NotebookLM 網址 `notebooklm.google.com/notebook/{ID}` 抓出來那串），新聞 / YouTube 各一個
7. **如果你沒有自己架設金融雷達系統**：把「不推送到 VM（純本機模式）」勾起來。不勾的話會嘗試把報告 POST 給作者的 VM，會失敗或推到別人那裡。
8. 確認你瀏覽器有登入 [https://notebooklm.google.com](https://notebooklm.google.com)

## 使用

點工具列 icon → 跳出小視窗 → 切換要操作的 notebook（新聞 / YT）→ 點按鈕：

- **📥 匯入剪貼簿 URL**：先複製一堆 URL（一行一個或混在文字中都吃），按下去就會逐個匯入
- **🗑 清空 sources**：刪掉 notebook 裡所有非 `[SKILL] ` 開頭的 sources（保留分析框架檔）
- **🧠 產生分析報告**：用內建提示詞跑一份分析報告（最久 5 分鐘）
- **🚀 一鍵 清空 → 匯入 → 分析**：上面三件事串起來一次跑完

完成後會跳**桌面通知**（首次使用時 Chrome 會問你是否允許，請允許）。即使把 popup 關掉、再打開，也會看到「進行中 / 已完成」的狀態還原。

## 常見狀況

| 訊息 | 原因 / 解法 |
|---|---|
| `未登入 NotebookLM` | 開 [notebooklm.google.com](https://notebooklm.google.com) 登入後再用 |
| `尚未設定 notebook ID` | 點齒輪「設定」填好 |
| 推送 VM 失敗 | 沒架雷達服務時請勾「不推送到 VM」 |
| 一直在「停用開發人員模式擴充功能」橫幅 | Chrome 對非商店擴充功能的固定提示，點「保留」即可 |
| 桌面通知沒跳 | 系統通知設定可能擋掉 Chrome；macOS 要去「系統設定 → 通知 → Google Chrome」開啟 |

## 更新版本

收到新版 zip 時：
1. 解壓蓋掉舊資料夾（或解到新位置）
2. `chrome://extensions/` 找到此擴充功能 → 按**圓箭頭重新整理**圖示
3. 不會清掉你的設定（notebook ID / VM URL 等都保存在 chrome.storage）

## 隱私

- 此擴充功能**不會**把你的 NotebookLM 帳號資料 / cookies 傳給任何第三方
- 唯一的對外連線：(1) 呼叫 `notebooklm.google.com` 內部 API（你本來就在用的）；(2) 如果你**沒勾**「不推送到 VM」，會 POST 報告全文 + 來源標題到設定中的 VM URL
- 剪貼簿讀取**只在你按下匯入 / 一鍵按鈕當下**才發生，不會背景監控
