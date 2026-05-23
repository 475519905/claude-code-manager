#!/usr/bin/env bash
# Build CodexManager.app on macOS.
#
# Requirements:
#   - Python 3.9+
#   - "$PYTHON" -m pip install -r requirements-mac.txt
#   - Optional: node/npx to regenerate web/app.bundle.js
#
# Environment:
#   PYTHON=/path/to/python3          choose the Python used for the build
#   SKIP_WEB_BUILD=1                 reuse web/app.bundle.js without running npx
#   PYINSTALLER_TARGET_ARCH=x86_64   optional PyInstaller target arch
#
# Output:
#   dist/CodexManager.app

set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="CodexManager"
PYTHON_BIN="${PYTHON:-python3}"
PYI=("$PYTHON_BIN" -m PyInstaller)

echo "==> Building ${APP_NAME}.app"
echo "==> Python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "!! Python 3.9+ is required. Set PYTHON=/path/to/python3.9+." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "!! PyInstaller is missing. Run: $PYTHON_BIN -m pip install -r requirements-mac.txt" >&2
  exit 1
fi

# Build icon.icns from web/icon.png if needed.
if [[ ! -f icon.icns ]]; then
  if [[ ! -f web/icon.png ]]; then
    echo "!! web/icon.png missing; cannot generate icon.icns" >&2
    exit 1
  fi
  echo "==> Generating icon.icns from web/icon.png"
  TMP_BUILD_DIR=$(mktemp -d)
  ICONSET="$TMP_BUILD_DIR/icon.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 64 128 256 512; do
    sips -z "$size" "$size" web/icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    dbl=$((size * 2))
    sips -z "$dbl" "$dbl" web/icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o icon.icns
  rm -rf "$TMP_BUILD_DIR"
fi

if [[ "${SKIP_WEB_BUILD:-0}" == "1" ]]; then
  if [[ ! -f web/app.bundle.js ]]; then
    echo "!! SKIP_WEB_BUILD=1 but web/app.bundle.js is missing" >&2
    exit 1
  fi
  echo "==> Reusing web/app.bundle.js"
elif command -v npx >/dev/null 2>&1; then
  echo "==> Pre-compiling web/*.jsx -> web/app.bundle.js"
  "$PYTHON_BIN" build_web.py
elif [[ -f web/app.bundle.js ]]; then
  echo "==> npx not found; reusing existing web/app.bundle.js"
else
  echo "!! npx not found and web/app.bundle.js is missing" >&2
  exit 1
fi

if [[ -n "${PYINSTALLER_TARGET_ARCH:-}" ]]; then
  "${PYI[@]}" --windowed --name "$APP_NAME" \
    --icon icon.icns \
    --hidden-import werkzeug.serving \
    --collect-all webview \
    --add-data "web:web" \
    --osx-bundle-identifier com.codexmanager.app \
    --target-arch "$PYINSTALLER_TARGET_ARCH" \
    --noconfirm --clean \
    app.py
else
  "${PYI[@]}" --windowed --name "$APP_NAME" \
    --icon icon.icns \
    --hidden-import werkzeug.serving \
    --collect-all webview \
    --add-data "web:web" \
    --osx-bundle-identifier com.codexmanager.app \
    --noconfirm --clean \
    app.py
fi

echo "==> Done. App bundle: dist/${APP_NAME}.app"
