@echo off
chcp 65001 >nul
REM ============================================================
REM   AlphaCouncil2-AI 首次安装脚本
REM   用途: 检查环境 + 安装依赖 + 初始化数据
REM ============================================================
cd /d "%~dp0"
title AlphaCouncil2-AI 首次安装

echo ============================================================
echo   AlphaCouncil2-AI 首次安装
echo ============================================================
echo.

REM ─── 1. 检查 Node.js ────────────────────────
echo [1/5] 检查 Node.js...
where node >nul 2>nul
if errorlevel 1 (
    echo   [错误] 未找到 Node.js
    echo   请从 https://nodejs.org 安装 Node.js 18+ 后重试
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo   [OK] Node.js %%v

REM ─── 2. 检查 Python ─────────────────────────
echo [2/5] 检查 Python...
where python >nul 2>nul
if errorlevel 1 (
    echo   [错误] 未找到 Python
    echo   请从 https://python.org 安装 Python 3.10+ 后重试
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo   [OK] %%v

REM ─── 3. 安装 Node 依赖 ──────────────────────
echo [3/5] 安装 Node 依赖...
if not exist "node_modules" (
    call npm install
    if errorlevel 1 ( echo   [错误] npm install 失败 & pause & exit /b 1 )
    echo   [OK] Node 依赖安装完成
) else (
    echo   [OK] node_modules 已存在，跳过
)

REM ─── 4. 安装 Python 依赖 ────────────────────
echo [4/5] 安装 Python 依赖...
python -c "import pandas, numpy, scipy, akshare" >nul 2>nul
if errorlevel 1 (
    pip install -r requirements.txt
    if errorlevel 1 ( echo   [错误] pip install 失败 & pause & exit /b 1 )
    echo   [OK] Python 依赖安装完成
) else (
    echo   [OK] Python 依赖已就绪，跳过
)

REM ─── 5. 初始化数据 (可选) ───────────────────
echo [5/5] 检查数据...
if exist "data\quant.db" (
    echo   [OK] 数据库已存在 (data\quant.db)
    echo   如需重新初始化，运行: python scripts\seed.py
) else (
    echo   数据库不存在，是否现在初始化? (拉取约400只股票日K+财务, 约30分钟)
    echo   也可跳过，之后手动运行: python scripts\seed.py --limit 50
    set /p ans="立即初始化? [y/N]: "
    if /i "%ans%"=="y" (
        python scripts\seed.py --limit 50 --no-financial
        echo   [提示] 已初始化少量股票(仅日K)。完整数据请运行: python scripts\seed.py
    ) else (
        echo   [跳过] 请稍后运行 python scripts\seed.py 初始化数据
    )
)

echo.
echo ============================================================
echo   安装完成!
echo.
echo   下一步: 双击 start_all.bat 启动系统
echo   前端: http://localhost:3333
echo   后端: http://localhost:3334
echo ============================================================
pause
