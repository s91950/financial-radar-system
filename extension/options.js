const TEXT_FIELDS = ['vmBaseUrl', 'apiToken', 'newsPrompt', 'ytPrompt', 'nonePrompt'];
const BOOL_FIELDS = ['skipVmPush'];

function bgSend(msg) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (chrome.runtime.lastError) { resolve({ ok: false, error: chrome.runtime.lastError.message }); return; }
        resolve(resp || { ok: false, error: '無回應' });
      });
    } catch (e) {
      resolve({ ok: false, error: String(e?.message || e) });
    }
  });
}

async function load() {
  const data = await chrome.storage.local.get([
    ...TEXT_FIELDS, ...BOOL_FIELDS,
    'autoIntervalHours', 'autoYtIntervalHours',
    'autoNewsEnabled', 'autoNewsNotebookId',
    'autoYtEnabled', 'autoYtNotebookId',
  ]);
  for (const f of TEXT_FIELDS) {
    const el = document.getElementById(f);
    if (el) el.value = data[f] || '';
  }
  for (const f of BOOL_FIELDS) {
    const el = document.getElementById(f);
    if (el) el.checked = !!data[f];
  }
  if (!document.getElementById('vmBaseUrl').value) {
    document.getElementById('vmBaseUrl').value = 'http://35.231.159.224';
  }

  // 提示詞：帶出目前「實際使用」的內容（含內建預設）讓使用者看得到、可編輯
  const sResp = await bgSend({ action: 'get_settings' });
  if (sResp.ok && sResp.data) {
    if (!data.newsPrompt) document.getElementById('newsPrompt').value = sResp.data.newsPrompt || '';
    if (!data.ytPrompt) document.getElementById('ytPrompt').value = sResp.data.ytPrompt || '';
    // nonePrompt 預設空白 → 維持空白
  }

  // 自動分析設定
  document.getElementById('autoIntervalHours').value = data.autoIntervalHours || data.autoYtIntervalHours || 3;
  document.getElementById('autoNewsEnabled').checked = !!data.autoNewsEnabled;
  document.getElementById('autoYtEnabled').checked = !!data.autoYtEnabled;
  await loadNotebooks({ news: data.autoNewsNotebookId || '', yt: data.autoYtNotebookId || '' });
  refreshAutoStatus();
}

// 用快取先填、背景再 refresh，避免每次開設定頁等 1-2 秒。同時填新聞 + YT 兩個下拉
async function loadNotebooks(selected) {
  const selNews = document.getElementById('autoNewsNotebookId');
  const selYt = document.getElementById('autoYtNotebookId');
  const { cachedNotebooks_v2 } = await chrome.storage.local.get('cachedNotebooks_v2');
  const render = (list) => {
    for (const [sel, selId] of [[selNews, selected.news], [selYt, selected.yt]]) {
      sel.innerHTML = '<option value="">— 請選擇 notebook —</option>';
      for (const nb of list) {
        const opt = document.createElement('option');
        opt.value = nb.id;
        opt.textContent = nb.title || nb.id.slice(0, 8);
        if (nb.id === selId) opt.selected = true;
        sel.appendChild(opt);
      }
    }
  };
  if (Array.isArray(cachedNotebooks_v2) && cachedNotebooks_v2.length) render(cachedNotebooks_v2);

  const resp = await bgSend({ action: 'list_notebooks' });
  if (resp.ok && Array.isArray(resp.data)) {
    render(resp.data);
    await chrome.storage.local.set({ cachedNotebooks_v2: resp.data });
  } else if (!Array.isArray(cachedNotebooks_v2) || !cachedNotebooks_v2.length) {
    const msg = '<option value="">— 無法載入（請先在分頁登入 NotebookLM）—</option>';
    selNews.innerHTML = msg;
    selYt.innerHTML = msg;
  }
}

function fmtKindStatus(label, d) {
  if (!d) return '';
  const last = d.lastRun ? new Date(d.lastRun).toLocaleString('zh-TW', { hour12: false }) : '尚未執行';
  return `${label}：${d.enabled ? '✅ 啟用' : '⏸ 停用'} · 上次 ${last}${d.lastResult ? ` · ${d.lastResult}` : ''} · 去重 ${d.analyzedCount}`;
}

async function refreshAutoStatus() {
  const el = document.getElementById('autoStatus');
  const resp = await bgSend({ action: 'get_auto_status' });
  if (!resp.ok) { el.textContent = '狀態：無法取得'; return; }
  const d = resp.data;
  el.innerHTML = `排程間隔：每 ${d.intervalHours} 小時${d.running ? ' · 🔄 執行中' : ''}`
    + `<br>${fmtKindStatus('📰 新聞', d.news)}`
    + `<br>${fmtKindStatus('📺 YT', d.yt)}`;
}

async function save() {
  const out = {};
  for (const f of TEXT_FIELDS) {
    const el = document.getElementById(f);
    out[f] = (el?.value || '').trim();
  }
  for (const f of BOOL_FIELDS) {
    const el = document.getElementById(f);
    out[f] = !!el?.checked;
  }
  if (out.vmBaseUrl) out.vmBaseUrl = out.vmBaseUrl.replace(/\/$/, '');

  // 自動分析設定
  out.autoIntervalHours = Math.max(0.5, Number(document.getElementById('autoIntervalHours').value) || 3);
  out.autoNewsEnabled = document.getElementById('autoNewsEnabled').checked;
  out.autoYtEnabled = document.getElementById('autoYtEnabled').checked;

  const selNews = document.getElementById('autoNewsNotebookId');
  const selYt = document.getElementById('autoYtNotebookId');
  out.autoNewsNotebookId = selNews.value || '';
  out.autoNewsNotebookTitle = selNews.value ? (selNews.options[selNews.selectedIndex]?.textContent || '') : '';
  out.autoYtNotebookId = selYt.value || '';
  out.autoYtNotebookTitle = selYt.value ? (selYt.options[selYt.selectedIndex]?.textContent || '') : '';

  if (out.autoNewsEnabled && !out.autoNewsNotebookId) {
    showStatus('啟用自動新聞分析前，請先選一個新聞 notebook', 'err');
    return;
  }
  if (out.autoYtEnabled && !out.autoYtNotebookId) {
    showStatus('啟用自動 YT 分析前，請先選一個 YT notebook', 'err');
    return;
  }

  await chrome.storage.local.set(out);
  showStatus('已儲存', 'ok');
  refreshAutoStatus();
}

async function resetPrompts() {
  await chrome.storage.local.remove(['newsPrompt', 'ytPrompt', 'nonePrompt']);
  document.getElementById('nonePrompt').value = '';
  // 重新帶出內建預設讓使用者看得到
  const sResp = await bgSend({ action: 'get_settings' });
  if (sResp.ok && sResp.data) {
    document.getElementById('newsPrompt').value = sResp.data.newsPrompt || '';
    document.getElementById('ytPrompt').value = sResp.data.ytPrompt || '';
  }
  showStatus('提示詞已重設為預設（已重新帶出內建模板；不推送恢復空白）', 'ok');
}

function showStatus(msg, kind) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = `status ${kind}`;
  setTimeout(() => { el.className = 'status'; }, 3000);
}

document.getElementById('save').addEventListener('click', save);
document.getElementById('reset').addEventListener('click', resetPrompts);
document.getElementById('refreshNotebooks').addEventListener('click', async () => {
  await loadNotebooks({
    news: document.getElementById('autoNewsNotebookId').value,
    yt: document.getElementById('autoYtNotebookId').value,
  });
  showStatus('notebook 清單已重新載入', 'ok');
});
document.getElementById('runNewsNow').addEventListener('click', async () => {
  showStatus('已觸發新聞分析（背景執行，可開 popup 看任務進度）', 'ok');
  await bgSend({ action: 'run_auto_now', kind: 'news' });
  setTimeout(refreshAutoStatus, 1500);
});
document.getElementById('runYtNow').addEventListener('click', async () => {
  showStatus('已觸發 YT 分析（背景執行，可開 popup 看任務進度）', 'ok');
  await bgSend({ action: 'run_auto_now', kind: 'yt' });
  setTimeout(refreshAutoStatus, 1500);
});
document.getElementById('resetNewsDedup').addEventListener('click', async () => {
  await bgSend({ action: 'reset_auto_dedup', kind: 'news' });
  showStatus('已重置新聞去重紀錄', 'ok');
  refreshAutoStatus();
});
document.getElementById('resetYtDedup').addEventListener('click', async () => {
  await bgSend({ action: 'reset_auto_dedup', kind: 'yt' });
  showStatus('已重置 YT 去重紀錄', 'ok');
  refreshAutoStatus();
});

load();
setInterval(refreshAutoStatus, 5000);
