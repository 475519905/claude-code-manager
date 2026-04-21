#!/usr/bin/env bash
# Build ClaudeManager.app on macOS.
#
# Requirements:
#   - Python 3.10+  (brew install python)
#   - pip install pyinstaller flask pywebview
#   - macOS built-ins `sips` and `iconutil` (used to build icon.icns from web/icon.png)
#
# Output:
#   dist/ClaudeManager.app   (drag into /Applications)

set -euo pipefail
cd "$(dirname "$0")"

echo "==> Building ClaudeManager.app"

# 1. Make an .icns from web/icon.png if we don't already have one.
if [[ ! -f icon.icns ]]; then
  if [[ ! -f web/icon.png ]]; then
    echo "!! web/icon.png missing — cannot generate icon.icns" >&2
    exit 1
  fi
  echo "    generating icon.icns from web/icon.png"
  TMPDIR=$(mktemp -d)
  ICONSET="$TMPDIR/icon.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 64 128 256 512; do
    sips -z "$size" "$size"      web/icon.png --out "$ICONSET/icon_${size}x${size}.png"      >/dev/null
    dbl=$((size * 2))
    sips -z "$dbl"  "$dbl"       web/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png"  >/dev/null
  done
  iconutil -c icns "$ICONSET" -o icon.icns
  rm -rf "$TMPDIR"
fi

# 2. Pre-compile web/*.jsx into a single app.bundle.js so the shipped app
#    doesn't have to run Babel in-browser at startup.
echo "==> Pre-compiling web/*.jsx -> web/app.bundle.js"
python3 build_web.py

# 3. Run PyInstaller (onedir, not onefile — onefile unpacks to /tmp on every
#    launch which costs 2-4s). Note `:` separator on macOS/Linux (Windows uses `;`).
pyinstaller --windowed --name ClaudeManager \
  --icon icon.icns \
  --hidden-import werkzeug.serving \
  --collect-all webview \
  --add-data "web:web" \
  --osx-bundle-identifier com.claudemanager.app \
  --noconfirm --clean \
  app.py

echo "==> Done. App bundle: dist/ClaudeManager.app"
echo "    (the raw binary is dist/ClaudeManager — launch the .app, not the binary)"
