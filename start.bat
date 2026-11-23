@echo off
REM MatchEdge Local - one-command start (Windows).  start.bat [--import | --test]
setlocal
cd /d "%~dp0"
set PORT=8000
if not "%MATCHEDGE_PORT%"=="" set PORT=%MATCHEDGE_PORT%

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" || (echo Python 3.10+ is required: https://www.python.org/downloads/ & exit /b 1)

if not exist .venv ( echo Creating Python virtual environment... & %PY% -m venv .venv )
set VPY=%cd%\.venv\Scripts\python.exe
if not exist .venv\.installed (
  echo Installing Python packages...
  "%VPY%" -m pip install --quiet --upgrade pip
  "%VPY%" -m pip install --quiet -r backend\requirements.txt || exit /b 1
  echo ok> .venv\.installed
)

if "%1"=="--test" (
  pushd backend & "%VPY%" -m pytest & popd
  pushd frontend & (if not exist node_modules call npm install --no-audit --no-fund) & call npx vitest run & popd
  exit /b 0
)

if not exist frontend\dist\index.html (
  where npm >nul 2>nul || (echo Node.js 18+ is required to build the interface: https://nodejs.org/ & exit /b 1)
  echo Building the interface...
  pushd frontend
  if not exist node_modules call npm install --no-audit --no-fund
  call npm run build
  popd
)

pushd backend
if "%1"=="--import" goto doimport
if not exist ..\data\matchedge.sqlite3 goto doimport
goto serve
:doimport
echo Importing the Open-Matchday dataset (free, no API key)...
"%VPY%" -m matchedge import || echo Import failed - retry from Data sources in the app.
:serve
echo MatchEdge Local - http://127.0.0.1:%PORT%  (Ctrl+C to stop)
start "" http://127.0.0.1:%PORT%
"%VPY%" -m matchedge serve --host 127.0.0.1 --port %PORT%
popd
