@echo off
rem Builds the Windows installer: installer\windows\Output\TorqueFlasher-<version>-Windows-Setup.exe
rem Needs: Python 3.10+ (python.org, "Add python.exe to PATH") and Inno Setup 6 (jrsoftware.org or
rem         "winget install JRSoftware.InnoSetup"). Internet for the first run (pip installs PyInstaller).
rem Use:   double-click, or run "installer\windows\build.bat" from the TorqueFlasher folder.
setlocal
cd /d "%~dp0..\.."

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python 3 not found: https://www.python.org & goto :fail)

echo == Python environment ==
if not exist build\venv %PY% -m venv build\venv || goto :fail
build\venv\Scripts\python -m pip install --quiet --upgrade pip pyinstaller || goto :fail

echo == Version ==
for /f "usebackq delims=" %%v in (`build\venv\Scripts\python installer\windows\make_version_info.py`) do set VER=%%v
if not defined VER goto :fail
echo %VER%

echo == PyInstaller ==
build\venv\Scripts\pyinstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller torqueflasher.spec || goto :fail

echo == Inno Setup ==
set ISCC=
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do if exist %%P set ISCC=%%P
if not defined ISCC (
  echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
  echo or with:  winget install JRSoftware.InnoSetup
  goto :fail
)
%ISCC% /Q /DAppVersion=%VER% installer\windows\TorqueFlasher.iss || goto :fail

echo.
echo Done: installer\windows\Output\TorqueFlasher-%VER%-Windows-Setup.exe
if not "%1"=="ci" pause
exit /b 0

:fail
echo.
echo Build FAILED (see the messages above).
if not "%1"=="ci" pause
exit /b 1
