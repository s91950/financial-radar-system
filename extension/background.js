// Background service worker — 統一處理 NotebookLM API + 推送 VM。
// 重點機制（v0.6+ task-based）：
//   1. chrome.alarms keepalive：避免 MV3 service worker 在長操作（特別是 waitForCompletion
//      polling 之間的 sleep）被 Chrome idle timeout 殺掉，造成「匯入到一半就停」。
//   2. 多任務並行：每個動作（匯入 / 清空 / 分析 / 一鍵）都是獨立的 Task 物件，
//      有自己的 AbortController + cancel flag + 進度欄位。使用者可同時開好幾個。
//      訊息協定 'task_update' / 'task_remove' 廣播給 popup 同步 UI。

import { NotebookLMClient, extractUrlsFromText } from './lib/notebooklm.js';

const SKILL_PREFIX = '[SKILL] ';
const KEEPALIVE_ALARM = 'nlm-keepalive';
// 定時自動 YT 分析：用活著的瀏覽器 session 定期把系統偵測到的新影片匯入 NLM 分析推回系統
const AUTO_YT_ALARM = 'nlm-auto-yt';
const AUTO_YT_MAX_ANALYZED_IDS = 500;
const PER_URL_TIMEOUT_MS = 60_000;
// PDF 需要 NLM 伺服器端同步下載整個檔案才回應，60s 通常不夠，給 90s。
const PDF_TIMEOUT_MS = 90_000;
// v0.5.3：worker pool 並行匯入。NLM 端能吃 3-5 並行 add_url／delete_source。
const IMPORT_CONCURRENCY = 3;
const CLEAR_CONCURRENCY = 5;
// task done 後保留多久才從清單自動移除
const DONE_TASK_TTL_MS = 30 * 60 * 1000;

const DEFAULT_NEWS_PROMPT = `你是一個資深金融分析師團隊。請根據提供的新聞 sources，產出一份繁體中文分析報告。

格式要求：
- 最多 2 個分類（依新聞數量決定，少於 10 篇只用 1 個）
- 每個分類用 \`## 分類名稱\` 開頭
- 每個分類下最多 3 個重點，每個重點用以下固定格式：
  1. **事件描述** — 簡短描述事件本身
  2. **市場與國別影響** — 對哪些市場 / 國家 / 資產類別有影響
  3. **後續分析** — 後續觀察重點 / 可能演變

每篇引用來源請以 \`- 一-1. 標題（URL）\` 格式列在分類最後的 \`### 關鍵來源\` 區塊。

請保持精簡、避免空泛敘述。`;

const DEFAULT_YT_PROMPT = `你是一個資深金融分析師團隊。請根據提供的 YouTube 影片 sources，產出一份繁體中文分析報告。

每支影片獨立成段，格式：
\`一、【頻道名稱】影片標題\`

每段內 3 個重點（YouTube Shorts 只用 1 個重點）：
1. **核心觀點** — 影片想傳達的核心觀點
2. **論據與資料** — 影片提供的論據 / 資料
3. **後續觀察** — 後續觀察方向

請保持精簡、避免空泛敘述。`;

async function getSettings() {
  const data = await chrome.storage.local.get([
    'vmBaseUrl', 'apiToken', 'newsPrompt', 'ytPrompt', 'nonePrompt', 'skipVmPush',
  ]);
  return {
    vmBaseUrl: (data.vmBaseUrl || 'http://34.23.154.194').replace(/\/$/, ''),
    apiToken: data.apiToken || '',
    newsPrompt: data.newsPrompt || DEFAULT_NEWS_PROMPT,
    ytPrompt: data.ytPrompt || DEFAULT_YT_PROMPT,
    // 不推送提示詞預設空白 — 空字串送進 client.generateReport 會走 NLM 內建預設
    // 'Create a report based on the provided sources.'（見 lib/notebooklm.js generateReport）
    nonePrompt: typeof data.nonePrompt === 'string' ? data.nonePrompt : '',
    skipVmPush: !!data.skipVmPush,
  };
}

function pickPrompt(settings, kind) {
  if (kind === 'yt') return settings.ytPrompt;
  if (kind === 'none') return settings.nonePrompt;  // 空字串 → NLM 走預設
  return settings.newsPrompt;
}

function isPdfUrl(url) {
  try {
    return new URL(url).pathname.toLowerCase().endsWith('.pdf');
  } catch {
    return false;
  }
}

function withTimeout(promise, ms, label = '') {
  return Promise.race([
    promise,
    new Promise((_, rej) => setTimeout(() => rej(new Error(`等待超時 ${Math.round(ms / 1000)}s${label ? `（${label}）` : ''}`)), ms)),
  ]);
}

// ── 取消錯誤類別 ────────────────────────────────────────────────────────

class CancelError extends Error {
  constructor(msg = '已取消') { super(msg); this.name = 'CancelError'; this.cancelled = true; }
}

function isCancelError(e) {
  if (!e) return false;
  if (e.name === 'CancelError' || e.cancelled === true) return true;
  if (e.name === 'AbortError') return true;
  if (/aborted|AbortError/i.test(String(e.message || ''))) return true;
  return false;
}

// ── Task 類別 ──────────────────────────────────────────────────────────
// 每個動作（匯入 / 清空 / 分析 / 一鍵）都建一個 Task。多 task 可並行。
// _tasks Map 由 background 持有；popup 透過 task_update / task_remove 廣播同步 UI。

class Task {
  constructor({ label, notebookId, notebookTitle, kind, customPrompt }) {
    this.id = `task_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    this.label = label;
    this.notebookId = notebookId;
    this.notebookTitle = notebookTitle || notebookId?.slice(0, 8) || '';
    this.kind = kind || null;
    this.customPrompt = customPrompt || null;
    this.startedAt = Date.now();
    this.finishedAt = null;
    this.ok = null;
    this.cancelled = false;
    this.phase = 'starting';
    this.current = 0;
    this.total = 0;
    this.message = '初始化…';
    this.summary = null;
    this.error = null;
    this.abortController = new AbortController();
    this._cancelRequested = false;
  }

  get signal() { return this.abortController.signal; }

  requestCancel() {
    this._cancelRequested = true;
    try { this.abortController.abort(); } catch { /* ignore */ }
  }

  checkCancel() {
    if (this._cancelRequested) throw new CancelError();
  }

  isCancelled() { return this._cancelRequested; }

  async setState(patch) {
    Object.assign(this, patch);
    await persistTasks();
    broadcastTaskUpdate(this);
  }

  serialize() {
    return {
      id: this.id,
      label: this.label,
      notebookId: this.notebookId,
      notebookTitle: this.notebookTitle,
      kind: this.kind,
      startedAt: this.startedAt,
      finishedAt: this.finishedAt,
      ok: this.ok,
      cancelled: this.cancelled,
      phase: this.phase,
      current: this.current,
      total: this.total,
      message: this.message,
      summary: this.summary,
      error: this.error,
    };
  }
}

const _tasks = new Map();

async function persistTasks() {
  const list = Array.from(_tasks.values()).map((t) => t.serialize());
  await chrome.storage.local.set({ tasks: list });
}

function broadcastTaskUpdate(task) {
  try {
    chrome.runtime.sendMessage({ action: 'task_update', task: task.serialize() }, () => {
      void chrome.runtime.lastError;
    });
  } catch { /* ignore */ }
}

function broadcastTaskRemove(taskId) {
  try {
    chrome.runtime.sendMessage({ action: 'task_remove', taskId }, () => {
      void chrome.runtime.lastError;
    });
  } catch { /* ignore */ }
}

async function createTask(label, { notebookId, notebookTitle, kind, customPrompt }) {
  const task = new Task({ label, notebookId, notebookTitle, kind, customPrompt });
  _tasks.set(task.id, task);
  await persistTasks();
  broadcastTaskUpdate(task);
  return task;
}

async function finishTask(task, { ok, summary, error, cancelled = false }) {
  task.finishedAt = Date.now();
  task.ok = ok;
  task.cancelled = cancelled;
  task.phase = 'done';
  task.summary = summary || (cancelled ? '已取消' : (ok ? '完成' : '失敗'));
  task.error = error || null;
  await persistTasks();
  broadcastTaskUpdate(task);

  // done 後保留 30 分鐘給 popup 查看，再自動移除
  setTimeout(async () => {
    if (_tasks.has(task.id) && task.phase === 'done') {
      _tasks.delete(task.id);
      await persistTasks();
      broadcastTaskRemove(task.id);
    }
  }, DONE_TASK_TTL_MS);
}

async function getNotebookTitle(notebookId) {
  if (!notebookId) return '';
  const { cachedNotebooks_v2 } = await chrome.storage.local.get('cachedNotebooks_v2');
  if (Array.isArray(cachedNotebooks_v2)) {
    const found = cachedNotebooks_v2.find((n) => n.id === notebookId);
    if (found) return found.title;
  }
  return notebookId.slice(0, 8) + '…';
}

// ── Service Worker keepalive ───────────────────────────────────────────

let _keepaliveCount = 0;

async function startKeepalive() {
  _keepaliveCount += 1;
  if (_keepaliveCount === 1) {
    await chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.4 });
  }
}

async function stopKeepalive() {
  _keepaliveCount = Math.max(0, _keepaliveCount - 1);
  if (_keepaliveCount === 0) {
    await chrome.alarms.clear(KEEPALIVE_ALARM);
  }
}

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === KEEPALIVE_ALARM) return;
  if (a.name === AUTO_YT_ALARM) {
    runAuto(['news', 'yt'], 'alarm').catch(() => { /* runAuto 內已自行收尾 */ });
  }
});

async function withKeepalive(fn) {
  await startKeepalive();
  try { return await fn(); } finally { await stopKeepalive(); }
}

// ── SW 重啟時清理 stale tasks ────────────────────────────────────────────
// SW 死亡時所有 in-flight task 都會被中斷，但 chrome.storage 內的 task 紀錄還在。
// 啟動時掃一遍，把還是 active 狀態的全部標成 cancelled，避免 popup 顯示永遠卡住。

(async function recoverStaleTasks() {
  try {
    const { tasks: stored } = await chrome.storage.local.get('tasks');
    if (!Array.isArray(stored) || stored.length === 0) return;
    const cleaned = [];
    for (const s of stored) {
      if (s.phase === 'done') {
        // 還沒過 TTL 就保留
        if (s.finishedAt && Date.now() - s.finishedAt < DONE_TASK_TTL_MS) {
          cleaned.push(s);
        }
      } else {
        cleaned.push({
          ...s,
          phase: 'done',
          cancelled: true,
          ok: false,
          finishedAt: Date.now(),
          summary: '⛔ Extension service worker 重啟，任務中斷',
        });
      }
    }
    await chrome.storage.local.set({ tasks: cleaned });
  } catch { /* ignore */ }
})();

// ── 核心動作 ─────────────────────────────────────────────────────────────

async function importUrlsToTask(task, urls) {
  if (!task.notebookId) throw new Error('未指定 notebook');
  if (!urls || urls.length === 0) throw new Error('沒有可匯入的 URL');

  const client = new NotebookLMClient();
  await client.init(task.signal);

  const results = { total: urls.length, succeeded: 0, failed: 0, errors: [] };
  let nextIndex = 0;
  let completed = 0;

  async function worker() {
    while (true) {
      if (task.isCancelled()) return;
      const i = nextIndex++;
      if (i >= urls.length) return;
      const url = urls[i];
      const pdf = isPdfUrl(url);
      const timeoutMs = pdf ? PDF_TIMEOUT_MS : PER_URL_TIMEOUT_MS;
      try {
        await withTimeout(
          client.addUrlSource(task.notebookId, url, task.signal),
          timeoutMs,
          url.slice(0, 40),
        );
        results.succeeded += 1;
      } catch (e) {
        if (isCancelError(e)) return;
        results.failed += 1;
        results.errors.push({ url, message: String(e?.message || e) });
      }
      completed += 1;
      const urlLabel = url.slice(0, 60) + (url.length > 60 ? '…' : '');
      await task.setState({
        phase: 'import',
        current: completed,
        total: urls.length,
        message: `📥 匯入 ${completed}/${urls.length}（並行 ${IMPORT_CONCURRENCY}）${pdf ? '📄 PDF ' : ''}：${urlLabel}`,
      });
    }
  }

  const N = Math.min(IMPORT_CONCURRENCY, urls.length);
  await Promise.all(Array.from({ length: N }, () => worker()));
  task.checkCancel();
  return results;
}

async function clearSourcesForTask(task) {
  if (!task.notebookId) throw new Error('未指定 notebook');

  const client = new NotebookLMClient();
  await client.init(task.signal);

  await task.setState({ phase: 'clear', current: 0, total: 0, message: '🗑 列出 sources…' });
  const sources = await client.listSources(task.notebookId, task.signal);
  const targets = sources.filter((s) => !(s.title || '').startsWith(SKILL_PREFIX));
  const skipped = sources.length - targets.length;

  const results = { total: targets.length, deleted: 0, failed: 0, skipped, errors: [] };
  let nextIndex = 0;
  let completed = 0;

  async function worker() {
    while (true) {
      if (task.isCancelled()) return;
      const i = nextIndex++;
      if (i >= targets.length) return;
      const s = targets[i];
      try {
        await withTimeout(
          client.deleteSource(task.notebookId, s.id, task.signal),
          PER_URL_TIMEOUT_MS,
          s.id,
        );
        results.deleted += 1;
      } catch (e) {
        if (isCancelError(e)) return;
        results.failed += 1;
        results.errors.push({ id: s.id, title: s.title, message: String(e?.message || e) });
      }
      completed += 1;
      await task.setState({
        phase: 'clear',
        current: completed,
        total: targets.length,
        message: `🗑 刪除 ${completed}/${targets.length}（並行 ${CLEAR_CONCURRENCY}）：${(s.title || s.id).slice(0, 60)}`,
      });
    }
  }

  const N = Math.min(CLEAR_CONCURRENCY, targets.length);
  await Promise.all(Array.from({ length: N }, () => worker()));
  task.checkCancel();
  return results;
}

async function generateAndPushForTask(task) {
  if (!task.notebookId) throw new Error('未指定 notebook');
  const settings = await getSettings();

  const client = new NotebookLMClient();
  await client.init(task.signal);

  await task.setState({ phase: 'generate', current: 0, total: 0, message: '🧠 送出產生任務…' });
  const prompt = task.customPrompt || pickPrompt(settings, task.kind);
  const { artifactId } = await client.generateReport(task.notebookId, prompt, 'zh-TW', task.signal);

  const GENERATE_TIMEOUT_MS = 600_000;
  const generateStartedAt = Date.now();
  await client.waitForCompletion(task.notebookId, artifactId, {
    timeout: GENERATE_TIMEOUT_MS,
    signal: task.signal,
    onTick: async (statusCode) => {
      task.checkCancel();
      const elapsed = Math.round((Date.now() - generateStartedAt) / 1000);
      const statusLabel = statusCode === 1 ? '生成中'
        : statusCode === 2 ? '佇列中'
        : statusCode === 3 ? '已完成'
        : statusCode === 4 ? '失敗'
        : `狀態 ${statusCode}`;
      await task.setState({
        phase: 'generate',
        current: elapsed,
        total: GENERATE_TIMEOUT_MS / 1000,
        message: `🧠 ${statusLabel}（已等候 ${elapsed}s / 上限 ${GENERATE_TIMEOUT_MS / 1000}s）`,
      });
    },
  });

  await task.setState({ phase: 'download', message: '⬇ 下載報告 markdown…' });
  const markdown = await client.downloadReport(task.notebookId, artifactId, task.signal);

  const sources = await client.listSources(task.notebookId, task.signal);
  const sourceTitles = sources
    .filter((s) => !(s.title || '').startsWith(SKILL_PREFIX))
    .map((s) => s.title)
    .filter(Boolean);
  const sourceTitleField = sourceTitles.length > 0
    ? `${sourceTitles.length} 篇 sources：${sourceTitles.slice(0, 3).join(' / ')}${sourceTitles.length > 3 ? ' …' : ''}`
    : 'manual generation';

  let pushed = false;
  let pushError = null;
  let vmUrl = null;
  // 兩種來源都會跳過推送：(1) options 內全域 skipVmPush 勾選、(2) popup 的「🚫 不推送」chip
  const shouldSkipPush = settings.skipVmPush || task.kind === 'none';
  const skipReason = task.kind === 'none' ? '🚫 此次選擇「不推送」' : '⏭ 跳過 VM 推送（純本機模式）';

  if (shouldSkipPush) {
    await task.setState({ phase: 'push', message: skipReason });
  } else {
    vmUrl = `${settings.vmBaseUrl}/api/radar/extension-report`;
    await task.setState({ phase: 'push', message: `📤 推送至 VM：${vmUrl}` });
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (settings.apiToken) headers['X-API-Key'] = settings.apiToken;
      const resp = await withTimeout(fetch(vmUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          content: markdown,
          generated_at: new Date().toISOString(),
          source_title: sourceTitleField,
          notebook_kind: task.kind,
        }),
        signal: task.signal,
      }), 30_000, 'VM push');
      pushed = resp.ok;
      if (!pushed) {
        let hint = '';
        if (resp.status === 401) {
          hint = settings.apiToken
            ? '（未授權 — VM 上這把 API Key 可能已撤銷或失效；請到「⚙ 設定」更新，或選「🚫 不推送」跳過）'
            : '（未授權 — 你還沒填 VM API Key；請到「⚙ 設定」貼一把 sk_ 開頭的 service key，或選「🚫 不推送」跳過）';
        } else if (resp.status === 403) {
          hint = '（無權限 — 此 API Key 角色不足，extension report 需要 admin 等級的 service key）';
        } else if (resp.status === 404) {
          hint = `（找不到端點 — 確認 VM URL 是否正確：${settings.vmBaseUrl}）`;
        } else if (resp.status >= 500) {
          hint = '（VM 端錯誤，可能 backend 沒啟動或正在重啟）';
        }
        pushError = `HTTP ${resp.status}${hint}`;
      }
    } catch (e) {
      pushError = String(e?.message || e);
    }
  }

  return {
    artifactId,
    contentLength: markdown.length,
    contentPreview: markdown.slice(0, 200),
    pushed,
    pushError,
    skipped: shouldSkipPush,
    skipReason: shouldSkipPush ? skipReason : null,
    vmUrl,
  };
}

async function runCombinedForTask(task, urls) {
  await task.setState({ phase: 'combined-start', message: `🚀 一鍵流程：${urls.length} 個 URL，將依序執行 清空 → 匯入 → 分析` });

  task.checkCancel();
  const clearResult = await clearSourcesForTask(task);
  await task.setState({ phase: 'between', message: `✓ 清空完成（${clearResult.deleted}/${clearResult.total}），下一步：匯入 ${urls.length} 個 URL` });

  task.checkCancel();
  const importResult = await importUrlsToTask(task, urls);
  await task.setState({ phase: 'between', message: `✓ 匯入完成（${importResult.succeeded}/${importResult.total}），下一步：產生分析報告（最久 10 分鐘）` });

  task.checkCancel();
  const generateResult = await generateAndPushForTask(task);
  return { clear: clearResult, import: importResult, generate: generateResult };
}

// ── 桌面通知 ────────────────────────────────────────────────────────────

let _notifyCounter = 0;

function notify(title, message, kind = 'basic') {
  _notifyCounter += 1;
  const id = `nlm-helper-${Date.now()}-${_notifyCounter}`;
  const blankPng = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII=';
  try {
    chrome.notifications.create(id, {
      type: 'basic',
      iconUrl: blankPng,
      title,
      message,
      priority: kind === 'err' ? 2 : 1,
    }, () => { void chrome.runtime.lastError; });
  } catch { /* ignore */ }
}

function fmtCombined(r) {
  return [
    `🗑 清空：${r.clear.deleted}/${r.clear.total}`,
    `📥 匯入：${r.import.succeeded}/${r.import.total}`,
    `🧠 分析：${r.generate.contentLength}字${r.generate.skipped ? '（未推送）' : (r.generate.pushed ? '，已推送' : `，⚠ 推送失敗：${r.generate.pushError || ''}`)}`,
  ].join('｜');
}

// ── Task 啟動 helpers（給 message handlers 用）─────────────────────────
// 共通模式：建立 task → 立刻 sendResponse 回 taskId → 背景非同步跑核心動作 →
// finishTask 寫入結果 + 廣播。Popup 不等動作完成，靠 task_update 訊息更新 UI。

function runTaskInBackground(task, coreFn, onSuccess, errorTitle) {
  // 不 await — 讓 caller 立即 sendResponse，task 在背景跑
  (async () => {
    try {
      const data = await withKeepalive(() => coreFn());
      const { ok, summary } = onSuccess(data);
      await finishTask(task, { ok, summary });
      notify(
        ok ? `✅ ${task.label}完成` : `⚠ ${task.label}有失敗`,
        `${task.notebookTitle} · ${summary}`,
        ok ? 'basic' : 'err',
      );
    } catch (e) {
      if (isCancelError(e)) {
        await finishTask(task, { ok: false, cancelled: true, summary: `⛔ ${task.label}已取消` });
        notify('⛔ 已取消', `${task.notebookTitle} · ${task.label}已取消`, 'basic');
      } else {
        const errMsg = String(e?.message || e);
        await finishTask(task, { ok: false, error: errMsg, summary: `❌ ${errMsg}` });
        notify(errorTitle, `${task.notebookTitle} · ${errMsg.slice(0, 150)}`, 'err');
      }
    }
  })();
}

// ── 定時自動分析（新聞 + YT）─────────────────────────────────────────────
// 用「活著的瀏覽器 session」定期跑：抓 VM 新內容 → 清空+匯入+產報告 → 推回系統。
// 完全不依賴 notebooklm-py 的無頭 cookie（會一直過期），跟使用者手動點 popup 同一條路。
// 兩種 kind 共用同一排程；每次 alarm 依序跑啟用的 kind（news 先、yt 後），避免並發打爆 NLM。

let _autoBusy = false;

// 每個 kind 的抓取邏輯：回傳 [{ key, url, title }]（key 用於本機去重）
const AUTO_FETCHERS = {
  news: async (settings) => {
    const headers = {};
    if (settings.apiToken) headers['X-API-Key'] = settings.apiToken;
    const url = `${settings.vmBaseUrl}/api/news/articles?limit=60`;
    const resp = await withTimeout(fetch(url, { headers }), 30_000, 'fetch news');
    if (!resp.ok) throw new Error(`抓新聞失敗 HTTP ${resp.status}`);
    const data = await resp.json();
    const arts = Array.isArray(data) ? data : (data.articles || []);
    return arts
      .map((a) => ({ key: a.source_url, url: a.source_url, title: a.title }))
      .filter((x) => x.url);
  },
  yt: async (settings) => {
    const headers = {};
    if (settings.apiToken) headers['X-API-Key'] = settings.apiToken;
    const url = `${settings.vmBaseUrl}/api/youtube/videos?new_only=true&limit=50`;
    const resp = await withTimeout(fetch(url, { headers }), 30_000, 'fetch videos');
    if (!resp.ok) throw new Error(`抓影片失敗 HTTP ${resp.status}`);
    const data = await resp.json();
    const videos = Array.isArray(data) ? data : [];
    return videos
      .map((v) => ({ key: v.video_id || v.youtube_id || String(v.id || ''), url: v.url, title: v.title }))
      .filter((x) => x.url && x.key);
  },
};

const AUTO_KIND_LABEL = { news: '新聞', yt: 'YouTube' };

// 每個 kind 的 storage key 名稱（保持向後相容：yt 沿用既有 autoYt* 名稱）
function autoKeys(kind) {
  if (kind === 'yt') {
    return {
      enabled: 'autoYtEnabled', notebookId: 'autoYtNotebookId', notebookTitle: 'autoYtNotebookTitle',
      analyzed: 'autoYtAnalyzedIds', lastRun: 'autoYtLastRun', lastResult: 'autoYtLastResult',
    };
  }
  return {
    enabled: 'autoNewsEnabled', notebookId: 'autoNewsNotebookId', notebookTitle: 'autoNewsNotebookTitle',
    analyzed: 'autoNewsAnalyzedKeys', lastRun: 'autoNewsLastRun', lastResult: 'autoNewsLastResult',
  };
}

async function getAutoKindConfig(kind) {
  const k = autoKeys(kind);
  const data = await chrome.storage.local.get([k.enabled, k.notebookId, k.notebookTitle, k.analyzed, k.lastRun, k.lastResult]);
  return {
    enabled: !!data[k.enabled],
    notebookId: data[k.notebookId] || '',
    notebookTitle: data[k.notebookTitle] || '',
    analyzed: Array.isArray(data[k.analyzed]) ? data[k.analyzed] : [],
    lastRun: data[k.lastRun] || null,
    lastResult: data[k.lastResult] || null,
  };
}

async function getAutoIntervalHours() {
  // 新 key autoIntervalHours；向後相容舊的 autoYtIntervalHours
  const { autoIntervalHours, autoYtIntervalHours } = await chrome.storage.local.get(['autoIntervalHours', 'autoYtIntervalHours']);
  return Number(autoIntervalHours) || Number(autoYtIntervalHours) || 3;
}

async function setupAutoAlarm() {
  const news = await getAutoKindConfig('news');
  const yt = await getAutoKindConfig('yt');
  await chrome.alarms.clear(AUTO_YT_ALARM);
  if (!news.enabled && !yt.enabled) return;
  const hours = await getAutoIntervalHours();
  // 下限 30 分鐘，避免設太短狂打 NLM / VM
  const minutes = Math.max(30, Math.round(hours * 60));
  await chrome.alarms.create(AUTO_YT_ALARM, { periodInMinutes: minutes, delayInMinutes: 1 });
}

// 單一 kind 的執行（不含 busy 鎖，鎖由 runAuto 持有）
async function _runAutoOne(kind, trigger) {
  const label = AUTO_KIND_LABEL[kind];
  const k = autoKeys(kind);
  const cfg = await getAutoKindConfig(kind);
  if (!cfg.enabled && trigger === 'alarm') return { ran: false, reason: 'disabled' };
  if (!cfg.enabled && trigger === 'manual') return { ran: false, reason: 'disabled' };
  if (!cfg.notebookId) {
    if (trigger === 'manual') notify(`⚠ 自動${label}分析`, '尚未在設定頁選擇要用的 notebook', 'err');
    return { ran: false, reason: 'no-notebook' };
  }

  const settings = await getSettings();
  let items;
  try {
    items = await AUTO_FETCHERS[kind](settings);
  } catch (e) {
    await chrome.storage.local.set({ [k.lastRun]: Date.now(), [k.lastResult]: `❌ ${e.message}` });
    if (trigger === 'manual') notify(`❌ 自動${label}分析`, String(e.message), 'err');
    return { ran: false, reason: 'fetch-failed', summary: String(e.message) };
  }

  const analyzed = new Set(cfg.analyzed);
  const fresh = items.filter((it) => it.key && !analyzed.has(it.key));

  if (fresh.length === 0) {
    await chrome.storage.local.set({ [k.lastRun]: Date.now(), [k.lastResult]: '無新內容' });
    if (trigger === 'manual') notify(`✓ 自動${label}分析`, `目前沒有未分析的新${label}`, 'basic');
    return { ran: false, reason: 'no-new', summary: '無新內容' };
  }

  const urls = fresh.map((it) => it.url);
  const keys = fresh.map((it) => it.key);
  const notebookTitle = cfg.notebookTitle || await getNotebookTitle(cfg.notebookId);

  const task = await createTask(`⏰ 自動${label}分析（${fresh.length} 篇）`, {
    notebookId: cfg.notebookId,
    notebookTitle,
    kind,
  });

  try {
    const data = await withKeepalive(() => runCombinedForTask(task, urls));
    const generateOk = data.generate.skipped || data.generate.pushed;
    const summary = fmtCombined(data);
    await finishTask(task, { ok: generateOk, summary });
    notify(
      generateOk ? `✅ 自動${label}分析完成` : `⚠ 自動${label}分析有問題`,
      `${notebookTitle} · ${summary}`,
      generateOk ? 'basic' : 'err',
    );
    // 推送成功（或純本機模式跳過）才記錄已分析，避免推送失敗時漏掉、下輪重試
    if (generateOk) {
      const merged = [...cfg.analyzed, ...keys].slice(-AUTO_YT_MAX_ANALYZED_IDS);
      await chrome.storage.local.set({ [k.analyzed]: merged });
    }
    await chrome.storage.local.set({ [k.lastRun]: Date.now(), [k.lastResult]: summary });
    return { ran: true, summary };
  } catch (e) {
    if (isCancelError(e)) {
      await finishTask(task, { ok: false, cancelled: true, summary: '⛔ 已取消' });
      await chrome.storage.local.set({ [k.lastRun]: Date.now(), [k.lastResult]: '⛔ 已取消' });
      return { ran: false, reason: 'cancelled' };
    }
    const errMsg = String(e?.message || e);
    await finishTask(task, { ok: false, error: errMsg, summary: `❌ ${errMsg}` });
    await chrome.storage.local.set({ [k.lastRun]: Date.now(), [k.lastResult]: `❌ ${errMsg}` });
    notify(`❌ 自動${label}分析失敗`, `${notebookTitle} · ${errMsg.slice(0, 150)}`, 'err');
    return { ran: false, reason: 'error', summary: errMsg };
  }
}

// 依序跑指定 kinds（news 先、yt 後）；單一 busy 鎖避免並發
async function runAuto(kinds, trigger = 'alarm') {
  if (_autoBusy) return { busy: true };
  _autoBusy = true;
  try {
    const results = {};
    for (const kind of kinds) {
      results[kind] = await _runAutoOne(kind, trigger);
    }
    return results;
  } finally {
    _autoBusy = false;
  }
}

// 啟動時 + 設定變動時建立 / 更新排程
setupAutoAlarm().catch(() => { /* ignore */ });
chrome.runtime.onInstalled.addListener(() => { setupAutoAlarm().catch(() => {}); });
chrome.runtime.onStartup?.addListener?.(() => { setupAutoAlarm().catch(() => {}); });
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if ('autoNewsEnabled' in changes || 'autoYtEnabled' in changes
      || 'autoIntervalHours' in changes || 'autoYtIntervalHours' in changes) {
    setupAutoAlarm().catch(() => {});
  }
});

// ── Message router ─────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg?.action === 'extract_urls_from_text') {
        sendResponse({ ok: true, data: extractUrlsFromText(msg.text || '') });
        return;
      }
      if (msg?.action === 'get_settings') {
        sendResponse({ ok: true, data: await getSettings() });
        return;
      }

      // ── Task 管理 ──────────────────────────────────────────────────

      if (msg?.action === 'list_tasks') {
        const tasks = Array.from(_tasks.values()).map((t) => t.serialize());
        sendResponse({ ok: true, data: tasks });
        return;
      }

      if (msg?.action === 'cancel_task') {
        const task = _tasks.get(msg.taskId);
        if (task) task.requestCancel();
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === 'cancel_all_tasks') {
        let count = 0;
        for (const task of _tasks.values()) {
          if (task.phase !== 'done') { task.requestCancel(); count += 1; }
        }
        sendResponse({ ok: true, count });
        return;
      }

      if (msg?.action === 'dismiss_task') {
        // 使用者手動把 done task 從清單移除
        const task = _tasks.get(msg.taskId);
        if (task && task.phase === 'done') {
          _tasks.delete(msg.taskId);
          await persistTasks();
          broadcastTaskRemove(msg.taskId);
        }
        sendResponse({ ok: true });
        return;
      }

      // ── Notebook 管理 ─────────────────────────────────────────────

      // ── 定時自動分析（新聞 + YT）──────────────────────────────────
      if (msg?.action === 'get_auto_status') {
        const news = await getAutoKindConfig('news');
        const yt = await getAutoKindConfig('yt');
        sendResponse({ ok: true, data: {
          intervalHours: await getAutoIntervalHours(),
          running: _autoBusy,
          news: {
            enabled: news.enabled, notebookId: news.notebookId, notebookTitle: news.notebookTitle,
            lastRun: news.lastRun, lastResult: news.lastResult, analyzedCount: news.analyzed.length,
          },
          yt: {
            enabled: yt.enabled, notebookId: yt.notebookId, notebookTitle: yt.notebookTitle,
            lastRun: yt.lastRun, lastResult: yt.lastResult, analyzedCount: yt.analyzed.length,
          },
        } });
        return;
      }

      if (msg?.action === 'run_auto_now') {
        // 立即手動觸發一次（不 await，背景跑；立刻回應）。msg.kind 指定單一 kind，否則跑全部啟用的
        sendResponse({ ok: true });
        const kinds = (msg.kind === 'news' || msg.kind === 'yt') ? [msg.kind] : ['news', 'yt'];
        runAuto(kinds, 'manual').catch(() => {});
        return;
      }

      if (msg?.action === 'reset_auto_dedup') {
        const k = autoKeys(msg.kind === 'news' ? 'news' : 'yt');
        await chrome.storage.local.set({ [k.analyzed]: [] });
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === 'list_notebooks') {
        try {
          const client = new NotebookLMClient();
          await client.init();
          const notebooks = await client.listNotebooks();
          sendResponse({ ok: true, data: notebooks });
        } catch (e) {
          sendResponse({ ok: false, error: String(e?.message || e) });
        }
        return;
      }

      if (msg?.action === 'open_notebook') {
        if (!msg.notebookId) {
          sendResponse({ ok: false, error: '未選擇 notebook' });
          return;
        }
        await chrome.tabs.create({ url: `https://notebooklm.google.com/notebook/${msg.notebookId}` });
        sendResponse({ ok: true });
        return;
      }

      if (msg?.action === 'create_notebook') {
        try {
          const title = (msg.title || '').trim() || `新筆記本 ${new Date().toLocaleString('zh-TW', { hour12: false })}`;
          const client = new NotebookLMClient();
          await client.init();
          const nb = await client.createNotebook(title);
          sendResponse({ ok: true, data: nb });
        } catch (e) {
          sendResponse({ ok: false, error: String(e?.message || e) });
        }
        return;
      }

      // ── 動作（建 task → 立即回 taskId → 背景跑）────────────────────

      if (msg?.action === 'import_urls') {
        const notebookTitle = await getNotebookTitle(msg.notebookId);
        const label = (msg.urls && msg.urls.length === 1) ? '匯入頁面' : '匯入剪貼簿 URL';
        const task = await createTask(label, {
          notebookId: msg.notebookId,
          notebookTitle,
          kind: null,
        });
        sendResponse({ ok: true, taskId: task.id });
        runTaskInBackground(
          task,
          () => importUrlsToTask(task, msg.urls),
          (data) => {
            const ok = data.succeeded > 0;
            const summary = `${data.succeeded}/${data.total} 成功${data.failed ? `、${data.failed} 失敗${ok ? '（含警告）' : ''}` : ''}`;
            return { ok, summary };
          },
          '❌ 匯入失敗',
        );
        return;
      }

      if (msg?.action === 'clear_sources') {
        const notebookTitle = await getNotebookTitle(msg.notebookId);
        const task = await createTask('清空 sources', {
          notebookId: msg.notebookId,
          notebookTitle,
          kind: null,
        });
        sendResponse({ ok: true, taskId: task.id });
        runTaskInBackground(
          task,
          () => clearSourcesForTask(task),
          (data) => ({
            ok: data.failed === 0,
            summary: `刪除 ${data.deleted}/${data.total}（保留 [SKILL] ${data.skipped}）`,
          }),
          '❌ 清空失敗',
        );
        return;
      }

      if (msg?.action === 'generate_report') {
        const notebookTitle = await getNotebookTitle(msg.notebookId);
        const task = await createTask('產生分析報告', {
          notebookId: msg.notebookId,
          notebookTitle,
          kind: msg.kind,
          customPrompt: msg.customPrompt || null,
        });
        sendResponse({ ok: true, taskId: task.id });
        runTaskInBackground(
          task,
          () => generateAndPushForTask(task),
          (data) => {
            const ok = data.skipped || data.pushed;
            const summary = data.skipped
              ? `${data.contentLength} 字（未推送）`
              : (data.pushed ? `${data.contentLength} 字，已推送 VM` : `${data.contentLength} 字，⚠ 推送失敗：${data.pushError}`);
            return { ok, summary };
          },
          '❌ 報告失敗',
        );
        return;
      }

      if (msg?.action === 'run_combined') {
        const notebookTitle = await getNotebookTitle(msg.notebookId);
        const task = await createTask('一鍵 清空→匯入→分析', {
          notebookId: msg.notebookId,
          notebookTitle,
          kind: msg.kind,
          customPrompt: msg.customPrompt || null,
        });
        sendResponse({ ok: true, taskId: task.id });
        runTaskInBackground(
          task,
          () => runCombinedForTask(task, msg.urls),
          (data) => {
            const generateOk = data.generate.skipped || data.generate.pushed;
            const hasWarning = data.import.failed > 0 || data.clear.failed > 0;
            const summary = hasWarning && generateOk
              ? `${fmtCombined(data)}（含警告）`
              : fmtCombined(data);
            return { ok: generateOk, summary };
          },
          '❌ 一鍵流程失敗',
        );
        return;
      }

      sendResponse({ ok: false, error: `未知的 action: ${msg?.action}` });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;
});
