"""Pre-compile the web/*.jsx files into a single web/app.bundle.js.

Before: the browser loaded @babel/standalone (~500 KB) at runtime and
transpiled eight JSX files on every app start.
After:  esbuild strips JSX at build time, so the WebView2 shell just
loads one plain-JS bundle. Cold start drops by 1–2 s.

All files keep top-level declarations (Icon, Tag, etc.) so later files
can reference them as implicit globals — same semantics as the
<script> tags in index.html.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

# Same order as the removed <script type="text/babel"> tags in index.html.
FILES = [
    "modal.jsx",
    "components.jsx",
    "sidebar.jsx",
    "usage_panel.jsx",
    "library.jsx",
    "conversation.jsx",
    "other_views.jsx",
    "app.jsx",
]

ESBUILD_VERSION = "0.24.2"


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def main() -> int:
    if not _has_cmd("npx") and not _has_cmd("npx.cmd"):
        print("!! node/npx not found on PATH — install Node.js first.", file=sys.stderr)
        return 1

    # Concatenate the ordered JSX files into one blob, feed through esbuild
    # in transform mode (--loader=jsx, no --bundle) so each file stays in
    # the global script scope.
    parts = []
    for name in FILES:
        src = WEB / name
        if not src.exists():
            print(f"!! missing {src}", file=sys.stderr)
            return 1
        parts.append(f"\n// ===== {name} =====\n")
        parts.append(src.read_text(encoding="utf-8"))
    combined = "".join(parts)

    # esbuild is invoked via npx so no global install is required. First run
    # downloads it into the npm cache (~8 MB, one-time); subsequent builds
    # resolve instantly from cache.
    npx = "npx.cmd" if sys.platform.startswith("win") else "npx"
    cmd = [
        npx, "--yes", f"esbuild@{ESBUILD_VERSION}",
        "--loader=jsx",
        "--target=es2020",
        "--minify",
    ]
    print(f"==> esbuild {' '.join(cmd[3:])}  ({sum(len(p) for p in parts)} chars in)")
    proc = subprocess.run(
        cmd, input=combined, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print("!! esbuild failed", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    out_path = WEB / "app.bundle.js"
    out_path.write_text(proc.stdout, encoding="utf-8")
    print(f"==> wrote {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
