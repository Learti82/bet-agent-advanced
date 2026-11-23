@echo off
REM MatchEdge Local - one-command start for Windows.
REM   start.bat            install what is missing, build the UI, import data on first run, start the app
REM   start.bat --import   re-download the dataset, then start
REM   start.bat --test     run the test suites
setlocal
cd /d "%~dp0"
set "PORT=8000"
if not "%MATCHEDGE_PORT%"=="" set "PORT=%MATCHEDGE_PORT%"
set "MODE=%~1"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required: https://www.python.org/downloads/
  echo During installation tick "Add python.exe to PATH", then open a NEW terminal and run start.bat again.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 exit /b 1
)
set "VPY=%CD%\.venv\Scripts\python.exe"
if not exist ".venv\.installed" (
  echo Installing Python packages - first run only, this takes a minute...
  "%VPY%" -m pip install --quiet --upgrade pip
  "%VPY%" -m pip install --quiet -r backend\requirements.txt
  if errorlevel 1 exit /b 1
  echo ok> ".venv\.installed"
)

if /i "%MODE%"=="--test" (
  pushd backend
  "%VPY%" -m pytest
  popd
  pushd frontend
  if not exist node_modules call npm install --no-audit --no-fund
  call npx vitest run
  popd
  exit /b 0
)

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo Node.js 18 or newer is required to build the interface: https://nodejs.org/
    echo Install the LTS version, open a NEW terminal and run start.bat again.
    exit /b 1
  )
  echo Building the interface - first run only...
  pushd frontend
  if not exist node_modules call npm install --no-audit --no-fund
  call npm run build
  if errorlevel 1 (
    popd
    exit /b 1
  )
  popd
)

set "DO_IMPORT="
if /i "%MODE%"=="--import" set "DO_IMPORT=1"
if not exist "data\matchedge.sqlite3" set "DO_IMPORT=1"
pushd backend
if defined DO_IMPORT (
  echo Importing the Open-Matchday dataset - free, no API key...
  "%VPY%" -m matchedge import
  if errorlevel 1 echo Import failed - you can retry from the Data sources page in the app.
)
echo.
echo MatchEdge Local: http://127.0.0.1:%PORT%   - keep this window open, press Ctrl+C to stop
"%VPY%" -m matchedge serve --host 127.0.0.1 --port %PORT% --open
popd
