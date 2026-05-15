@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [1/4] Checking Python...
set "BOOT_PY=python"
"%BOOT_PY%" --version >nul 2>&1
if errorlevel 1 (
  set "BOOT_PY=py"
  "%BOOT_PY%" -3 --version >nul 2>&1
  if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ and ensure "python" or "py" is on PATH.
    pause
    exit /b 1
  )
)

set "USE_VENV="
echo.
set /p USE_VENV=Do you want to use a virtual environment (.venv)? [Y/N]: 
if /I "%USE_VENV%"=="Y" goto use_venv
if /I "%USE_VENV%"=="N" goto no_venv
echo Invalid choice. Please run install.bat again and enter Y or N.
pause
exit /b 1

:use_venv
set "GLOBAL_PY_ARGS="
if not exist ".venv\Scripts\python.exe" (
  echo [2/4] Creating virtual environment...
  if /I "%BOOT_PY%"=="py" (
    "%BOOT_PY%" -3 -m venv .venv
  ) else (
    "%BOOT_PY%" -m venv .venv
  )
  if not exist ".venv\Scripts\python.exe" (
    echo Failed to create .venv
    pause
    exit /b 1
  )
) else (
  echo [2/4] Using existing .venv
)
set "PY_EXE=%CD%\.venv\Scripts\python.exe"
goto pip_prompt

:no_venv
echo [2/4] Using global Python environment.
if /I "%BOOT_PY%"=="py" (
  set "PY_EXE=py"
  set "GLOBAL_PY_ARGS=-3"
) else (
  set "PY_EXE=python"
  set "GLOBAL_PY_ARGS="
)

:pip_prompt
set "UPGRADE_PIP="
echo.
set /p UPGRADE_PIP=Do you want to upgrade pip before installing requirements? [Y/N]: 
if /I "%UPGRADE_PIP%"=="Y" goto install_step
if /I "%UPGRADE_PIP%"=="N" goto install_step
echo Invalid choice. Please run install.bat again and enter Y or N.
pause
exit /b 1

:install_step
echo [3/4] Installing dependencies...
if /I "%UPGRADE_PIP%"=="Y" (
  "%PY_EXE%" %GLOBAL_PY_ARGS% -m pip install --upgrade pip
  if errorlevel 1 (
    echo pip upgrade failed.
    pause
    exit /b 1
  )
)
"%PY_EXE%" %GLOBAL_PY_ARGS% -m pip install -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  pause
  exit /b 1
)

:install_done
echo.
echo [4/4] Setup finished.
echo Start the app with start.bat
pause
exit /b 0
