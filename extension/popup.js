// popup.js — 多任務 UI（v0.6+）
// 動作按鈕都是「即發即返」：bgSend 收到 taskId 立即回；task 在 background 並行跑，
// task_update / task_remove 廣播給 popup 同步 UI。所以使用者可以連續對不同 notebook
// 開好幾個任務同時跑。

const $ = (sel) => document.querySelector(sel);
const selectEl = $('#notebook-select');
const taskListEl = $('#task-list');
const emptyStateEl = $('#empty-state');
const cancelAllBtn = $('#btn-cancel-all');
const configHint = $('#config-hint');
const ppPanel = $('#pp-panel');
const ppBackdrop = $('#pp-backdrop');
const ppList = $('#pp-list');

// 提示詞收藏資料（從 storage 載入）
let _savedPrompts = [];   // [{ id, name, content }]
let _selectedPromptId = null;  // null = 使用預設（依 kind）

// taskId -> { rowEl, task }  — popup 本地副本，每秒 tick 更新 elapsed 用
const taskRows = new Map();

const ACTIVE_PHASES = new Set([
  'starting', 'clear', 'import', 'generate', 'download', 'push',
  'combined-start', 'between',
]);

function isActivePhase(phase) { return ACTIVE_PHASES.has(phase); }

function fmtElapsed(start, end) {
  if (!start) return '';
  const sec = Math.round(((end || Date.now()) - start) / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m${sec % 60}s`;
}

function getKind() {
  return document.querySelector('input[name="kind"]:checked')?.value || 'news';
}

function kindBadge(kind) {
  if (kind === 'yt') return '📺 YT';
  if (kind === 'none') return '🚫 不推送';
  if (kind === 'news') return '📰 新聞';
  return '';
}

// ── 提示詞收藏 ─────────────────────────────────────────────────────────

function getSelectedPromptContent() {
  if (!_selectedPromptId) return null;
  return _savedPrompts.find((p) => p.id === _selectedPromptId)?.content ?? null;
}

async function loadSavedPrompts() {
  const data = await chrome.storage.local.get(['savedPrompts', 'selectedPromptId']);
  _savedPrompts = Array.isArray(data.savedPrompts) ? data.savedPrompts : [];
  _selectedPromptId = data.selectedPromptId || null;
  // 選取的 id 若已被刪除則清掉
  if (_selectedPromptId && !_savedPrompts.find((p) => p.id === _selectedPromptId)) {
    _selectedPromptId = null;
  }
}

async function persistPrompts() {
  await chrome.storage.local.set({ savedPrompts: _savedPrompts, selectedPromptId: _selectedPromptId });
}

function renderPromptList() {
  ppList.innerHTML = '';

  // 預設項
  ppList.appendChild(makePromptItem(null, '預設（依分析類型）', false));

  if (_savedPrompts.length === 0) {
    const el = document.createElement('div');
    el.className = 'pp-empty';
    el.textContent = '尚無收藏，在下方新增';
    ppList.appendChild(el);
  } else {
    for (const p of _savedPrompts) {
      ppList.appendChild(makePromptItem(p.id, p.name, true));
    }
  }

  $('#btn-prompt-settings').classList.toggle('has-selection', _selectedPromptId !== null);
}

function makePromptItem(id, name, deletable) {
  const wrapper = document.createElement('div');
  wrapper.className = 'pp-item-wrapper';

  // ── 主列 ──
  const row = document.createElement('div');
  row.className = `pp-item${_selectedPromptId === id ? ' selected' : ''}`;

  const dot = document.createElement('span');
  dot.className = 'pp-dot';

  const nameEl = document.createElement('span');
  nameEl.className = 'pp-item-name';
  nameEl.textContent = name;
  nameEl.title = name;

  row.append(dot, nameEl);

  if (deletable) {
    const prompt = _savedPrompts.find((p) => p.id === id);

    // 展開按鈕
    const expandBtn = document.createElement('button');
    expandBtn.className = 'pp-item-action';
    expandBtn.textContent = '▸';
    expandBtn.title = '展開內容';
    expandBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = contentArea.hidden;
      contentArea.hidden = !isOpen;
      expandBtn.textContent = isOpen ? '▾' : '▸';
      expandBtn.classList.toggle('open', isOpen);
    });

    // 複製按鈕
    const copyBtn = document.createElement('button');
    copyBtn.className = 'pp-item-action';
    copyBtn.textContent = '⧉';
    copyBtn.title = '複製提示詞';
    copyBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!prompt?.content) return;
      navigator.clipboard.writeText(prompt.content).then(() => {
        copyBtn.textContent = '✓';
        setTimeout(() => { copyBtn.textContent = '⧉'; }, 1200);
      }).catch(() => {
        // fallback for HTTP
        const ta = document.createElement('textarea');
        ta.value = prompt.content;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        copyBtn.textContent = '✓';
        setTimeout(() => { copyBtn.textContent = '⧉'; }, 1200);
      });
    });

    // 刪除按鈕
    const del = document.createElement('button');
    del.className = 'pp-item-del';
    del.textContent = '✕';
    del.title = '刪除';
    del.addEventListener('click', async (e) => {
      e.stopPropagation();
      await deletePrompt(id);
    });

    row.append(expandBtn, copyBtn, del);

    // ── 展開內容區 ──
    var contentArea = document.createElement('div');
    contentArea.className = 'pp-item-content';
    contentArea.textContent = prompt?.content || '';
    contentArea.hidden = true;
    wrapper.append(row, contentArea);
  } else {
    wrapper.appendChild(row);
  }

  row.addEventListener('click', async () => {
    await selectPrompt(id);
  });

  return wrapper;
}

async function selectPrompt(id) {
  _selectedPromptId = id;
  await persistPrompts();
  renderPromptList();
}

async function deletePrompt(id) {
  if (_selectedPromptId === id) _selectedPromptId = null;
  _savedPrompts = _savedPrompts.filter((p) => p.id !== id);
  await persistPrompts();
  renderPromptList();
}

async function addNewPrompt() {
  const nameEl = $('#pp-name');
  const contentEl = $('#pp-content');
  const name = nameEl.value.trim();
  const content = contentEl.value.trim();
  if (!name) { showToast('請輸入名稱', 'err'); nameEl.focus(); return; }
  if (!content) { showToast('請輸入提示詞內容', 'err'); contentEl.focus(); return; }
  const id = `p_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  _savedPrompts.push({ id, name, content });
  await persistPrompts();
  nameEl.value = '';
  contentEl.value = '';
  renderPromptList();
  showToast(`已新增「${name}」`, 'info');
}

function openPromptPanel() {
  ppPanel.hidden = false;
  ppBackdrop.hidden = false;
  $('#btn-prompt-settings').classList.add('active');
  renderPromptList();
}

function closePromptPanel() {
  ppPanel.hidden = true;
  ppBackdrop.hidden = true;
  $('#btn-prompt-settings').classList.remove('active');
}

function togglePromptPanel() {
  if (ppPanel.hidden) openPromptPanel();
  else closePromptPanel();
}

function getNotebookId() {
  return selectEl?.value || '';
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

// ── Toast（暫時提示）─────────────────────────────────────────────────

let _toastTimer = null;
function showToast(text, kind = 'info') {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = `toast ${kind === 'err' ? 'err' : ''}`;
  el.textContent = text;
  document.body.appendChild(el);
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.remove(); }, 2500);
}

// ── Notebook 下拉 ──────────────────────────────────────────────────────

async function loadNotebooks({ forceRefresh = false } = {}) {
  selectEl.innerHTML = '<option value="">載入筆記本中…</option>';
  selectEl.disabled = true;

  const { lastNotebookId, cachedNotebooks_v2 } = await chrome.storage.local.get(['lastNotebookId', 'cachedNotebooks_v2']);

  if (!forceRefresh && Array.isArray(cachedNotebooks_v2) && cachedNotebooks_v2.length > 0) {
    renderNotebookOptions(cachedNotebooks_v2, lastNotebookId);
  }

  const resp = await bgSend('list_notebooks');
  if (!resp.ok) {
    if (!Array.isArray(cachedNotebooks_v2) || cachedNotebooks_v2.length === 0) {
      selectEl.innerHTML = '<option value="">❌ 載入失敗</option>';
      showToast(`載入筆記本失敗：${resp.error || '未登入'}`, 'err');
    }
    selectEl.disabled = false;
    return;
  }
  const notebooks = resp.data || [];
  await chrome.storage.local.set({ cachedNotebooks_v2: notebooks });
  renderNotebookOptions(notebooks, lastNotebookId);
}

function renderNotebookOptions(notebooks, preferredId) {
  if (!notebooks || notebooks.length === 0) {
    selectEl.innerHTML = '<option value="">（沒有筆記本，請按「+ 建立新筆記本」）</option>';
    selectEl.disabled = false;
    return;
  }
  selectEl.innerHTML = '';
  for (const nb of notebooks) {
    const opt = document.createElement('option');
    opt.value = nb.id;
    opt.textContent = nb.title;
    selectEl.appendChild(opt);
  }
  if (preferredId && notebooks.some((n) => n.id === preferredId)) {
    selectEl.value = preferredId;
  } else {
    selectEl.value = notebooks[0].id;
  }
  selectEl.disabled = false;
  rememberNotebook();
}

async function rememberNotebook() {
  await chrome.storage.local.set({ lastNotebookId: getNotebookId() });
}

async function rememberKind() {
  await chrome.storage.local.set({ lastKind: getKind() });
}

async function restoreKind() {
  const { lastKind } = await chrome.storage.local.get('lastKind');
  const kind = lastKind || 'none';
  const radio = document.querySelector(`input[name="kind"][value="${kind}"]`);
  if (radio) radio.checked = true;
}

async function checkConfig() {
  const resp = await bgSend('get_settings');
  if (!resp.ok) return;
  const s = resp.data;
  configHint.textContent = s.skipVmPush ? '本機模式（不推 VM）' : `VM: ${s.vmBaseUrl}`;
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

// ── Task 列表渲染 ──────────────────────────────────────────────────────

function upsertTaskRow(task) {
  let entry = taskRows.get(task.id);
  if (!entry) {
    const tpl = document.getElementById('task-row-template');
    const rowEl = tpl.content.firstElementChild.cloneNode(true);
    rowEl.dataset.taskId = task.id;
    rowEl.querySelector('.task-cancel').addEventListener('click', () => {
      bgSend('cancel_task', { taskId: task.id });
    });
    rowEl.querySelector('.task-dismiss').addEventListener('click', () => {
      bgSend('dismiss_task', { taskId: task.id });
    });
    // 新 task 放最上面，方便看
    taskListEl.insertBefore(rowEl, taskListEl.firstChild);
    entry = { rowEl, task };
    taskRows.set(task.id, entry);
  } else {
    entry.task = task;
  }
  renderTaskRow(entry.rowEl, task);
  updateEmptyState();
  updateGlobalCancelVisibility();
}

function removeTaskRow(taskId) {
  const entry = taskRows.get(taskId);
  if (entry) {
    entry.rowEl.remove();
    taskRows.delete(taskId);
  }
  updateEmptyState();
  updateGlobalCancelVisibility();
}

function renderTaskRow(rowEl, task) {
  const active = isActivePhase(task.phase);
  rowEl.classList.remove('active', 'ok', 'err', 'cancelled');
  if (active) rowEl.classList.add('active');
  else if (task.cancelled) rowEl.classList.add('cancelled');
  else if (task.ok) rowEl.classList.add('ok');
  else rowEl.classList.add('err');

  const icon = rowEl.querySelector('.task-icon');
  const label = rowEl.querySelector('.task-label');
  const elapsed = rowEl.querySelector('.task-elapsed');
  const cancelBtn = rowEl.querySelector('.task-cancel');
  const dismissBtn = rowEl.querySelector('.task-dismiss');
  const meta = rowEl.querySelector('.task-meta');
  const progress = rowEl.querySelector('.task-progress');

  if (active) icon.textContent = '⏳';
  else if (task.cancelled) icon.textContent = '⛔';
  else if (task.ok) icon.textContent = '✅';
  else icon.textContent = '❌';

  label.textContent = task.label;
  elapsed.textContent = active
    ? fmtElapsed(task.startedAt)
    : `耗時 ${fmtElapsed(task.startedAt, task.finishedAt)}`;

  cancelBtn.hidden = !active;
  dismissBtn.hidden = active;

  const kindStr = task.kind ? ` · ${kindBadge(task.kind)}` : '';
  meta.textContent = `📒 ${task.notebookTitle}${kindStr}`;

  let progressText = task.message || '';
  if (task.total > 0 && task.phase !== 'generate' && active) {
    progressText = `${task.current}/${task.total} · ${progressText}`;
  }
  if (!active && (task.summary || task.error)) {
    progressText = task.summary || task.error || '';
  }
  progress.textContent = progressText;
}

function updateEmptyState() {
  if (taskRows.size === 0) {
    if (!emptyStateEl.parentElement) taskListEl.appendChild(emptyStateEl);
    emptyStateEl.hidden = false;
  } else {
    emptyStateEl.hidden = true;
  }
}

function updateGlobalCancelVisibility() {
  let activeCount = 0;
  for (const { task } of taskRows.values()) {
    if (isActivePhase(task.phase)) activeCount += 1;
  }
  cancelAllBtn.hidden = activeCount < 2;
}

async function loadTasks() {
  const resp = await bgSend('list_tasks');
  if (!resp.ok) return;
  const tasks = resp.data || [];
  // 由舊到新加入（內部 insertBefore firstChild 會自動讓最新的在最上面）
  for (const task of tasks.sort((a, b) => a.startedAt - b.startedAt)) {
    upsertTaskRow(task);
  }
}

// 每秒更新 elapsed（只對 active task）
setInterval(() => {
  for (const { rowEl, task } of taskRows.values()) {
    if (isActivePhase(task.phase)) {
      rowEl.querySelector('.task-elapsed').textContent = fmtElapsed(task.startedAt);
    }
  }
}, 1000);

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.action === 'task_update' && msg.task) {
    upsertTaskRow(msg.task);
  } else if (msg?.action === 'task_remove' && msg.taskId) {
    removeTaskRow(msg.taskId);
  }
});

// ── 動作（每個都即發即返，task 在背景跑）─────────────────────────────

function requireNotebook() {
  const id = getNotebookId();
  if (!id) {
    showToast('請先在上方下拉選一個筆記本', 'err');
    return null;
  }
  return id;
}

async function startTask(action, payload, errMsg) {
  const resp = await bgSend(action, payload);
  if (!resp.ok) {
    showToast(errMsg + '：' + (resp.error || ''), 'err');
    return false;
  }
  return true;
}

async function handleImportCurrent() {
  const notebookId = requireNotebook();
  if (!notebookId) return;
  await rememberKind();
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) throw new Error('找不到目前頁面 URL（可能是 chrome:// 內部頁）');
    if (!/^https?:\/\//i.test(tab.url)) {
      throw new Error(`不支援此 URL 類型：${tab.url.slice(0, 60)}`);
    }
    await startTask('import_urls', { notebookId, urls: [tab.url] }, '開啟匯入任務失敗');
  } catch (e) {
    showToast(String(e?.message || e), 'err');
  }
}

async function handleImport() {
  const notebookId = requireNotebook();
  if (!notebookId) return;
  await rememberKind();
  try {
    const urls = await readClipboardUrls();
    if (urls.length === 0) {
      showToast('剪貼簿沒有 URL，請先複製含 URL 的文字', 'err');
      return;
    }
    await startTask('import_urls', { notebookId, urls }, '開啟匯入任務失敗');
  } catch (e) {
    showToast(String(e?.message || e), 'err');
  }
}

async function handleClear() {
  const notebookId = requireNotebook();
  if (!notebookId) return;
  const nbTitle = selectEl.options[selectEl.selectedIndex]?.textContent || notebookId;
  if (!confirm(`確定要清空「${nbTitle}」內所有非 [SKILL] sources？`)) return;
  await rememberKind();
  await startTask('clear_sources', { notebookId }, '開啟清空任務失敗');
}

async function handleGenerate() {
  const notebookId = requireNotebook();
  if (!notebookId) return;
  await rememberKind();
  await startTask('generate_report', {
    notebookId,
    kind: getKind(),
    customPrompt: getSelectedPromptContent(),
  }, '開啟分析任務失敗');
}

async function handleCombined() {
  const notebookId = requireNotebook();
  if (!notebookId) return;
  // 先讀剪貼簿（popup 此時有 focus，clipboard API 才允許讀取）
  // 必須在 confirm() 之前，因為 confirm 彈出後 document 暫時失去 focus
  let urls;
  try {
    urls = await readClipboardUrls();
    if (urls.length === 0) {
      showToast('剪貼簿沒有 URL，請先複製含 URL 的文字', 'err');
      return;
    }
  } catch (e) {
    showToast(String(e?.message || e), 'err');
    return;
  }
  const nbTitle = selectEl.options[selectEl.selectedIndex]?.textContent || notebookId;
  if (!confirm(`一鍵流程（在「${nbTitle}」）：\n1️⃣ 清空所有非 [SKILL] sources\n2️⃣ 匯入 ${urls.length} 個 URL\n3️⃣ 產生分析報告並推送 VM\n\n要繼續嗎？`)) return;
  await rememberKind();
  try {
    await startTask('run_combined', {
      notebookId,
      kind: getKind(),
      customPrompt: getSelectedPromptContent(),
      urls,
    }, '開啟一鍵流程失敗');
  } catch (e) {
    showToast(String(e?.message || e), 'err');
  }
}

async function handleOpenNotebook() {
  const notebookId = requireNotebook();
  if (!notebookId) return;
  await bgSend('open_notebook', { notebookId });
}

async function handleCreateNotebook() {
  const title = prompt('新筆記本名稱：', `新筆記本 ${new Date().toLocaleDateString('zh-TW')}`);
  if (title === null) return;
  if (!title.trim()) { showToast('名稱不能空白', 'err'); return; }
  showToast('建立筆記本中…', 'info');
  const resp = await bgSend('create_notebook', { title: title.trim() });
  if (!resp.ok) { showToast('建立失敗：' + resp.error, 'err'); return; }
  showToast(`✅ 已建立「${resp.data.title}」`, 'info');
  await chrome.storage.local.set({ lastNotebookId: resp.data.id });
  await loadNotebooks({ forceRefresh: true });
}

async function handleRefreshNotebooks() {
  await loadNotebooks({ forceRefresh: true });
}

async function handleCancelAll() {
  const resp = await bgSend('cancel_all_tasks');
  if (resp.ok) showToast(`已對 ${resp.count || 0} 個任務送取消`, 'info');
}

// ── 綁定 ──────────────────────────────────────────────────────────────

$('#btn-import-current').addEventListener('click', handleImportCurrent);
$('#btn-import').addEventListener('click', handleImport);
$('#btn-clear').addEventListener('click', handleClear);
$('#btn-generate').addEventListener('click', handleGenerate);
$('#btn-combined').addEventListener('click', handleCombined);
$('#btn-open-notebook').addEventListener('click', handleOpenNotebook);
$('#btn-create-notebook').addEventListener('click', handleCreateNotebook);
$('#btn-refresh-notebooks').addEventListener('click', handleRefreshNotebooks);
$('#btn-cancel-all').addEventListener('click', handleCancelAll);
$('#open-options').addEventListener('click', openOptions);
$('#btn-prompt-settings').addEventListener('click', togglePromptPanel);
$('#pp-close').addEventListener('click', closePromptPanel);
$('#pp-backdrop').addEventListener('click', closePromptPanel);
$('#pp-add-btn').addEventListener('click', addNewPrompt);
selectEl.addEventListener('change', rememberNotebook);
document.querySelectorAll('input[name="kind"]').forEach((r) => {
  r.addEventListener('change', rememberKind);
});

// 清掉 v0.5.0 那一版錯誤 parse 結果留下的舊 cache
chrome.storage.local.remove('cachedNotebooks');

restoreKind();
checkConfig();
loadNotebooks();
loadTasks();
loadSavedPrompts().then(() => {
  // 更新 ✏️ 按鈕的小圓點指示（有選取非預設提示詞時顯示）
  $('#btn-prompt-settings').classList.toggle('has-selection', _selectedPromptId !== null);
});
