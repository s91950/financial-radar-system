/**
 * 財經雷達 GAS 腳本 — 貼入現有 GAS 專案
 * ==========================================
 *
 * === 主要機制：每 30 分鐘從 VM 拉取新聞（pullFromVM）===
 *   VM 的 SQLite 資料庫為唯一來源，GAS 定期同步，自動去重。
 *   欄位：入庫時間 | 標題 | 嚴重度 | 來源 | 關鍵字 | 網址
 *
 * === 備援機制：接收後端 POST（doPost）===
 *   相容舊版 {articles:[...]} 與新版 {action:"appendNews", rows:[...]} 格式。
 *
 * === 每日封存（dailyArchive）===
 *   每日 00:05 台灣時間執行：
 *   將「財金新聞」tab 複製為「YYYY-MM-DD」封存 tab，並清空「財金新聞」。
 *
 * === 每小時摘要推 LINE（hourlyDigest，選用）===
 *
 * ─────────────────────────────────────────
 * 指令碼屬性（「專案設定」→「指令碼屬性」）：
 *   VM_API_URL    = http://34.23.154.194     ← VM 公開 IP（無尾斜線）
 *   GEMINI_API_KEY = ...                     ← 選用（hourlyDigest 用）
 *   LINE_TOKEN     = ...                     ← 選用（hourlyDigest 用）
 *   LINE_TARGET_ID = ...                     ← 選用（hourlyDigest 用）
 *   HOURS_BACK     = 1                       ← 選用（hourlyDigest 用）
 *   MIN_ARTICLES   = 2                       ← 選用（hourlyDigest 用）
 *
 * ─────────────────────────────────────────
 * 觸發器設定：
 *   pullFromVM   → 時間驅動 → 分鐘計時器（每 30 分鐘）
 *   dailyArchive → 時間驅動 → 日計時器（午夜至凌晨 1 點）
 *   hourlyDigest → 時間驅動 → 小時計時器（每小時）← 選用
 *
 * ─────────────────────────────────────────
 * 部署方式（doPost 備援用）：
 *   「部署」→「新增部署作業」→ 類型「網頁應用程式」
 *   執行身分：我（你的帳號）  存取權：所有人
 *   ★ 每次修改腳本後必須重新部署才會生效！
 */


// ── 全域設定 ──────────────────────────────────────────────────────────────────
var NEWS_SHEET   = '財金新聞';    // 當日新聞工作表（每日清空）
var ARCHIVE_COL  = 6;             // 欄位數：入庫時間/標題/嚴重度/來源/關鍵字/網址
var HEADERS      = ['入庫時間', '標題', '嚴重度', '來源', '關鍵字', '網址'];
var URL_COL_IDX  = 6;             // 網址在第 6 欄（1-based）


// ══════════════════════════════════════════════════════════════════════════════
// 功能一：從 VM 主動拉取新聞（主要機制）
// 觸發：每 30 分鐘
// ══════════════════════════════════════════════════════════════════════════════

function pullFromVM() {
  var props  = PropertiesService.getScriptProperties();
  var vmUrl  = (props.getProperty('VM_API_URL') || '').replace(/\/$/, '');
  if (!vmUrl) {
    Logger.log('[SKIP] VM_API_URL 未設定，請在指令碼屬性中填入 VM 的 http://IP');
    return;
  }

  // 取得今日台灣時間起點（00:00:00 +08:00）
  var tz       = 'Asia/Taipei';
  var today    = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var cutoff   = today + 'T00:00:00+08:00';
  var apiUrl   = vmUrl + '/api/news/articles?limit=500&fetched_after='
                 + encodeURIComponent(cutoff);

  try {
    var resp = UrlFetchApp.fetch(apiUrl, {
      method: 'get',
      muteHttpExceptions: true,
      headers: { 'Accept': 'application/json' }
    });

    if (resp.getResponseCode() !== 200) {
      Logger.log('[ERROR] VM API 回傳 %s: %s',
        resp.getResponseCode(), resp.getContentText().substring(0, 200));
      return;
    }

    var data     = JSON.parse(resp.getContentText());
    var articles = data.articles || [];
    Logger.log('[INFO] VM 回傳 %s 篇文章（今日 %s 起）', articles.length, today);
    if (articles.length === 0) return;

    var sheet      = _getOrCreateSheet_();
    var existingUrls = _getExistingUrls_(sheet);
    var written    = 0;

    articles.forEach(function(a) {
      var url = a.source_url || '';
      if (url && existingUrls[url]) return;  // 已存在，跳過

      var fetched = _formatTW_(a.fetched_at || a.published_at || '');
      sheet.appendRow([
        fetched,
        a.title           || '',
        _sevLabel_(a.severity || ''),
        a.source          || '',
        a.matched_keyword || '',
        url
      ]);
      if (url) existingUrls[url] = true;
      written++;
    });

    Logger.log('[OK] 新增 %s 筆（已去重，共 %s 篇）', written, articles.length);

  } catch (err) {
    Logger.log('[ERROR] pullFromVM 例外：%s', err.message);
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// 功能二：每日封存
// 觸發：日計時器（午夜 00:00–01:00 台灣時間）
// ══════════════════════════════════════════════════════════════════════════════

function dailyArchive() {
  var tz        = 'Asia/Taipei';
  var yesterday = new Date(new Date().getTime() - 24 * 60 * 60 * 1000);
  var dateLabel = Utilities.formatDate(yesterday, tz, 'yyyy-MM-dd');

  var ss  = SpreadsheetApp.getActiveSpreadsheet();
  var src = ss.getSheetByName(NEWS_SHEET);
  if (!src) {
    Logger.log('[SKIP] 找不到工作表：%s', NEWS_SHEET);
    return;
  }

  var lastRow = src.getLastRow();

  // 有資料才封存（lastRow > 1 表示有資料列）
  if (lastRow > 1) {
    // 若封存 tab 已存在則先刪除（避免重複）
    var existing = ss.getSheetByName(dateLabel);
    if (existing) ss.deleteSheet(existing);

    // 複製 tab 並重命名
    var archive = src.copyTo(ss);
    archive.setName(dateLabel);

    // 將封存 tab 移到「財金新聞」右邊（維持時間順序）
    var srcIndex = ss.getSheets().indexOf(src);
    ss.moveActiveSheet(srcIndex + 2);  // copyTo 後 archive 是最後一頁，移到 src 後面

    Logger.log('[OK] 封存為 tab「%s」（%s 筆資料）', dateLabel, lastRow - 1);
  } else {
    Logger.log('[SKIP] 無新聞可封存（%s）', dateLabel);
  }

  // 清空「財金新聞」（保留標頭）
  if (lastRow > 1) {
    src.deleteRows(2, lastRow - 1);
  }
  Logger.log('[OK]「財金新聞」已清空，準備收集 %s 的新聞',
    Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd'));
}


// ══════════════════════════════════════════════════════════════════════════════
// 功能三：接收後端 POST（備援機制）
// 相容 {articles:[...]} 與 {action:"appendNews", rows:[...]} 兩種格式
// ══════════════════════════════════════════════════════════════════════════════

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);

    // 格式正規化：統一轉成 [{date, title, severity, source, keyword, url}]
    var articles = [];
    if (Array.isArray(data.articles)) {
      // 舊版格式：{articles:[{date, title, keyword, url}]}
      articles = data.articles.map(function(a) {
        return {
          date: a.date || '', title: a.title || '',
          severity: a.severity || '', source: a.source || '',
          keyword: a.keyword || '', url: a.url || ''
        };
      });
    } else if (data.action === 'appendNews' && Array.isArray(data.rows)) {
      // 新版格式：{action:"appendNews", rows:[{入庫時間, 標題, 嚴重度, 來源, 關鍵字, 網址}]}
      articles = data.rows.map(function(r) {
        return {
          date: r['入庫時間'] || r['資料日期'] || '',
          title:    r['標題']  || '',
          severity: r['嚴重度'] || '',
          source:   r['來源']  || '',
          keyword:  r['關鍵字'] || r['分類'] || '',
          url:      r['網址']  || ''
        };
      });
    }

    if (articles.length === 0) return _jsonResp({status: 'ok', written: 0});

    var sheet        = _getOrCreateSheet_();
    var existingUrls = _getExistingUrls_(sheet);
    var written      = 0;

    articles.forEach(function(a) {
      if (a.url && existingUrls[a.url]) return;
      sheet.appendRow([
        a.date, a.title, _sevLabel_(a.severity), a.source, a.keyword, a.url
      ]);
      if (a.url) existingUrls[a.url] = true;
      written++;
    });

    return _jsonResp({status: 'ok', written: written});

  } catch (err) {
    return _jsonResp({status: 'error', message: err.message});
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// 功能四：每小時摘要推 LINE（選用）
// ══════════════════════════════════════════════════════════════════════════════

function hourlyDigest() {
  var props     = PropertiesService.getScriptProperties();
  var apiKey    = props.getProperty('GEMINI_API_KEY')    || '';
  var lineToken = props.getProperty('LINE_TOKEN')        || '';
  var targetId  = props.getProperty('LINE_TARGET_ID')    || '';
  var hoursBack = parseInt(props.getProperty('HOURS_BACK') || '1', 10);
  var minArt    = parseInt(props.getProperty('MIN_ARTICLES') || '2', 10);

  if (!apiKey || !lineToken || !targetId) {
    Logger.log('[SKIP] 缺少必要的指令碼屬性（GEMINI_API_KEY / LINE_TOKEN / LINE_TARGET_ID）');
    return;
  }

  var articles = _getRecentArticles_(hoursBack);
  Logger.log('[INFO] 近 %s 小時找到 %s 篇文章', hoursBack, articles.length);
  if (articles.length < minArt) {
    Logger.log('[SKIP] 文章數不足 %s 篇，跳過', minArt);
    return;
  }

  var analysis = _callGemini_(_buildPrompt_(articles, hoursBack), apiKey);
  if (!analysis) { Logger.log('[ERROR] Gemini 未回傳內容'); return; }

  var now = Utilities.formatDate(new Date(), 'Asia/Taipei', 'MM/dd HH:mm');
  _pushLine_('📊 財經雷達摘要 ' + now + '\n\n' + analysis, lineToken, targetId);
}


// ══════════════════════════════════════════════════════════════════════════════
// 私有工具函式
// ══════════════════════════════════════════════════════════════════════════════

function _getOrCreateSheet_() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(NEWS_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(NEWS_SHEET, 0);  // 插入為第一個 tab
    sheet.appendRow(HEADERS);
    // 凍結標頭列
    sheet.setFrozenRows(1);
    // 調整欄寬（讓標題和網址更易讀）
    sheet.setColumnWidth(2, 400);  // 標題
    sheet.setColumnWidth(6, 300);  // 網址
  }
  return sheet;
}

function _getExistingUrls_(sheet) {
  var lastRow = sheet.getLastRow();
  var urls    = {};
  if (lastRow < 2) return urls;
  var vals = sheet.getRange(2, URL_COL_IDX, lastRow - 1, 1).getValues();
  vals.forEach(function(r) { if (r[0]) urls[r[0]] = true; });
  return urls;
}

function _formatTW_(isoStr) {
  if (!isoStr) return '';
  try {
    var d = new Date(isoStr);
    return Utilities.formatDate(d, 'Asia/Taipei', 'MM/dd HH:mm');
  } catch (e) {
    return isoStr.substring(0, 16);
  }
}

function _sevLabel_(sev) {
  var map = { critical: '🔴 緊急', high: '🟡 高', low: '⚪ 低' };
  return map[sev] || sev || '';
}

function _getRecentArticles_(hoursBack) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(NEWS_SHEET);
  if (!sheet) return [];
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  var data   = sheet.getRange(2, 1, lastRow - 1, ARCHIVE_COL).getValues();
  var cutoff = new Date(Date.now() - hoursBack * 60 * 60 * 1000);
  return data.filter(function(r) {
    if (!r[1]) return false;  // 無標題
    var d = new Date(r[0]);
    return !isNaN(d.getTime()) && d >= cutoff;
  }).map(function(r) {
    return { title: String(r[1]), severity: r[2], source: r[3] };
  });
}

function _buildPrompt_(articles, hoursBack) {
  var lines = ['以下是過去 ' + hoursBack + ' 小時內收錄的財經新聞，請用繁體中文分析：\n'];
  articles.forEach(function(a, i) {
    var tag = a.severity ? ' [' + a.severity + ']' : '';
    lines.push((i + 1) + '. ' + a.title + tag);
  });
  lines.push('\n請提供：');
  lines.push('1. 最值得關注的 2-3 則新聞及其對台灣市場的潛在影響');
  lines.push('2. 整體市場情緒判斷（樂觀 / 謹慎 / 悲觀）');
  lines.push('3. 建議關注的後續指標或事件');
  lines.push('請簡潔，回覆控制在 400 字以內。');
  return lines.join('\n');
}

function _callGemini_(prompt, apiKey) {
  var url     = 'https://generativelanguage.googleapis.com/v1beta/models/'
                + 'gemini-2.0-flash:generateContent?key=' + apiKey;
  var payload = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens: 800, temperature: 0.4 }
  };
  try {
    var resp = UrlFetchApp.fetch(url, {
      method: 'post', contentType: 'application/json',
      payload: JSON.stringify(payload), muteHttpExceptions: true
    });
    if (resp.getResponseCode() !== 200) return null;
    var json = JSON.parse(resp.getContentText());
    return json.candidates &&
           json.candidates[0] &&
           json.candidates[0].content &&
           json.candidates[0].content.parts &&
           json.candidates[0].content.parts[0].text || null;
  } catch (e) {
    Logger.log('[ERROR] Gemini：%s', e.message);
    return null;
  }
}

function _pushLine_(message, token, targetId) {
  var payload = { to: targetId, messages: [{ type: 'text', text: message.substring(0, 4990) }] };
  try {
    UrlFetchApp.fetch('https://api.line.me/v2/bot/message/push', {
      method: 'post', contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token },
      payload: JSON.stringify(payload), muteHttpExceptions: true
    });
  } catch (e) {
    Logger.log('[ERROR] LINE：%s', e.message);
  }
}

function _jsonResp(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
