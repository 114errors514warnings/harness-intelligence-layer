@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"

rem Quick launcher for the local HIL dashboard.
rem   open_dashboard.bat                            regenerate and open
rem   open_dashboard.bat --open-only                skip regeneration
rem   open_dashboard.bat --root D:\MY --window 14  pass through to the tool
rem
rem Set HIL_DASHBOARD_NO_OPEN=1 to render without launching a browser.

set "PYTHONPATH=%CD%\src"
set "DASH=%~dp0.hil\dashboard.html"

where python >nul 2>nul
if errorlevel 1 (
  echo [HIL] python not found on PATH.
  popd
  exit /b 1
)

if /I "%~1"=="--open-only" (
  shift
  goto open
)

echo [HIL] generating dashboard...
python "%~dp0tools\hil_dashboard.py" %*
if errorlevel 1 (
  echo [HIL] dashboard generation failed.
  popd
  exit /b 1
)

:open
if not exist "%DASH%" (
  echo [HIL] dashboard not found: %DASH%
  echo [HIL] run this script without --open-only first.
  popd
  exit /b 1
)

echo [HIL] %DASH%
if not "%HIL_DASHBOARD_NO_OPEN%"=="1" start "" "%DASH%"
popd
endlocal
