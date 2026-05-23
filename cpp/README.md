# C++ backend prototype

This is a native backend for the existing web UI. It focuses on the expensive
paths first: session discovery, JSONL parsing, conversation details, search,
exports, costs, stats, and active-session polling.

Build on Windows:

```bat
build.bat
```

Run:

```bat
build\conv_manager_cpp.exe
```

On Windows the default UI is a standalone WebView2 desktop window. It starts at
2560x1440 and uses the local C++ HTTP server internally.

Useful options:

```text
--port 8766       Choose a starting port. If busy, the server tries the next ports.
--web PATH        Serve an alternate web directory.
--browser         Open the UI in the default browser instead of the desktop window.
--window          Open the standalone desktop window explicitly.
--no-open         Run the local server only.
```

The Python app remains untouched. This prototype stores its index separately in
`~/.codex_conv_manager_cpp/index.json`, so it will not corrupt the Python cache.

Implemented endpoints:

```text
GET  /
GET  /api/sessions
POST /api/refresh
GET  /api/session/<project>/<sid>
GET  /api/search?q=...
GET  /api/export/<project>/<sid>?format=md|json
POST /api/delete
POST /api/open-cwd
GET  /api/costs
GET  /api/stats
GET  /api/active
GET  /api/account
GET  /api/auth-status
POST /api/notify
```

Login endpoints are intentionally kept as privacy-safe placeholders. They do
not start `codex login` or `claude login`.

CLI launch and cross-agent transfer endpoints are currently conservative stubs.
The C++ service is meant to validate the performance win before porting those
side-effect-heavy flows.
