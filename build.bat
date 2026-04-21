@echo off
cd /d "%~dp0"

echo ==^> Pre-compiling web/*.jsx -^> web/app.bundle.js
python build_web.py
if errorlevel 1 (
  echo Web build failed.
  exit /b 1
)

echo ==^> PyInstaller onedir build
pyinstaller --windowed --name ClaudeManager ^
  --icon icon.ico ^
  --hidden-import werkzeug.serving ^
  --collect-all webview ^
  --add-data "web;web" ^
  --noconfirm --clean ^
  app.py
if errorlevel 1 (
  echo PyInstaller build failed.
  exit /b 1
)
echo Done. App folder: dist\ClaudeManager\  (launch ClaudeManager.exe inside)
