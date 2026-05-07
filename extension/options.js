const FIELDS = ['notebookIdNews', 'notebookIdYt', 'vmBaseUrl', 'newsPrompt', 'ytPrompt'];

async function load() {
  const data = await chrome.storage.local.get(FIELDS);
  for (const f of FIELDS) {
    const el = document.getElementById(f);
    if (el) el.value = data[f] || '';
  }
  // VM URL 預設值
  if (!document.getElementById('vmBaseUrl').value) {
    document.getElementById('vmBaseUrl').value = 'http://34.23.154.194';
  }
}

async function save() {
  const out = {};
  for (const f of FIELDS) {
    const el = document.getElementById(f);
    out[f] = (el?.value || '').trim();
  }
  // 規範化 VM URL
  if (out.vmBaseUrl) out.vmBaseUrl = out.vmBaseUrl.replace(/\/$/, '');
  await chrome.storage.local.set(out);
  showStatus('已儲存', 'ok');
}

async function resetPrompts() {
  await chrome.storage.local.remove(['newsPrompt', 'ytPrompt']);
  document.getElementById('newsPrompt').value = '';
  document.getElementById('ytPrompt').value = '';
  showStatus('提示詞已重設為預設', 'ok');
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
