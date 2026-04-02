@echo off
REM Windows 工作排程器設定腳本
REM 設定每小時自動執行 perplexity_digest.py
REM 請用「以系統管理員身分執行」

set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set PYTHON=python
set TASK_NAME=FinancialRadar_PerplexityDigest

echo [設定] 建立每小時排程工作：%TASK_NAME%

schtasks /create /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT_DIR%perplexity_digest.py\"" ^
  /sc HOURLY ^
  /mo 1 ^
  /st 00:00 ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo [OK] 排程建立成功，每小時整點自動執行
    echo.
    echo 管理指令：
    echo   查看：schtasks /query /tn "%TASK_NAME%"
    echo   手動執行：schtasks /run /tn "%TASK_NAME%"
    echo   刪除：schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo [ERROR] 排程建立失敗，請確認以系統管理員身分執行
)
pause
