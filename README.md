# Claude Manager

Claude Manager is a local desktop/Web UI for browsing, organizing, exporting, and resuming Claude Code conversation history from `~/.claude/projects`.

## Features

- Browse local Claude Code sessions by project, tag, archive, recent activity, and pinned status.
- Render conversation messages with Markdown support.
- Export sessions and transfer context between Claude Code and Codex.
- Launch Claude and Codex actions from the app, using local CLI tools on macOS/Linux or the Windows sidecar executable when present.

## Windows Build

```bat
build.bat
```

Output:

```text
dist\ClaudeManager\ClaudeManager.exe
```

## macOS Build

Install dependencies into the Python environment used for the build:

```bash
python3 -m pip install -r requirements-mac.txt
```

Build the app:

```bash
./build.sh
```

Useful build environment variables:

- `PYTHON=/path/to/python3`: choose the Python used by PyInstaller.
- `SKIP_WEB_BUILD=1`: reuse `web/app.bundle.js` when `npx` is unavailable.
- `PYINSTALLER_TARGET_ARCH=arm64` or `x86_64`: request a specific PyInstaller target architecture when supported by the Python runtime.

Typical local builds:

```bash
# Apple Silicon native build
PYTHON=/usr/bin/python3 SKIP_WEB_BUILD=1 ./build.sh

# Intel/Rosetta compatibility build, when an x86_64 Python is installed
PYTHON=/usr/local/bin/python3.12 SKIP_WEB_BUILD=1 ./build.sh
```

Output:

```text
dist/ClaudeManager.app
```

Release packages are usually copied to:

```text
dist/mac/ClaudeManager-macos-arm64.zip
dist/mac/ClaudeManager-macos-arm64.dmg
dist/mac/ClaudeManager-macos-x86_64.zip
dist/mac/ClaudeManager-macos-x86_64.dmg
```

## Runtime Notes

- macOS builds expect the local `claude` and `codex` CLIs to be installed and authenticated separately; the CLIs are not bundled.
- Default local server port is `8765`; override it with `CLAUDE_MANAGER_PORT`.
- If the preferred port is already in use, the app automatically selects an available local port before opening the UI.
- macOS packages are ad-hoc signed by PyInstaller, not notarized. On first launch, macOS may require right-clicking the app and choosing Open.
