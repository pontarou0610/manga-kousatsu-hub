@echo off
REM Wrapper to auto-update glossaries before running Hugo.
REM Usage: hugo.cmd [hugo arguments...]

setlocal
set SCRIPT_DIR=%~dp0
set PS_SCRIPT=%SCRIPT_DIR%scripts\update_all_glossaries.py

if not exist "%PS_SCRIPT%" (
  echo [ERROR] update_all_glossaries.py not found at %PS_SCRIPT%
  exit /b 1
)

echo [INFO] Updating glossaries...
python "%PS_SCRIPT%"
if errorlevel 1 (
  echo [ERROR] Glossary update failed.
  exit /b %errorlevel%
)

echo [INFO] Running hugo %*
REM Call the real hugo.exe in PATH (different name to avoid recursion)
hugo.exe %*
exit /b %errorlevel%
