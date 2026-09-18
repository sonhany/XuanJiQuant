@echo off
setlocal
cd /d "%~dp0.."

if /i "%~1"=="api" goto api
if /i "%~1"=="web" goto web
exit /b 2

:api
node server\index.mjs >> logs\backend-launcher-out.log 2>> logs\backend-launcher-err.log
exit /b %errorlevel%

:web
node node_modules\vite\bin\vite.js --host 127.0.0.1 --port 8888 --strictPort >> logs\frontend-launcher-out.log 2>> logs\frontend-launcher-err.log
exit /b %errorlevel%
