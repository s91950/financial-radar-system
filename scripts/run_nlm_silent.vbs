Set objShell = CreateObject("WScript.Shell")
objShell.Run "python D:\即時偵測系統claude\scripts\notebooklm_hourly.py >> D:\即時偵測系統claude\scripts\nlm_reports\run.log 2>&1", 0, False
