# Claude Code 自動 YouTube 分析 — 迴圈說明書（playbook）

**模式：NotebookLM 分析（省 token）。** 每次 `/loop` 觸發，Claude Code 只負責「觸發 NLM 腳本 +
回報結果」，**分析全部交給 NotebookLM**，Claude Code 不自己讀影片、不自己寫分析，所以幾乎不耗 token。

## 每輪步驟

1. **跑 NotebookLM YT 分析**（這一步就把「抓新影片 → 匯入 NLM → 產生報告 → 下載 → 推回系統」全做完）：
   ```
   python "C:\nlm_scripts\notebooklm_hourly.py" --yt-only
   ```
   - 腳本自己用 `.nlm_state.json` 記錄上次跑的時間，只處理新影片；沒有新影片就自然結束。
   - 報告會出現在系統「分析結果 → 📺 NLM YouTube」。
   - 失敗最常見原因：`Cookie 刷新失敗：認證已完全過期` → 需在本機手動跑一次 `notebooklm login`（互動瀏覽器登入）。

2. **回報結果**：讀腳本輸出 / `C:\nlm_scripts\nlm_reports\run.log` 末幾行，用一兩句話回報「成功推送 / 無新影片 / 登入過期需 notebooklm login」。**不要**自己分析影片內容。

## 注意
- 建議節奏：每 3 小時一輪（對齊系統 YouTube 偵測累積量）。沒新影片的輪次幾乎瞬間結束。
- 這條路徑專責 **YT NLM 分析**。為避免重複分析，Windows 工作排程「NotebookLM 金融分析」已改為 `--news-only`（只跑新聞）。⇒ YT 由本 /loop 負責，前提是 Claude Code 視窗開著；若想要 YT 也 always-on，可把 Windows 任務改回不帶旗標（恢復新聞+YT 都跑）。
- 與 VM 端 Gemini YT 自動分析（每 3h → 📺 Gemini YouTube）完全獨立、並存互不干擾，可當備援。

## 備援：不依賴 NotebookLM 的純 Claude 分析（會耗 token）
若 NLM 登入一直無法恢復、又想要 YT 分析，可改用 `scripts/claude_yt_analyze.py`（fetch → Claude 自己寫 → push 到 🧩 Extension YT）。這是 token 成本較高的退路，預設不用。
