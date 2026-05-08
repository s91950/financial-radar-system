// Background service worker — 統一處理 NotebookLM API + 推送 VM。
// 重點機制：
//   1. chrome.alarms keepalive：避免 MV3 service worker 在長操作（特別是 waitForCompletion
//      polling 之間的 sleep）被 Chrome idle timeout 殺掉，造成「匯入到一半就停」。
//   2. progress 廣播 + chrome.storage 持久化：每一步驟都更新 lastRun 狀態，popup 重開
//      時可以還原；popup 開著時則透過 runtime.sendMessage 即時刷新。

import { NotebookLMClient, extractUrlsFromText } from './lib/notebooklm.js';

const SKILL_PREFIX = '[SKILL] ';
const KEEPALIVE_ALARM = 'nlm-keepalive';
const PER_URL_TIMEOUT_MS = 30_000;
const INTER_URL_DELAY_MS = 300;

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
    'notebookIdNews', 'notebookIdYt',
    'vmBaseUrl', 'apiToken', 'newsPrompt', 'ytPrompt', 'skipVmPush',
  ]);
  return {
    notebookIdNews: data.notebookIdNews || '',
    notebookIdYt: data.notebookIdYt || '',
    vmBaseUrl: (data.vmBaseUrl || 'http://34.23.154.194').replace(/\/$/, ''),
    apiToken: data.apiToken || '',
    newsPrompt: data.newsPrompt || DEFAULT_NEWS_PROMPT,
    ytPrompt: data.ytPrompt || DEFAULT_YT_PROMPT,
    skipVmPush: !!data.skipVmPush,
  };
}

function pickNotebookId(settings, kind) {
  return kind === 'yt' ? settings.notebookIdYt : settings.notebookIdNews;
}

function pickPrompt(settings, kind) {
  return kind === 'yt' ? settings.ytPrompt : settings.newsPrompt;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function withTimeout(promise, ms, label = '') {
  return Promise.race([
    promise,
    new Promise((_, rej) => setTimeout(() => rej(new Error(`等待超時 ${Math.round(ms / 1000)}s${label ? `（${label}）` : ''}`)), ms)),
  ]);
}

// ── Service Worker keepalive ───────────────────────────────────────────
// MV3 SW 沒有定期事件就會被殺；alarm 觸發會喚醒 SW 阻止它 idle 死亡。
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
  // 純粹喚醒 SW，不需要做任何事
  if (a.name === KEEPALIVE_ALARM) return;
});

async function withKeepalive(fn) {
  await startKeepalive();
  try { return await fn(); } finally { await stopKeepalive(); }
}

// ── Progress 持久化 + 廣播 ──────────────────────────────────────────────
// runState 結構：{ phase, label, current, total, message, startedAt, finishedAt?, ok?, error? }

async function setRunState(patch) {
  const { lastRun = {} } = await chrome.storage.local.get('lastRun');
  const next = { ...lastRun, ...patch };
  await chrome.storage.local.set({ lastRun: next });
  // 廣播給可能正在開著的 popup
  try {
    chrome.runtime.sendMessage({ action: 'progress', state: next }, () => {
      // popup 沒開就會 lastError，吞掉即可
      void chrome.runtime.lastError;
    });
  } catch { /* ignore */ }
  return next;
}

async function clearRunState() {
  await chrome.storage.local.remove('lastRun');
}

async function startRun(label) {
  const startedAt = Date.now();
  await chrome.storage.local.set({
    lastRun: { phase: 'starting', label, current: 0, total: 0, message: '初始化…', startedAt },
  });
  return startedAt;
}

async function finishRun({ ok, summary, error }) {
  await setRunState({
    phase: 'done',
    finishedAt: Date.now(),
    ok,
    message: summary || (ok ? '完成' : '失敗'),
    error: error || null,
  });
}

// ── 三個基本動作 ────────────────────────────────────────────────────────

async function importClipboardUrls({ kind, urls }) {
  const settings = await getSettings();
  const notebookId = pickNotebookId(settings, kind);
  if (!notebookId) throw new Error(`尚未設定 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook ID（請開啟「選項」設定）`);
  if (!urls || urls.length === 0) throw new Error('剪貼簿沒有可匯入的 URL');

  const client = new NotebookLMClient();
  await client.init();

  const results = { total: urls.length, succeeded: 0, failed: 0, errors: [] };
  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    await setRunState({
      phase: 'import',
      current: i + 1,
      total: urls.length,
      message: `📥 匯入 ${i + 1}/${urls.length}：${url.slice(0, 60)}${url.length > 60 ? '…' : ''}`,
    });
    try {
      await withTimeout(
        client.addUrlSource(notebookId, url),
        PER_URL_TIMEOUT_MS,
        url.slice(0, 40),
      );
      results.succeeded += 1;
    } catch (e) {
      results.failed += 1;
      results.errors.push({ url, message: String(e?.message || e) });
    }
    // 避免打 NotebookLM 太密；對大批量很重要
    if (i < urls.length - 1) await sleep(INTER_URL_DELAY_MS);
  }
  return results;
}

async function clearSources({ kind }) {
  const settings = await getSettings();
  const notebookId = pickNotebookId(settings, kind);
  if (!notebookId) throw new Error(`尚未設定 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook ID`);

  const client = new NotebookLMClient();
  await client.init();

  await setRunState({ phase: 'clear', current: 0, total: 0, message: '🗑 列出 sources…' });
  const sources = await client.listSources(notebookId);
  const targets = sources.filter((s) => !(s.title || '').startsWith(SKILL_PREFIX));
  const skipped = sources.length - targets.length;

  const results = { total: targets.length, deleted: 0, failed: 0, skipped, errors: [] };
  for (let i = 0; i < targets.length; i++) {
    const s = targets[i];
    await setRunState({
      phase: 'clear',
      current: i + 1,
      total: targets.length,
      message: `🗑 刪除 ${i + 1}/${targets.length}：${(s.title || s.id).slice(0, 60)}`,
    });
    try {
      await withTimeout(
        client.deleteSource(notebookId, s.id),
        PER_URL_TIMEOUT_MS,
        s.id,
      );
      results.deleted += 1;
    } catch (e) {
      results.failed += 1;
      results.errors.push({ id: s.id, title: s.title, message: String(e?.message || e) });
    }
    if (i < targets.length - 1) await sleep(INTER_URL_DELAY_MS);
  }
  return results;
}

async function generateAndPushReport({ kind }) {
  const settings = await getSettings();
  const notebookId = pickNotebookId(settings, kind);
  if (!notebookId) throw new Error(`尚未設定 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook ID`);

  const client = new NotebookLMClient();
  await client.init();

  await setRunState({ phase: 'generate', current: 0, total: 0, message: '🧠 送出產生任務…' });
  const prompt = pickPrompt(settings, kind);
  const { artifactId } = await client.generateReport(notebookId, prompt, 'zh-TW');

  const GENERATE_TIMEOUT_MS = 600_000;  // 10 分鐘：NLM 在 200+ sources 時可能遠超 5 分鐘
  const startedAt = Date.now();
  await client.waitForCompletion(notebookId, artifactId, {
    timeout: GENERATE_TIMEOUT_MS,
    onTick: async (statusCode) => {
      const elapsed = Math.round((Date.now() - startedAt) / 1000);
      const statusLabel = statusCode === 1 ? '生成中'
        : statusCode === 2 ? '佇列中'
        : statusCode === 3 ? '已完成'
        : statusCode === 4 ? '失敗'
        : `狀態 ${statusCode}`;
      await setRunState({
        phase: 'generate',
        current: elapsed,
        total: GENERATE_TIMEOUT_MS / 1000,
        message: `🧠 ${statusLabel}（已等候 ${elapsed}s / 上限 ${GENERATE_TIMEOUT_MS / 1000}s）`,
      });
    },
  });

  await setRunState({ phase: 'download', message: '⬇ 下載報告 markdown…' });
  const markdown = await client.downloadReport(notebookId, artifactId);

  // 來源列表（排除 [SKILL] 框架檔）
  const sources = await client.listSources(notebookId);
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

  if (settings.skipVmPush) {
    await setRunState({ phase: 'push', message: '⏭ 跳過 VM 推送（純本機模式）' });
  } else {
    vmUrl = `${settings.vmBaseUrl}/api/radar/extension-report`;
    await setRunState({ phase: 'push', message: `📤 推送至 VM：${vmUrl}` });
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
          notebook_kind: kind,
        }),
      }), 30_000, 'VM push');
      pushed = resp.ok;
      if (!pushed) pushError = `HTTP ${resp.status}`;
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
    skipped: !!settings.skipVmPush,
    vmUrl,
  };
}

async function runCombined({ kind, urls }) {
  await setRunState({ phase: 'combined-start', message: `🚀 一鍵流程啟動：${urls.length} 個 URL，將依序執行 清空 → 匯入 → 分析` });

  const clearResult = await clearSources({ kind });
  await setRunState({ phase: 'between', message: `✓ 清空完成（${clearResult.deleted}/${clearResult.total}），下一步：匯入 ${urls.length} 個 URL` });

  const importResult = await importClipboardUrls({ kind, urls });
  await setRunState({ phase: 'between', message: `✓ 匯入完成（${importResult.succeeded}/${importResult.total}），下一步：產生分析報告（最久 5 分鐘）` });

  const generateResult = await generateAndPushReport({ kind });
  return { clear: clearResult, import: importResult, generate: generateResult };
}

// ── 桌面通知 ────────────────────────────────────────────────────────────

let _notifyCounter = 0;

function notify(title, message, kind = 'basic') {
  _notifyCounter += 1;
  const id = `nlm-helper-${Date.now()}-${_notifyCounter}`;
  // type:basic 在 Chrome 上 iconUrl 是必填；用內嵌 1×1 透明 PNG 作 fallback
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
    `🧠 分析：${r.generate.contentLength}字${r.generate.skipped ? '（本機）' : (r.generate.pushed ? '，已推送' : `，⚠ 推送失敗：${r.generate.pushError || ''}`)}`,
  ].join('｜');
}

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
      if (msg?.action === 'get_last_run') {
        const { lastRun } = await chrome.storage.local.get('lastRun');
        sendResponse({ ok: true, data: lastRun || null });
        return;
      }

      if (msg?.action === 'import_urls') {
        await startRun('匯入剪貼簿 URL');
        try {
          const data = await withKeepalive(() => importClipboardUrls({ kind: msg.kind, urls: msg.urls }));
          await finishRun({ ok: data.failed === 0, summary: `匯入 ${data.succeeded}/${data.total} 成功${data.failed ? `、${data.failed} 失敗` : ''}` });
          notify(data.failed === 0 ? '✅ 匯入完成' : '⚠ 匯入有失敗', `${data.succeeded}/${data.total} 成功${data.failed ? `、${data.failed} 失敗` : ''}`, data.failed === 0 ? 'basic' : 'err');
          sendResponse({ ok: true, data });
        } catch (e) {
          await finishRun({ ok: false, error: String(e?.message || e), summary: `❌ ${e?.message || e}` });
          notify('❌ 匯入失敗', String(e?.message || e).slice(0, 200), 'err');
          throw e;
        }
        return;
      }

      if (msg?.action === 'clear_sources') {
        await startRun('清空 sources');
        try {
          const data = await withKeepalive(() => clearSources({ kind: msg.kind }));
          await finishRun({ ok: data.failed === 0, summary: `刪除 ${data.deleted}/${data.total}（保留 [SKILL] ${data.skipped}）` });
          notify(data.failed === 0 ? '✅ 清空完成' : '⚠ 清空有失敗', `刪除 ${data.deleted}/${data.total}（保留 [SKILL] ${data.skipped}）`, data.failed === 0 ? 'basic' : 'err');
          sendResponse({ ok: true, data });
        } catch (e) {
          await finishRun({ ok: false, error: String(e?.message || e), summary: `❌ ${e?.message || e}` });
          notify('❌ 清空失敗', String(e?.message || e).slice(0, 200), 'err');
          throw e;
        }
        return;
      }

      if (msg?.action === 'generate_report') {
        await startRun('產生分析報告');
        try {
          const data = await withKeepalive(() => generateAndPushReport({ kind: msg.kind }));
          const ok = data.skipped || data.pushed;
          const summary = data.skipped
            ? `${data.contentLength} 字（已跳過 VM 推送）`
            : (data.pushed ? `${data.contentLength} 字，已推送 VM` : `${data.contentLength} 字，⚠ 推送失敗：${data.pushError}`);
          await finishRun({ ok, summary });
          notify(ok ? '✅ 報告完成' : '⚠ 報告完成但推送失敗', summary, ok ? 'basic' : 'err');
          sendResponse({ ok: true, data });
        } catch (e) {
          await finishRun({ ok: false, error: String(e?.message || e), summary: `❌ ${e?.message || e}` });
          notify('❌ 報告失敗', String(e?.message || e).slice(0, 200), 'err');
          throw e;
        }
        return;
      }

      if (msg?.action === 'run_combined') {
        await startRun('一鍵 清空 → 匯入 → 分析');
        try {
          const data = await withKeepalive(() => runCombined({ kind: msg.kind, urls: msg.urls }));
          // 成功標準：分析有產出且推送成功（或本機模式跳過推送）就算成功；
          // 匯入 / 清空有少量失敗只當警告，不把整體判為失敗（NLM 偶爾會有個位數 URL 失敗，
          // 但只要分析報告產出來就有價值）。
          const generateOk = data.generate.skipped || data.generate.pushed;
          const hasWarning = data.import.failed > 0 || data.clear.failed > 0;
          const summary = hasWarning && generateOk
            ? `${fmtCombined(data)}（含警告）`
            : fmtCombined(data);
          await finishRun({ ok: generateOk, summary });
          const titleIcon = generateOk ? (hasWarning ? '✅' : '✅') : '❌';
          const titleText = generateOk
            ? (hasWarning ? '一鍵流程完成（含警告）' : '一鍵流程完成')
            : '一鍵流程失敗';
          notify(`${titleIcon} ${titleText}`, summary, generateOk ? 'basic' : 'err');
          sendResponse({ ok: true, data });
        } catch (e) {
          await finishRun({ ok: false, error: String(e?.message || e), summary: `❌ ${e?.message || e}` });
          notify('❌ 一鍵流程失敗', String(e?.message || e).slice(0, 200), 'err');
          throw e;
        }
        return;
      }

      sendResponse({ ok: false, error: `未知的 action: ${msg?.action}` });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;  // 保持 channel 開著等 async sendResponse
});
