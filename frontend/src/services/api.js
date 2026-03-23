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
  analyzeAlert: (id) => api.post(`/radar/alerts/${id}/analyze`),
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
  getNotificationSettings: () => api.get('/settings/notifications'),
  updateNotification: (channel, data) => api.put(`/settings/notifications/${channel}`, data),
  testNotification: (channel) => api.post(`/settings/notifications/test/${channel}`),
  getGoogleSheetsStatus: () => api.get('/settings/google-sheets'),
  testGoogleSheets: () => api.post('/settings/google-sheets/test'),
}

export default api
