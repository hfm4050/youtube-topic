@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" http://localhost:5180
python app\server.py --port 5180
pause
