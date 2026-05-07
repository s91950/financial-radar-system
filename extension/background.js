// Background service worker — 統一處理 NotebookLM API + 推送到 VM。
// popup 與 content.js 都透過 chrome.runtime.sendMessage 呼叫這裡。

import { NotebookLMClient, extractUrlsFromText } from './lib/notebooklm.js';

const SKILL_PREFIX = '[SKILL] ';

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
    'vmBaseUrl', 'newsPrompt', 'ytPrompt',
  ]);
  return {
    notebookIdNews: data.notebookIdNews || '',
    notebookIdYt: data.notebookIdYt || '',
    vmBaseUrl: (data.vmBaseUrl || 'http://34.23.154.194').replace(/\/$/, ''),
    newsPrompt: data.newsPrompt || DEFAULT_NEWS_PROMPT,
    ytPrompt: data.ytPrompt || DEFAULT_YT_PROMPT,
  };
}

function pickNotebookId(settings, kind) {
  return kind === 'yt' ? settings.notebookIdYt : settings.notebookIdNews;
}

function pickPrompt(settings, kind) {
  return kind === 'yt' ? settings.ytPrompt : settings.newsPrompt;
}

// ── 三大動作 ────────────────────────────────────────────────────────────

async function importClipboardUrls({ kind, urls }) {
  const settings = await getSettings();
  const notebookId = pickNotebookId(settings, kind);
  if (!notebookId) throw new Error(`尚未設定 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook ID（請開啟「選項」設定）`);
  if (!urls || urls.length === 0) throw new Error('剪貼簿沒有可匯入的 URL');

  const client = new NotebookLMClient();
  await client.init();

  const results = { total: urls.length, succeeded: 0, failed: 0, errors: [] };
  for (const url of urls) {
    try {
      await client.addUrlSource(notebookId, url);
      results.succeeded += 1;
    } catch (e) {
      results.failed += 1;
      results.errors.push({ url, message: String(e?.message || e) });
    }
  }
  return results;
}

async function clearSources({ kind }) {
  const settings = await getSettings();
  const notebookId = pickNotebookId(settings, kind);
  if (!notebookId) throw new Error(`尚未設定 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook ID`);

  const client = new NotebookLMClient();
  await client.init();

  const sources = await client.listSources(notebookId);
  const targets = sources.filter((s) => !(s.title || '').startsWith(SKILL_PREFIX));
  const skipped = sources.length - targets.length;

  const results = { total: targets.length, deleted: 0, failed: 0, skipped, errors: [] };
  for (const s of targets) {
    try {
      await client.deleteSource(notebookId, s.id);
      results.deleted += 1;
    } catch (e) {
      results.failed += 1;
      results.errors.push({ id: s.id, title: s.title, message: String(e?.message || e) });
    }
  }
  return results;
}

async function generateAndPushReport({ kind }) {
  const settings = await getSettings();
  const notebookId = pickNotebookId(settings, kind);
  if (!notebookId) throw new Error(`尚未設定 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook ID`);

  const client = new NotebookLMClient();
  await client.init();

  const prompt = pickPrompt(settings, kind);
  const { artifactId } = await client.generateReport(notebookId, prompt, 'zh-TW');
  await client.waitForCompletion(notebookId, artifactId, { timeout: 300_000 });
  const markdown = await client.downloadReport(notebookId, artifactId);

  // 推送到 VM
  const sources = await client.listSources(notebookId);
  const sourceTitles = sources
    .filter((s) => !(s.title || '').startsWith(SKILL_PREFIX))
    .map((s) => s.title)
    .filter(Boolean);
  const sourceTitleField = sourceTitles.length > 0
    ? `${sourceTitles.length} 篇 sources：${sourceTitles.slice(0, 3).join(' / ')}${sourceTitles.length > 3 ? ' …' : ''}`
    : 'manual generation';

  const pushUrl = `${settings.vmBaseUrl}/api/radar/extension-report`;
  const payload = {
    content: markdown,
    generated_at: new Date().toISOString(),
    source_title: sourceTitleField,
    notebook_kind: kind,
  };
  let pushOk = false;
  let pushError = null;
  try {
    const resp = await fetch(pushUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    pushOk = resp.ok;
    if (!pushOk) pushError = `HTTP ${resp.status}`;
  } catch (e) {
    pushError = String(e?.message || e);
  }

  return {
    artifactId,
    contentLength: markdown.length,
    contentPreview: markdown.slice(0, 200),
    pushed: pushOk,
    pushError,
    vmUrl: pushUrl,
  };
}

// ── Message router ─────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg?.action === 'extract_urls_from_text') {
        sendResponse({ ok: true, data: extractUrlsFromText(msg.text || '') });
        return;
      }
      if (msg?.action === 'import_urls') {
        const data = await importClipboardUrls({ kind: msg.kind, urls: msg.urls });
        sendResponse({ ok: true, data });
        return;
      }
      if (msg?.action === 'clear_sources') {
        const data = await clearSources({ kind: msg.kind });
        sendResponse({ ok: true, data });
        return;
      }
      if (msg?.action === 'generate_report') {
        const data = await generateAndPushReport({ kind: msg.kind });
        sendResponse({ ok: true, data });
        return;
      }
      if (msg?.action === 'get_settings') {
        sendResponse({ ok: true, data: await getSettings() });
        return;
      }
      sendResponse({ ok: false, error: `未知的 action: ${msg?.action}` });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();
  return true;  // 保持 channel 開著等 async sendResponse
});
