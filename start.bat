@echo off
rem Starts TorqueFlasher without a console window.
rem If nothing appears, run "py -3 gui.py" in a terminal in this folder to see the error.
cd /d "%~dp0"
set PYTHONUTF8=1
where pyw >nul 2>nul && (start "" pyw -3 gui.py & goto :eof)
where pythonw >nul 2>nul && (start "" pythonw gui.py & goto :eof)
echo Python 3 was not found. Install it from https://www.python.org
echo (tick "Add python.exe to PATH" during setup) and start this file again.
pause
