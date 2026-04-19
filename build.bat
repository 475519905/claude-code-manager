@echo off
cd /d "%~dp0"
echo Building ClaudeManager.exe ...
pyinstaller --onefile --windowed --name ClaudeManager ^
  --icon icon.ico ^
  --hidden-import werkzeug.serving ^
  --collect-all webview ^
  --add-data "web;web" ^
  --noconfirm --clean ^
  app.py
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo Done. EXE: dist\ClaudeManager.exe
