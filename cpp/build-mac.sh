#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="CodexManager"
MANAGER_KIND="${MANAGER_KIND:-codex}"
ARCH="${ARCH:-$(uname -m)}"
BUILD_DIR="${ROOT}/build-mac"
PACKAGE_DIR="${ROOT}/../dist/cpp/${APP_NAME}-macos-${ARCH}"
APP_SRC="${BUILD_DIR}/conv_manager_cpp.app"
APP_DST="${PACKAGE_DIR}/${APP_NAME}.app"
ZIP_PATH="${ROOT}/../dist/cpp/${APP_NAME}-macos-${ARCH}.zip"

cmake -S "${ROOT}" -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DMANAGER_KIND="${MANAGER_KIND}" \
  -DCMAKE_OSX_ARCHITECTURES="${ARCH}"
cmake --build "${BUILD_DIR}" --config Release

rm -rf "${PACKAGE_DIR}"
mkdir -p "${PACKAGE_DIR}"
ditto "${APP_SRC}" "${APP_DST}"
rm -rf "${APP_DST}/Contents/Resources/web"
mkdir -p "${APP_DST}/Contents/Resources"
ditto "${ROOT}/../web" "${APP_DST}/Contents/Resources/web"
if [[ -f "${ROOT}/../icon-512.png" ]]; then
  cp "${ROOT}/../icon-512.png" "${APP_DST}/Contents/Resources/icon-512.png"
fi

rm -f "${ZIP_PATH}"
(cd "${PACKAGE_DIR}" && ditto -c -k --sequesterRsrc --keepParent "${APP_NAME}.app" "${ZIP_PATH}")

echo "Built app: ${APP_DST}"
echo "Built zip: ${ZIP_PATH}"
