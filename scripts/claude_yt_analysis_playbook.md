# Claude Code 自動 YouTube 分析 — 迴圈說明書（playbook）

每次 `/loop` 觸發時，Claude Code 照這份步驟做一輪。**分析由 Claude Code 自己完成（模型推理），不接 Gemini / Claude API。**

## 每輪步驟

1. **抓新影片**
   ```
   python scripts/claude_yt_analyze.py fetch
   ```
   輸出 JSON：`{"count": N, "videos": [...]}`。
   - 若 `count == 0`→ 本輪沒有新影片，**不要推送**，直接結束本輪（回報「無新影片」即可）。
   - 若 `count > 0`→ 進下一步。

2. **（選用）補充內容**
   `videos[].description` 已含前 500 字描述，通常足夠。若標題/描述資訊太少、且需要更準確判斷，可用 WebFetch 抓影片頁補充背景（非必要，避免拖慢）。

3. **自己分析、寫報告**
   以**繁體中文**、金融分析師視角，產生 Markdown 報告，存到暫存檔（例如 `C:\Users\User\AppData\Local\Temp\claude_yt_report.md`）。格式對齊系統既有 YT 分析：
   - 每部影片一節：`## 一、【頻道】標題`
   - 固定三點：`1. **事件描述**` / `2. **市場與國別影響**` / `3. **後續分析**`
   - 結尾 `### 關鍵來源`，逐點列 `標題（URL）`
   - **重要**：來源多為時事評論／爆料頻道，報告開頭加一行 disclaimer：內容為頻道宣稱、未經查證，分析聚焦「若屬實的市場影響」。

4. **推回系統**
   ```
   python scripts/claude_yt_analyze.py push --file "<報告檔路徑>" --ids "<逗號分隔的 video_id>" --title "Claude Code 自動分析（N 部影片）"
   ```
   成功後腳本會把這批 `video_id` 記進 `scripts/.claude_yt_state.json` 去重，下一輪 `fetch` 不會再出現。
   報告會出現在系統「分析結果 → 🧩 Extension YT」分頁。

## 注意
- `fetch` / `push` 的 VM 位址與 service key 從 `scripts/.env.local`（`API_BASE_URL` / `API_TOKEN`）讀取。
- 去重靠 `scripts/.claude_yt_state.json`（只存最近 500 個 video_id），不會動到 `is_new` 旗標，因此不影響 LINE「yt」未讀查詢與 23:00 的 mark-all-seen 排程。
- 這條路徑與 (a) VM 端 Gemini YT 自動分析（每 3h，→ 📺 Gemini YouTube）、(b) NotebookLM hourly（→ 📺 NLM YouTube）完全獨立，三者並存互不干擾。
- 建議節奏：每 3 小時一輪（對齊系統 YouTube 偵測排程 30 分鐘抓一次的累積量）。
