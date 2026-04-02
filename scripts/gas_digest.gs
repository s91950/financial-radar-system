/**
 * 財經雷達 GAS 腳本 — 貼入現有 GAS 專案
 * ==========================================
 *
 * === 功能一：接收後端寫入緊急新聞（doPost）===
 *   後端每次雷達掃描結束後，自動 POST 緊急/高重要度文章過來。
 *   新聞會追加到工作表「財金新聞」（如不存在則自動建立並加標頭）。
 *   格式：{"articles": [{"date":"...","title":"...","keyword":"...","url":"..."}]}
 *
 *   部署方式：
 *     「部署」→「新增部署作業」→ 類型選「網頁應用程式」
 *     執行身分：我（你的帳號）
 *     存取權：所有人
 *   ★ 每次修改腳本後必須重新部署（建立新版本）才會生效！
 *
 * === 功能二：每小時摘要推 LINE（hourlyDigest）===
 *   在 GAS 專案的「專案設定」→「指令碼屬性」設定以下變數：
 *     GEMINI_API_KEY   = 你的 Gemini API Key
 *     LINE_TOKEN       = LINE_CHANNEL_ACCESS_TOKEN
 *     LINE_TARGET_ID   = LINE 推播目標 ID
 *     NEWS_SHEET_NAME  = 財金新聞（或你的新聞存檔頁名稱）
 *     HOURS_BACK       = 1（抓幾小時內的新聞，預設 1）
 *     MIN_ARTICLES     = 2（不足幾篇就跳過）
 *
 *   設定觸發器：「觸發條件」→「+ 新增觸發條件」
 *     函式：hourlyDigest
 *     事件來源：時間驅動
 *     時間型觸發器：小時計時器（每小時）
 */


// ── 接收後端 POST（寫入緊急新聞）────────────────────────────────────────────

var NEWS_WRITE_SHEET = '財金新聞';   // ← 你的工作表名稱，改這裡即可

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var articles = data.articles;
    if (!articles || articles.length === 0) {
      return _jsonResp({status: 'ok', written: 0});
    }

    var ss    = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(NEWS_WRITE_SHEET);

    // 工作表不存在時自動建立並加標頭
    if (!sheet) {
      sheet = ss.insertSheet(NEWS_WRITE_SHEET);
      sheet.appendRow(['資料日期', '標題', '關鍵字', '網址']);
    }

    articles.forEach(function(a) {
      sheet.appendRow([
        a.date    || '',
        a.title   || '',
        a.keyword || '',
        a.url     || ''
      ]);
    });

    return _jsonResp({status: 'ok', written: articles.length});

  } catch (err) {
    return _jsonResp({status: 'error', message: err.message});
  }
}

function _jsonResp(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}


// ── 主函式（每小時觸發）─────────────────────────────────────────────────

function hourlyDigest() {
  const props     = PropertiesService.getScriptProperties();
  const apiKey    = props.getProperty('GEMINI_API_KEY')    || '';
  const lineToken = props.getProperty('LINE_TOKEN')        || '';
  const targetId  = props.getProperty('LINE_TARGET_ID')    || '';
  const sheetName = props.getProperty('NEWS_SHEET_NAME')   || 'Sheet2';
  const hoursBack = parseInt(props.getProperty('HOURS_BACK') || '1', 10);
  const minArt    = parseInt(props.getProperty('MIN_ARTICLES') || '2', 10);

  if (!apiKey || !lineToken || !targetId) {
    Logger.log('[SKIP] 缺少必要的指令碼屬性設定');
    return;
  }

  // 1. 讀取近期文章
  const articles = getRecentArticles_(sheetName, hoursBack);
  Logger.log('[INFO] 近 %s 小時找到 %s 篇文章', hoursBack, articles.length);

  if (articles.length < minArt) {
    Logger.log('[SKIP] 文章數不足 %s 篇，跳過', minArt);
    return;
  }

  // 2. 呼叫 Gemini 分析
  const prompt   = buildPrompt_(articles, hoursBack);
  const analysis = callGemini_(prompt, apiKey);

  if (!analysis) {
    Logger.log('[ERROR] Gemini 未回傳內容');
    return;
  }

  Logger.log('[Gemini 回應]\n%s', analysis.substring(0, 500));

  // 3. 推 LINE
  const now = Utilities.formatDate(new Date(), 'Asia/Taipei', 'MM/dd HH:mm');
  const message = '📊 財經雷達摘要 ' + now + '\n\n' + analysis;
  pushLine_(message, lineToken, targetId);
}


// ── 讀取近期文章 ──────────────────────────────────────────────────────────

function getRecentArticles_(sheetName, hoursBack) {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    Logger.log('[ERROR] 找不到工作表：%s', sheetName);
    return [];
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  // 讀取所有資料（第 1 列為標頭，從第 2 列開始）
  // 欄位順序：A=日期, B=標題, C=分類, D=網址, E=內容
  const data   = sheet.getRange(2, 1, lastRow - 1, 5).getValues();
  const cutoff = new Date(Date.now() - hoursBack * 60 * 60 * 1000);

  const articles = [];
  data.forEach(function(row) {
    const dateVal = row[0];
    const title   = row[1] ? String(row[1]).trim() : '';
    const category = row[2] ? String(row[2]).trim() : '';
    if (!title) return;

    // 解析日期（可能是 Date 物件或字串）
    let rowDate;
    if (dateVal instanceof Date) {
      rowDate = dateVal;
    } else {
      rowDate = new Date(dateVal);
    }
    if (isNaN(rowDate.getTime()) || rowDate < cutoff) return;

    articles.push({ title: title, category: category });
  });

  return articles;
}


// ── 建立提示詞 ────────────────────────────────────────────────────────────

function buildPrompt_(articles, hoursBack) {
  const lines = [
    '以下是過去 ' + hoursBack + ' 小時內收錄的財經新聞，請用繁體中文分析：\n'
  ];

  articles.forEach(function(a, i) {
    const cat = a.category ? ' [' + a.category + ']' : '';
    lines.push((i + 1) + '. ' + a.title + cat);
  });

  lines.push('\n請提供：');
  lines.push('1. 最值得關注的 2-3 則新聞及其對台灣市場的潛在影響');
  lines.push('2. 整體市場情緒判斷（樂觀 / 謹慎 / 悲觀）');
  lines.push('3. 建議關注的後續指標或事件');
  lines.push('請簡潔，回覆控制在 400 字以內。');

  return lines.join('\n');
}


// ── 呼叫 Gemini API ───────────────────────────────────────────────────────

function callGemini_(prompt, apiKey) {
  const model   = 'gemini-2.0-flash';
  const url     = 'https://generativelanguage.googleapis.com/v1beta/models/'
                  + model + ':generateContent?key=' + apiKey;
  const payload = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens: 800, temperature: 0.4 }
  };

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    if (code !== 200) {
      Logger.log('[ERROR] Gemini API 回傳 %s: %s', code, resp.getContentText().substring(0, 300));
      return null;
    }

    const json     = JSON.parse(resp.getContentText());
    const text     = json.candidates &&
                     json.candidates[0] &&
                     json.candidates[0].content &&
                     json.candidates[0].content.parts &&
                     json.candidates[0].content.parts[0].text;
    return text || null;

  } catch (e) {
    Logger.log('[ERROR] Gemini 呼叫例外：%s', e.message);
    return null;
  }
}


// ── 推播 LINE ─────────────────────────────────────────────────────────────

function pushLine_(message, token, targetId) {
  const url     = 'https://api.line.me/v2/bot/message/push';
  const payload = {
    to: targetId,
    messages: [{ type: 'text', text: message.substring(0, 4990) }]
  };

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });

    const code = resp.getResponseCode();
    if (code === 200) {
      Logger.log('[OK] LINE 推播成功');
    } else {
      Logger.log('[ERROR] LINE 推播失敗 %s: %s', code, resp.getContentText());
    }
  } catch (e) {
    Logger.log('[ERROR] LINE 推播例外：%s', e.message);
  }
}
