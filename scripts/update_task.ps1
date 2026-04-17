# 更新 NotebookLM 排程工作：改用 bat 檔直接執行，確保 Python 路徑正確
$task = Get-ScheduledTask | Where-Object { $_.TaskName -like "*Notebook*" } | Select-Object -First 1
if (-not $task) {
    Write-Host "找不到 NotebookLM 工作，嘗試重新建立..."
}

$python = "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe"
$script = "D:\即時偵測系統claude\scripts\notebooklm_hourly.py"
$log    = "D:\即時偵測系統claude\scripts\nlm_reports\run.log"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-X utf8 `"$script`"" `
    -WorkingDirectory "D:\即時偵測系統claude\scripts"

if ($task) {
    Set-ScheduledTask -TaskName $task.TaskName -Action $action
    Write-Host "已更新工作 Action：$($task.TaskName)"
} else {
    # 重新建立（每小時從 12:00 起）
    $trigger = New-ScheduledTaskTrigger -Daily -At "12:00" -RepetitionInterval (New-TimeSpan -Hours 1)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask `
        -TaskName "NotebookLM 每小時執行" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -RunLevel Highest
    Write-Host "已重新建立工作"
}

# 立刻手動觸發一次測試
Write-Host "手動觸發工作..."
Get-ScheduledTask | Where-Object { $_.TaskName -like "*Notebook*" } | Start-ScheduledTask
Write-Host "已觸發，請稍候 30 秒後查看 nlm_reports/ 是否有新報告"
