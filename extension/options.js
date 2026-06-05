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
    'autoYtEnabled', 'autoYtIntervalHours', 'autoYtNotebookId',
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
    document.getElementById('vmBaseUrl').value = 'http://34.23.154.194';
  }
  document.getElementById('autoYtEnabled').checked = !!data.autoYtEnabled;
  document.getElementById('autoYtIntervalHours').value = data.autoYtIntervalHours || 3;
  await loadNotebooks(data.autoYtNotebookId || '');
  refreshAutoStatus();
}

// 用快取先填、背景再 refresh，避免每次開設定頁等 1-2 秒
async function loadNotebooks(selectedId) {
  const sel = document.getElementById('autoYtNotebookId');
  const { cachedNotebooks_v2 } = await chrome.storage.local.get('cachedNotebooks_v2');
  const render = (list) => {
    sel.innerHTML = '<option value="">— 請選擇 notebook —</option>';
    for (const nb of list) {
      const opt = document.createElement('option');
      opt.value = nb.id;
      opt.textContent = nb.title || nb.id.slice(0, 8);
      if (nb.id === selectedId) opt.selected = true;
      sel.appendChild(opt);
    }
  };
  if (Array.isArray(cachedNotebooks_v2) && cachedNotebooks_v2.length) render(cachedNotebooks_v2);

  const resp = await bgSend({ action: 'list_notebooks' });
  if (resp.ok && Array.isArray(resp.data)) {
    render(resp.data);
    await chrome.storage.local.set({ cachedNotebooks_v2: resp.data });
  } else if (!Array.isArray(cachedNotebooks_v2) || !cachedNotebooks_v2.length) {
    sel.innerHTML = '<option value="">— 無法載入（請先在分頁登入 NotebookLM）—</option>';
  }
}

async function refreshAutoStatus() {
  const el = document.getElementById('autoStatus');
  const resp = await bgSend({ action: 'get_auto_yt_status' });
  if (!resp.ok) { el.textContent = '狀態：無法取得'; return; }
  const d = resp.data;
  const last = d.lastRun ? new Date(d.lastRun).toLocaleString('zh-TW', { hour12: false }) : '尚未執行';
  el.innerHTML = `狀態：${d.enabled ? `✅ 已啟用（每 ${d.intervalHours} 小時）` : '⏸ 未啟用'}`
    + `${d.running ? ' · 🔄 執行中' : ''}`
    + `<br>上次執行：${last}${d.lastResult ? ` · ${d.lastResult}` : ''}`
    + `<br>已記錄去重影片數：${d.analyzedCount}`;
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

  // 自動 YT 設定
  out.autoYtEnabled = document.getElementById('autoYtEnabled').checked;
  out.autoYtIntervalHours = Math.max(0.5, Number(document.getElementById('autoYtIntervalHours').value) || 3);
  const sel = document.getElementById('autoYtNotebookId');
  out.autoYtNotebookId = sel.value || '';
  out.autoYtNotebookTitle = sel.value ? (sel.options[sel.selectedIndex]?.textContent || '') : '';

  if (out.autoYtEnabled && !out.autoYtNotebookId) {
    showStatus('啟用自動 YT 分析前，請先選一個 notebook', 'err');
    return;
  }

  await chrome.storage.local.set(out);
  showStatus('已儲存', 'ok');
  refreshAutoStatus();
}

async function resetPrompts() {
  await chrome.storage.local.remove(['newsPrompt', 'ytPrompt', 'nonePrompt']);
  document.getElementById('newsPrompt').value = '';
  document.getElementById('ytPrompt').value = '';
  document.getElementById('nonePrompt').value = '';
  showStatus('提示詞已重設為預設（新聞 / YT 走內建模板；不推送恢復空白）', 'ok');
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
  const sel = document.getElementById('autoYtNotebookId');
  await loadNotebooks(sel.value);
  showStatus('notebook 清單已重新載入', 'ok');
});
document.getElementById('runAutoNow').addEventListener('click', async () => {
  showStatus('已觸發一次自動分析（背景執行，可開 popup 看任務進度）', 'ok');
  await bgSend({ action: 'run_auto_yt_now' });
  setTimeout(refreshAutoStatus, 1500);
});
document.getElementById('resetDedup').addEventListener('click', async () => {
  await bgSend({ action: 'reset_auto_yt_dedup' });
  showStatus('已重置去重紀錄（下次會重新分析目前所有新影片）', 'ok');
  refreshAutoStatus();
});

load();
setInterval(refreshAutoStatus, 5000);
