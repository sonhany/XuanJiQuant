@echo off
chcp 65001 >nul
cd /d "%~dp0"
title XuanJiQuant Launcher

echo ============================================================
echo   XuanJiQuant starting...
echo ============================================================

if not exist "data\quant.db" (
    echo [ERROR] data\quant.db is missing.
    echo Run setup.bat or python scripts\seed.py first.
    pause
    exit /b 1
)

node scripts\start_services.mjs
if errorlevel 1 (
    echo.
    echo [ERROR] One or more services failed to start.
    echo Check logs\backend-launcher-err.log and logs\frontend-launcher-err.log.
    pause
    exit /b 1
)

echo.
echo Frontend: http://127.0.0.1:8888
echo Backend : http://127.0.0.1:8880
echo Logs    : logs\
echo ============================================================

start "" http://127.0.0.1:8888
timeout /t 2 >nul
