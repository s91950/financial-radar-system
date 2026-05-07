// popup.js — 三顆按鈕的 UI binding。實際執行委派給 background.js。

const $ = (sel) => document.querySelector(sel);
const statusBox = $('#status');
const statusText = $('#status-text');
const statusDetail = $('#status-detail');
const configHint = $('#config-hint');

function setStatus(text, kind = '', detail = '') {
  statusBox.classList.remove('hidden', 'ok', 'err');
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
  ['#btn-import', '#btn-clear', '#btn-generate'].forEach((s) => {
    $(s).disabled = disabled;
  });
}

async function rememberKind() {
  const kind = getKind();
  await chrome.storage.local.set({ lastKind: kind });
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
    configHint.textContent = `VM: ${s.vmBaseUrl}`;
  }
}

function openOptions(e) {
  e?.preventDefault();
  chrome.runtime.openOptionsPage();
}

// ── 動作 ──────────────────────────────────────────────────────────────

async function handleImport() {
  await rememberKind();
  const kind = getKind();
  setStatus('讀取剪貼簿…', '', '');
  disableButtons(true);
  try {
    let text = '';
    try {
      text = await navigator.clipboard.readText();
    } catch (e) {
      throw new Error(`無法讀取剪貼簿：${e?.message || e}（首次使用會跳權限提示，請允許）`);
    }
    const extractResp = await bgSend('extract_urls_from_text', { text });
    if (!extractResp.ok) throw new Error(extractResp.error);
    const urls = extractResp.data;
    if (urls.length === 0) {
      setStatus('剪貼簿沒有 URL', 'err', '請先複製含 URL 的文字到剪貼簿');
      return;
    }
    setStatus(`匯入中… 找到 ${urls.length} 個 URL`, '', urls.slice(0, 3).join('\n') + (urls.length > 3 ? '\n…' : ''));
    const resp = await bgSend('import_urls', { kind, urls });
    if (!resp.ok) throw new Error(resp.error);
    const r = resp.data;
    const detail = r.errors.length > 0
      ? '失敗：\n' + r.errors.slice(0, 5).map((e) => `• ${e.url} — ${e.message}`).join('\n')
      : '';
    setStatus(`✅ 匯入完成：${r.succeeded}/${r.total} 成功${r.failed > 0 ? `、${r.failed} 失敗` : ''}`, r.failed > 0 ? 'err' : 'ok', detail);
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
  } finally {
    disableButtons(false);
  }
}

async function handleClear() {
  await rememberKind();
  const kind = getKind();
  if (!confirm(`確定要清空 ${kind === 'yt' ? 'YouTube' : '新聞'} notebook 內所有非 [SKILL] sources？`)) return;
  setStatus('清空中…', '');
  disableButtons(true);
  try {
    const resp = await bgSend('clear_sources', { kind });
    if (!resp.ok) throw new Error(resp.error);
    const r = resp.data;
    setStatus(
      `✅ 清空完成：刪除 ${r.deleted}/${r.total}${r.failed > 0 ? `、${r.failed} 失敗` : ''}`,
      r.failed > 0 ? 'err' : 'ok',
      `保留 ${r.skipped} 個 [SKILL] sources`,
    );
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
  } finally {
    disableButtons(false);
  }
}

async function handleGenerate() {
  await rememberKind();
  const kind = getKind();
  setStatus('產生報告中…（最久 5 分鐘）', '', '請保持 popup 開啟，否則 service worker 可能被關閉');
  disableButtons(true);
  try {
    const resp = await bgSend('generate_report', { kind });
    if (!resp.ok) throw new Error(resp.error);
    const r = resp.data;
    const detail = r.pushed
      ? `已推送至 ${r.vmUrl}\n內容長度：${r.contentLength} 字\n預覽：${r.contentPreview}…`
      : `⚠ 推送 VM 失敗：${r.pushError || '未知'}\n本機仍有報告，可手動到 NotebookLM 查看`;
    setStatus(`✅ 報告完成`, r.pushed ? 'ok' : 'err', detail);
  } catch (e) {
    setStatus(`❌ ${e?.message || e}`, 'err');
  } finally {
    disableButtons(false);
  }
}

// ── 綁定 ──────────────────────────────────────────────────────────────

$('#btn-import').addEventListener('click', handleImport);
$('#btn-clear').addEventListener('click', handleClear);
$('#btn-generate').addEventListener('click', handleGenerate);
$('#open-options').addEventListener('click', openOptions);
document.querySelectorAll('input[name="kind"]').forEach((r) => r.addEventListener('change', rememberKind));

restoreKind();
checkConfig();
