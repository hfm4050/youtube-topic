@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Content Studio (localhost:5180)
rem already running? then just open the browser
netstat -ano | findstr /R /C:":5180 .*LISTENING" >nul && (start "" http://localhost:5180 & exit /b)
start "" /min cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:5180"
python app\server.py --port 5180
echo.
echo Server stopped. Press any key to close.
pause >nul
