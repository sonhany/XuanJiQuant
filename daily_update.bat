@echo off
chcp 65001 >nul
REM ============================================================
REM   AlphaCouncil2-AI 每日数据更新
REM   用途: 收盘后增量刷新 K线 (+ 可选财务)
REM   建议: 每个交易日 17:00 后运行
REM ============================================================
cd /d "%~dp0"
title AlphaCouncil 每日更新

echo ============================================================
echo   AlphaCouncil2-AI 每日数据更新
echo   时间: %date% %time%
echo ============================================================
echo.

echo [1] 增量更新 K线 (约30分钟，全A股最新交易日)...
python scripts\daily_update.py
if errorlevel 1 (
    echo   [错误] K线更新失败，请检查网络
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   K线更新完成!
echo.
echo   如需刷新财务数据 (季度任务，约5小时):
echo     python scripts\daily_update.py --financial
echo.
echo   如需重新评估因子有效性 (约30分钟):
echo     python scripts\evaluate_factors.py
echo ============================================================
echo.
pause
