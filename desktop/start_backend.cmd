@echo off
setlocal EnableExtensions
set "INSTALL_DIR=%~dp0.."
for %%I in ("%INSTALL_DIR%") do set "INSTALL_DIR=%%~fI"
set "RUNTIME=%INSTALL_DIR%\runtime"
set "PYTHONHOME=%RUNTIME%"
set "PATH=%RUNTIME%;%RUNTIME%\Scripts;%PATH%"
if not defined TENDER_INSTALL_DIR set "TENDER_INSTALL_DIR=%INSTALL_DIR%"
if not defined TENDER_DATA_DIR set "TENDER_DATA_DIR=%LOCALAPPDATA%\TenderAgent\data"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"
if not defined PYTHONDONTWRITEBYTECODE set "PYTHONDONTWRITEBYTECODE=1"
if not defined PYTHONPYCACHEPREFIX set "PYTHONPYCACHEPREFIX=%TENDER_DATA_DIR%\pycache"
if not exist "%TENDER_DATA_DIR%" mkdir "%TENDER_DATA_DIR%" 2>nul
"%RUNTIME%\python.exe" -u "%~dp0backend_launcher.py" %*
exit /b %ERRORLEVEL%
