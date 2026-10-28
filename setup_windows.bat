@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m unittest -v
if errorlevel 1 goto fail
.venv\Scripts\python.exe configure.py
if errorlevel 1 goto fail
echo Setup finished. Run start_windows.bat to start the bot.
pause
exit /b 0
:fail
echo Setup failed. Do not share screenshots containing secrets.
pause
exit /b 1
