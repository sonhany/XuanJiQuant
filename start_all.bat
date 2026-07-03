@echo off
chcp 65001 >nul
REM ============================================================
REM   AlphaCouncil2-AI 一键启动
REM   启动: Node 后端(port 3334) + Vite 前端(port 3333)
REM   存储: SQLite (data/quant.db)，无需 Redis
REM ============================================================
cd /d "%~dp0"
title AlphaCouncil2-AI

echo ============================================================
echo   AlphaCouncil2-AI 启动中...
echo ============================================================

REM 检查数据是否存在
if not exist "data\quant.db" (
    echo   [提示] 数据库不存在，请先运行 setup.bat 或 python scripts\seed.py
    echo   现在用少量数据快速初始化? [10只股票, 约10秒]
    set /p ans="立即初始化? [Y/n]: "
    if /i not "%ans%"=="n" (
        python scripts\seed.py --limit 10 --no-financial
    )
)

REM 1. 启动 Node 后端
echo [1/2] 启动 Node 后端 (port 3334)...
start "AlphaCouncil-Backend" /MIN cmd /c "node server\index.mjs"

timeout /t 2 >nul

REM 2. 启动 Vite 前端
echo [2/2] 启动 Vite 前端 (port 3333)...
start "AlphaCouncil-Frontend" /MIN cmd /c "npx vite --host 0.0.0.0 --port 3333"

echo.
echo ============================================================
echo   启动完成!
echo.
echo   前端: http://localhost:3333
echo   后端: http://localhost:3334
echo.
echo   关闭: 退出两个最小化的命令行窗口
echo ============================================================
echo.
echo 3 秒后自动打开浏览器...
timeout /t 3 >nul
start http://localhost:3333
