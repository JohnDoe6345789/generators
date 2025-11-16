@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
if "%VENV_DIR%"=="" set "VENV_DIR=%ROOT_DIR%\.venv"
if "%1"=="" (
  set "TARGET=tests"
) else (
  set "TARGET=%1"
  shift
)

if not exist "%VENV_DIR%" (
  echo Virtual environment not found at %VENV_DIR%.
  echo Run setup.bat first or set VENV_DIR to a valid environment.
  exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
set "PYTHONPATH=%ROOT_DIR%\src;%PYTHONPATH%"

if /I "%TARGET%"=="tests" (
  python -m pytest "%ROOT_DIR%\tests" %*
  goto :eof
) else if /I "%TARGET%"=="generator" (
  python -m generators.simplyretro_d8_generator %*
  goto :eof
) else if /I "%TARGET%"=="launcher" (
  python -m gui.workflow_launcher %*
  goto :eof
) else if /I "%TARGET%"=="module" (
  if "%1"=="" (
    echo Please provide a module path, e.g. generators.jigsaw_generator
    exit /b 1
  )
  set "MODULE=%1"
  shift
  python -m %MODULE% %*
  goto :eof
) else if /I "%TARGET%"=="help" (
  echo Usage: run.bat [tests^|generator^|module^|help] [args]
  echo(  tests      Run pytest for the repository.
  echo(  generator  Execute the SimplyRetro D8 generator.
  echo(  launcher   Launch the Tk workflow control center.
  echo(  module     Run an arbitrary module under src/.
  goto :eof
)

echo Unknown command: %TARGET%
exit /b 1

endlocal
