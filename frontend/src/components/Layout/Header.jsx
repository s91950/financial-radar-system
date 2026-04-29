export default function Header({ title, subtitle, wsConnected, alertStats, onToggleNotifications }) {
  return (
    <header className="sticky top-0 z-30 bg-dark-900/80 backdrop-blur-xl border-b border-dark-700">
      <div className="flex items-center justify-between px-3 py-2.5 md:px-6 md:py-4">
        <div className="min-w-0">
          <h2 className="text-base md:text-xl font-bold text-white truncate">{title}</h2>
          {subtitle && <p className="hidden md:block text-sm text-dark-400 mt-0.5">{subtitle}</p>}
        </div>

        <div className="flex items-center gap-2 md:gap-4 shrink-0">
          {/* Connection Status */}
          <div className={`flex items-center gap-1.5 md:gap-2 px-2 md:px-3 py-1 md:py-1.5 rounded-full text-xs font-medium ${
            wsConnected
              ? 'bg-green-500/10 text-green-400 border border-green-500/20'
              : 'bg-red-500/10 text-red-400 border border-red-500/20'
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="hidden sm:inline">{wsConnected ? '即時連線' : '離線中'}</span>
          </div>

          {/* Alert Count */}
          {alertStats && alertStats.unread > 0 && (
            <button
              onClick={onToggleNotifications}
              className="relative p-2 rounded-lg hover:bg-dark-800 transition-colors"
            >
              <svg className="w-5 h-5 text-dark-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
              </svg>
              <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-bold">
                {alertStats.unread > 99 ? '99+' : alertStats.unread}
              </span>
            </button>
          )}

          {/* Current Time */}
          <div className="hidden md:block text-sm text-dark-400">
            {new Date().toLocaleDateString('zh-TW', { month: 'short', day: 'numeric', weekday: 'short' })}
          </div>
        </div>
      </div>
    </header>
  )
}
