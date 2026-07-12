@echo off
rem 雙擊啟動:背景跑服務 + 系統匣圖示 + 可叫出的看板預覽視窗(無主控台)。
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m app.desktop
