@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Stash Path Copy
cd /d "%~dp0"
set "EXITCODE=0"

if exist ".venv\Scripts\python.exe" (
  echo Using virtual environment: .venv
  echo.
  ".venv\Scripts\python.exe" -u app.py
  set "EXITCODE=!ERRORLEVEL!"
  goto :done
)

echo No .venv found - trying py -3, then python ...
echo.
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -u app.py
  set "EXITCODE=!ERRORLEVEL!"
  goto :done
)
where python >nul 2>&1
if not errorlevel 1 (
  python -u app.py
  set "EXITCODE=!ERRORLEVEL!"
  goto :done
)

echo.
echo ERROR: No Python found in PATH and no .venv\Scripts\python.exe
echo Create venv:  py -3 -m venv .venv
echo Then:         .venv\Scripts\pip install -r requirements.txt
echo.
set "EXITCODE=1"
goto :done

:done
if not "!EXITCODE!"=="0" (
  echo.
  echo FAILED - exit code !EXITCODE!
  echo.
  echo --------------------------------------------
  echo  Press any key to close this window.
  echo --------------------------------------------
  pause
  exit /b !EXITCODE!
)

exit /b 0
