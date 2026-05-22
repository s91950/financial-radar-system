const TEXT_FIELDS = ['vmBaseUrl', 'apiToken', 'newsPrompt', 'ytPrompt', 'nonePrompt'];
const BOOL_FIELDS = ['skipVmPush'];

async function load() {
  const data = await chrome.storage.local.get([...TEXT_FIELDS, ...BOOL_FIELDS]);
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
  await chrome.storage.local.set(out);
  showStatus('已儲存', 'ok');
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
load();
