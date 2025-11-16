@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
if "%VENV_DIR%"=="" (
  set "VENV_DIR=%ROOT_DIR%\.venv"
)
if "%PYTHON%"=="" (
  set "PYTHON=python"
)

where %PYTHON% >nul 2>nul
if errorlevel 1 (
  echo Unable to find Python interpreter '%PYTHON%'.
  exit /b 1
)

if not exist "%VENV_DIR%" (
  echo Creating virtual environment in %VENV_DIR%
  %PYTHON% -m venv "%VENV_DIR%"
) else (
  echo Reusing existing virtual environment in %VENV_DIR%
)

call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --upgrade pip
if exist "%ROOT_DIR%\requirements.txt" (
  python -m pip install -r "%ROOT_DIR%\requirements.txt"
)

echo Environment ready. Activate it with "call %VENV_DIR%\Scripts\activate.bat"
endlocal
