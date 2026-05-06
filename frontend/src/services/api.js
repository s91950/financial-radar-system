import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

// --- Radar APIs ---
export const radarAPI = {
  getAlerts: (params) => api.get('/radar/alerts', { params }),
  getAlertStats: () => api.get('/radar/alerts/stats'),
  markRead: (id) => api.put(`/radar/alerts/${id}/read`),
  markAllRead: () => api.put('/radar/alerts/read-all'),
  getMarketData: () => api.get('/radar/market'),
  getMarketCategories: () => api.get('/radar/market/categories'),
  getMarketHistory: (symbol, period = '5d', interval = '1h') =>
    api.get(`/radar/market/history/${encodeURIComponent(symbol)}`, { params: { period, interval } }),
  getTWSEData: () => api.get('/radar/market/twse'),
  addWatchlistItem: (data) => api.post('/radar/market/watchlist', data),
  updateWatchlistItem: (id, data) => api.put(`/radar/market/watchlist/${id}`, data),
  deleteWatchlistItem: (id) => api.delete(`/radar/market/watchlist/${id}`),
  // Signal conditions
  getConditions: (itemId) => api.get(`/radar/market/watchlist/${itemId}/conditions`),
  createCondition: (itemId, data) => api.post(`/radar/market/watchlist/${itemId}/conditions`, data),
  updateCondition: (condId, data) => api.put(`/radar/market/conditions/${condId}`, data),
  deleteCondition: (condId) => api.delete(`/radar/market/conditions/${condId}`),
  // Alert actions
  deleteAlert: (id) => api.delete(`/radar/alerts/${id}`),
  toggleSaveAlert: (id) => api.put(`/radar/alerts/${id}/save`),
  analyzeAlert: (id) => api.post(`/radar/alerts/${id}/analyze`),
  triggerScan: () => api.post('/radar/scan'),
  getNlmReport: () => api.get('/radar/notebooklm-report'),
  getNlmYtReport: () => api.get('/radar/notebooklm-yt-report'),
  listNlmReports: (type = 'news') => api.get('/radar/notebooklm-reports', { params: { report_type: type } }),
  getNlmReportById: (id) => api.get(`/radar/notebooklm-reports/${id}`),
  // Gemini 分析報告
  getGeminiReport: () => api.get('/radar/gemini-report'),
  getGeminiYtReport: () => api.get('/radar/gemini-yt-report'),
  listGeminiReports: (type = 'gemini_news') => api.get('/radar/gemini-reports', { params: { report_type: type } }),
  getGeminiReportById: (id) => api.get(`/radar/gemini-reports/${id}`),
  triggerGeminiAnalysis: () => api.post('/radar/gemini-analyze'),
}

// --- Search APIs ---
export const searchAPI = {
  searchTopic: (data) => api.post('/search/topic', data),
  analyzeTopic: (data) => api.post('/search/topic/analyze', data),
  quickSearch: (q, hoursBack = 24) => api.get('/search/quick', { params: { q, hours_back: hoursBack } }),
  getPositions: () => api.get('/search/positions'),
}

// --- News Database APIs ---
export const newsAPI = {
  getArticles: (params) => api.get('/news/articles', { params }),
  getArticle: (id) => api.get(`/news/articles/${id}`),
  updateArticle: (id, data) => api.put(`/news/articles/${id}`, data),
  deleteArticle: (id) => api.delete(`/news/articles/${id}`),
  manualFetch: (data) => api.post('/news/fetch', data),
  saveSelected: (data) => api.post('/news/save-selected', data),
  getSources: () => api.get('/news/sources'),
  getKeywords: () => api.get('/news/keywords'),
  getSentiment: () => api.get('/news/sentiment'),
  exportArticles: (params) => api.get('/news/export', { params }),
  getCategories: () => api.get('/news/categories'),
}

// --- Settings APIs ---
export const settingsAPI = {
  getSources: () => api.get('/settings/sources'),
  createSource: (data) => api.post('/settings/sources', data),
  updateSource: (id, data) => api.put(`/settings/sources/${id}`, data),
  deleteSource: (id) => api.delete(`/settings/sources/${id}`),
  reorderSources: (order) => api.put('/settings/sources/reorder', order),
  getNotificationSettings: () => api.get('/settings/notifications'),
  updateNotification: (channel, data) => api.put(`/settings/notifications/${channel}`, data),
  testNotification: (channel) => api.post(`/settings/notifications/test/${channel}`),
  getLineStatus: () => api.get('/settings/line-status'),
  getGoogleSheetsStatus: () => api.get('/settings/google-sheets'),
  testGoogleSheets: () => api.post('/settings/google-sheets/test'),
  getAIModel: () => api.get('/settings/ai-model'),
  updateAIModel: (model) => api.put('/settings/ai-model', { model }),
  getRadarTopics: () => api.get('/settings/radar-topics'),
  updateRadarTopics: (topics, hours_back = 24, interval_minutes = null, topics_us = [], rss_only = false, exclusion_keywords = []) => api.put('/settings/radar-topics', { topics, hours_back, interval_minutes, topics_us, rss_only, exclusion_keywords }),
  getSeverityKeywords: () => api.get('/settings/severity-keywords'),
  updateSeverityKeywords: (data) => api.put('/settings/severity-keywords', data),
  testRssSource: (id) => api.post(`/settings/sources/${id}/test-rss`),
  getTopicCategories: () => api.get('/settings/radar-topic-categories'),
  updateTopicCategories: (categories) => api.put('/settings/radar-topic-categories', { categories }),
  getSeverityRules: () => api.get('/settings/severity-rules'),
  updateSeverityRules: (rules) => api.put('/settings/severity-rules', { rules }),
  getFinanceFilter: () => api.get('/settings/finance-filter'),
  updateFinanceFilter: (enabled, threshold) => api.put('/settings/finance-filter', { enabled, threshold }),
  getRssPriority: () => api.get('/settings/rss-priority'),
  updateRssPriority: (min_articles) => api.put('/settings/rss-priority', { min_articles }),
  getGnCriticalOnly: () => api.get('/settings/gn-critical-only'),
  updateGnCriticalOnly: (enabled) => api.put('/settings/gn-critical-only', { enabled }),
  getSourceHealthThreshold: () => api.get('/settings/source-health-threshold'),
  updateSourceHealthThreshold: (hours) => api.put('/settings/source-health-threshold', { hours }),
  getSourceHealth: () => api.get('/settings/source-health'),
}

// --- Topic Tracking APIs ---
export const topicsAPI = {
  getTopics: () => api.get('/topics/'),
  createTopic: (data) => api.post('/topics/', data),
  updateTopic: (id, data) => api.put(`/topics/${id}`, data),
  deleteTopic: (id) => api.delete(`/topics/${id}`),
  getArticles: (id, params) => api.get(`/topics/${id}/articles`, { params }),
  searchAndImport: (id, data) => api.post(`/topics/${id}/search`, data),
  deleteArticle: (topicId, articleId) => api.delete(`/topics/${topicId}/articles/${articleId}`),
}

// --- Research Reports APIs ---
export const reportsAPI = {
  getReports: (params) => api.get('/research/reports', { params }),
  updateReport: (id, data) => api.put(`/research/${id}`, data),
  deleteReport: (id) => api.delete(`/research/${id}`),
  manualFetch: (data) => api.post('/research/fetch', data),
  saveSelected: (data) => api.post('/research/save-selected', data),
  getInstitutions: () => api.get('/research/institutions'),
}

// --- YouTube Channel Monitor APIs ---
export const youtubeAPI = {
  getChannels: () => api.get('/youtube/channels'),
  addChannel: (data) => api.post('/youtube/channels', data),
  updateChannel: (id, data) => api.put(`/youtube/channels/${id}`, data),
  deleteChannel: (id) => api.delete(`/youtube/channels/${id}`),
  checkChannel: (id) => api.post(`/youtube/channels/${id}/check`),
  checkAll: () => api.post('/youtube/check-all'),
  getVideos: (params) => api.get('/youtube/videos', { params }),
  getNewCount: () => api.get('/youtube/new-count'),
  markSeen: (id) => api.put(`/youtube/videos/${id}/seen`),
  markAllSeen: (channelId) => api.put('/youtube/videos/mark-all-seen', null, {
    params: channelId ? { channel_id: channelId } : {},
  }),
}

// --- Utility ---

/**
 * Resolve a URL to its final destination (follow HTTP redirects).
 * Useful for converting RSS feed redirect URLs into actual article URLs
 * that AI tools like Gemini can read directly.
 */
export async function resolveUrl(url) {
  if (!url) return url
  try {
    const { data } = await api.get('/utils/resolve-url', { params: { url }, timeout: 10000 })
    return data.url
  } catch {
    return url
  }
}

/**
 * Copy text to clipboard.
 * Uses navigator.clipboard when available (HTTPS / localhost).
 * Falls back to document.execCommand('copy') for HTTP environments (e.g. VM on port 80).
 */
export function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text)
  }
  return new Promise((resolve, reject) => {
    const el = document.createElement('textarea')
    el.value = text
    el.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0'
    document.body.appendChild(el)
    el.focus()
    el.select()
    try {
      const ok = document.execCommand('copy')
      document.body.removeChild(el)
      ok ? resolve() : reject(new Error('execCommand failed'))
    } catch (err) {
      document.body.removeChild(el)
      reject(err)
    }
  })
}

export default api
