// popup.js — UI binding。實際執行委派給 background.js，狀態全部從 chrome.storage
// + runtime.sendMessage 廣播取得，所以 popup 關了重開也能還原進度。

const $ = (sel) => document.querySelector(sel);
const statusBox = $('#status');
const statusText = $('#status-text');
const statusDetail = $('#status-detail');
const configHint = $('#config-hint');

function setStatus(text, kind = 'run', detail = '') {
  statusBox.classList.remove('ok', 'err', 'run');
  if (kind) statusBox.classList.add(kind);
  statusText.textContent = text;
  statusDetail.textContent = detail || '';
}

function getKind() {
  return document.querySelector('input[name="kind"]:checked')?.value || 'news';
}

async function bgSend(action, payload = {}) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action, ...payload }, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(resp || { ok: false, error: '無回應' });
      }
    });
  });
}

function disableButtons(disabled) {
  ['#btn-import', '#btn-clear', '#btn-generate', '#btn-combined'].forEach((s) => {
    const el = $(s);
    if (el) el.disabled = disabled;
  });
}

async function rememberKind() {
  await chrome.storage.local.set({ lastKind: getKind() });
}

async function restoreKind() {
  const { lastKind } = await chrome.storage.local.get('lastKind');
  if (lastKind) {
    const radio = document.querySelector(`input[name="kind"][value="${lastKind}"]`);
    if (radio) radio.checked = true;
  }
}

async function checkConfig() {
  const resp = await bgSend('get_settings');
  if (!resp.ok) return;
  const s = resp.data;
  const missing = [];
  if (!s.notebookIdNews) missing.push('新聞 notebook ID');
  if (!s.notebookIdYt) missing.push('YouTube notebook ID');
  if (missing.length > 0) {
    configHint.innerHTML = `⚠ 尚未設定：${missing.join('、')} <a href="#" id="open-options-2" class="link">設定</a>`;
    document.getElementById('open-options-2')?.addEventListener('click', openOptions);
  } else {
    const mode = s.skipVmPush ? '本機模式（不推 VM）' : `VM: ${s.vmBaseUrl}`;
    configHint.textContent = mode;
  }
}

function openOptions(e) {
  e?.preventDefault();
  chrome.runtime.openOptionsPage();
}

async function readClipboardUrls() {
  let text = '';
  try {
    text = await navigator.clipboard.readText();
  } catch (e) {
    throw new Error(`無法讀取剪貼簿：${e?.message || e}（首次使用會跳權限提示，請允許）`);
  }
  const ext = await bgSend('extract_urls_from_text', { text });
  if (!ext.ok) throw new Error(ext.error);
  return ext.data;
}

// ── 狀態還原 / 即時刷新 ────────────────────────────────────────────────

const ACTIVE_PHASES = new Set([
  'starting', 'clear', 'import', 'generate', 'download', 'push',
  'combined-start', 'between',
]);

function fmtElapsed(startedAt) {
  if (!startedAt) return '';
  const sec = Math.round((Date.now() - startedAt) / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m${sec % 60}s`;
}

function renderRunState(state) {
  if (!state) {
    setStatus('👋 選擇 notebook 後點按鈕開始', 'run', '');
    disableButtons(false);
    return;
  }

  // 進行中
  if (state.phase && ACTIVE_PHASES.has(state.phase)) {
    const elapsed = fmtElapsed(state.startedAt);
    const head = `[${state.label}] 進行中 · 已 ${elapsed}`;
    let body = state.message || '';
    if (state.total > 0 && state.phase !== 'generate') {
      body = `進度 ${state.current}/${state.total}\n${body}`;
    }
    setStatus(head, 'run', body);
    disableButtons(true);
    return;
  }

  // 已完成
  if (state.phase === 'done') {
    const elapsed = state.finishedAt && state.startedAt
      ? fmtElapsed(state.startedAt).replace(/^/, '耗時 ')
      : '';
    const headIcon = state.ok ? '✅' : '❌';
    setStatus(
      `${headIcon} [${state.label}] ${state.ok ? '完成' : '失敗'}${elapsed ? ` · ${elapsed.replace('已 ', '')}` : ''}`,
      state.ok ? 'ok' : 'err',
      state.message || state.error || '',
    );
    disableButtons(false);
    return;
  }

  // 其他/未知狀態
  setStatus('👋 選擇 notebook 後點按鈕開始', 'run', '');
  disableButtons(false);
}

async function loadInitialRunState() {
  const resp = await bgSend('get_last_run');
  const state = resp.ok ? resp.data : null;
  // 太舊（>30 分鐘）的 done 狀態就不顯示了，避免混淆
  if (state && state.phase === 'done' && state.finishedAt && Date.now() - state.finishedAt > 30 * 60 * 1000) {
    renderRunState(null);
    return;
  }
  renderRunState(state);
}

// 訂閱 progress 廣播（popup 開著時即時刷新）
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.action === 'progress' && msg.state) {
    renderRunState(msg.state);
  }
});

// 進行中時每秒更新「已 Xs」計時
let _tickTimer = null;
function startTick() {
  if (_tickTimer) return;
  _tickTimer = setInterval(async () => {
    const resp = await bgSend('get_last_run');
    if (!resp.ok || !resp.data) return;
    if (ACTIVE_PHASES.has(resp.data.phase)) {
      renderRunState(resp.data);
    } else {
      stopTick();
    }
  }, 1000);
}
function stopTick() {
  if (_tickTimer) { clearInterval(_tickTimer); _tickTimer = null; }
}
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.action === 'progress' && msg.state) {
    if (ACTIVE_PHASES.has(msg.state.phase)) startTick(); else stopTick();
  }
});

// ── 動作 ──────────────────────────────────────────────────────────────

async function handleImport() {
  await rememberKind();
  setStatus('讀取剪貼簿…', 'run');
  disableButtons(true);
  try {
    const urls = await readClipboardUrls();
    if (urls.length === 0) {
      setStatus('剪貼簿沒有 URL', 'err', '請先複製含 URL 的文字到剪貼簿');
      disableButtons(false);
      return;
    }
    startTick();
    const resp = await bgSend('import_urls', { kind: getKind(), urls });
    if (!resp.ok) throw new Error(resp.error);
    // 完成狀態由 progress 廣播 + finishRun 處理，這裡不主動覆蓋
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
    disableButtons(false);
  } finally {
    stopTick();
  }
}

async function handleClear() {
  await rememberKind();
  const kind = getKind();
  if (!confirm(`確定要清空 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook 內所有非 [SKILL] sources？`)) return;
  setStatus('準備清空…', 'run');
  disableButtons(true);
  try {
    startTick();
    const resp = await bgSend('clear_sources', { kind });
    if (!resp.ok) throw new Error(resp.error);
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
    disableButtons(false);
  } finally {
    stopTick();
  }
}

async function handleGenerate() {
  await rememberKind();
  setStatus('準備產生…', 'run', '可以關閉 popup，完成後會跳桌面通知；重開 popup 也能看到進度');
  disableButtons(true);
  try {
    startTick();
    const resp = await bgSend('generate_report', { kind: getKind() });
    if (!resp.ok) throw new Error(resp.error);
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
    disableButtons(false);
  } finally {
    stopTick();
  }
}

async function handleCombined() {
  await rememberKind();
  const kind = getKind();
  if (!confirm(`一鍵流程：\n1️⃣ 清空 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook 內所有非 [SKILL] sources\n2️⃣ 匯入剪貼簿 URL（請先複製好）\n3️⃣ 產生分析報告並推送 VM\n\n總時間最久 5 分鐘，要繼續嗎？`)) return;
  setStatus('讀取剪貼簿…', 'run');
  disableButtons(true);
  try {
    const urls = await readClipboardUrls();
    if (urls.length === 0) {
      setStatus('剪貼簿沒有 URL', 'err', '請先複製含 URL 的文字到剪貼簿');
      disableButtons(false);
      return;
    }
    startTick();
    const resp = await bgSend('run_combined', { kind, urls });
    if (!resp.ok) throw new Error(resp.error);
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
    disableButtons(false);
  } finally {
    stopTick();
  }
}

// ── 綁定 ──────────────────────────────────────────────────────────────

$('#btn-import').addEventListener('click', handleImport);
$('#btn-clear').addEventListener('click', handleClear);
$('#btn-generate').addEventListener('click', handleGenerate);
$('#btn-combined').addEventListener('click', handleCombined);
$('#open-options').addEventListener('click', openOptions);
document.querySelectorAll('input[name="kind"]').forEach((r) => r.addEventListener('change', rememberKind));

restoreKind();
checkConfig();
loadInitialRunState();
