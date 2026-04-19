"""Claude Code 对话管理器 - 本地 Web UI."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

PROJECTS_DIR = Path.home() / ".claude" / "projects"
HOST = "127.0.0.1"
PORT = 8765
ACTIVE_WINDOW_SECS = 180  # file mtime within this window → session is "active"


def _resource_dir() -> Path:
    """Return path to the web/ directory (handles PyInstaller _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "web"
    return Path(__file__).resolve().parent / "web"


WEB_DIR = _resource_dir()

app = Flask(__name__, static_folder=None)


def _safe_project(name: str) -> Path:
    p = (PROJECTS_DIR / name).resolve()
    if PROJECTS_DIR.resolve() not in p.parents and p != PROJECTS_DIR.resolve():
        abort(400, "bad project")
    if not p.exists() or not p.is_dir():
        abort(404, "project not found")
    return p


def _safe_session(project: str, sid: str) -> Path:
    if "/" in sid or "\\" in sid or ".." in sid:
        abort(400, "bad sid")
    proj = _safe_project(project)
    f = proj / f"{sid}.jsonl"
    if not f.exists():
        abort(404, "session not found")
    return f


def _iter_jsonl(path: Path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "text":
                out.append(c.get("text", ""))
            elif t == "tool_use":
                out.append(f"[tool_use: {c.get('name','')}]")
            elif t == "tool_result":
                r = c.get("content")
                if isinstance(r, str):
                    out.append(f"[tool_result] {r}")
                elif isinstance(r, list):
                    for rc in r:
                        if isinstance(rc, dict) and rc.get("type") == "text":
                            out.append(f"[tool_result] {rc.get('text','')}")
        return "\n".join(out)
    return ""


def _summarize_session(project: str, path: Path) -> dict:
    sid = path.stem
    first_user_text = ""
    cwd = ""
    git_branch = ""
    first_ts = ""
    last_ts = ""
    user_count = 0
    assistant_count = 0
    summary = ""

    for obj in _iter_jsonl(path):
        t = obj.get("type")
        ts = obj.get("timestamp") or ""
        if t == "summary":
            summary = obj.get("summary", "") or summary
            continue
        if t == "user":
            if not cwd:
                cwd = obj.get("cwd", "") or cwd
            if not git_branch:
                git_branch = obj.get("gitBranch", "") or git_branch
            msg = obj.get("message") or {}
            text = _extract_text(msg.get("content"))
            is_meta = obj.get("isMeta") or False
            is_tool_result = bool(msg.get("content") and isinstance(msg["content"], list) and
                                  any(isinstance(c, dict) and c.get("type") == "tool_result" for c in msg["content"]))
            if text and not is_meta and not is_tool_result:
                if not first_user_text:
                    first_user_text = text[:200]
                user_count += 1
        elif t == "assistant":
            assistant_count += 1
        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

    try:
        size = path.stat().st_size
        mtime = path.stat().st_mtime
    except OSError:
        size, mtime = 0, 0

    active = (time.time() - mtime) < ACTIVE_WINDOW_SECS if mtime else False
    return {
        "project": project,
        "sid": sid,
        "cwd": cwd,
        "gitBranch": git_branch,
        "firstTs": first_ts,
        "lastTs": last_ts,
        "mtime": mtime,
        "size": size,
        "userCount": user_count,
        "assistantCount": assistant_count,
        "summary": summary or first_user_text,
        "preview": first_user_text,
        "active": active,
    }


@app.route("/api/sessions")
def api_sessions():
    if not PROJECTS_DIR.exists():
        return jsonify({"projects": [], "sessions": []})
    sessions = []
    projects = []
    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        proj_sessions = []
        for f in proj_dir.glob("*.jsonl"):
            try:
                proj_sessions.append(_summarize_session(proj_dir.name, f))
            except Exception as e:
                proj_sessions.append({
                    "project": proj_dir.name, "sid": f.stem, "error": str(e),
                    "mtime": f.stat().st_mtime, "size": f.stat().st_size,
                    "summary": "", "preview": "", "cwd": "", "firstTs": "", "lastTs": "",
                    "userCount": 0, "assistantCount": 0,
                })
        proj_sessions.sort(key=lambda s: s.get("mtime", 0), reverse=True)
        projects.append({"name": proj_dir.name, "count": len(proj_sessions)})
        sessions.extend(proj_sessions)
    sessions.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    return jsonify({"projects": projects, "sessions": sessions})


@app.route("/api/session/<project>/<sid>")
def api_session_detail(project: str, sid: str):
    f = _safe_session(project, sid)
    messages = []
    cwd = ""
    git_branch = ""
    for obj in _iter_jsonl(f):
        t = obj.get("type")
        if t == "summary":
            messages.append({"role": "summary", "text": obj.get("summary", ""), "ts": ""})
            continue
        if t not in ("user", "assistant"):
            continue
        if not cwd:
            cwd = obj.get("cwd", "") or cwd
        if not git_branch:
            git_branch = obj.get("gitBranch", "") or git_branch
        msg = obj.get("message") or {}
        text = _extract_text(msg.get("content"))
        if not text:
            continue
        is_meta = obj.get("isMeta") or False
        is_tool_result = bool(msg.get("content") and isinstance(msg["content"], list) and
                              any(isinstance(c, dict) and c.get("type") == "tool_result" for c in msg["content"]))
        messages.append({
            "role": t,
            "text": text,
            "ts": obj.get("timestamp", ""),
            "meta": is_meta,
            "toolResult": is_tool_result,
            "model": msg.get("model", ""),
        })
    return jsonify({
        "project": project, "sid": sid, "cwd": cwd, "gitBranch": git_branch,
        "messages": messages,
    })


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    ql = q.lower()
    results = []
    if not PROJECTS_DIR.exists():
        return jsonify({"results": []})
    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            hits = []
            for obj in _iter_jsonl(f):
                t = obj.get("type")
                if t not in ("user", "assistant", "summary"):
                    continue
                text = ""
                if t == "summary":
                    text = obj.get("summary", "")
                else:
                    msg = obj.get("message") or {}
                    text = _extract_text(msg.get("content"))
                if not text:
                    continue
                if ql in text.lower():
                    i = text.lower().find(ql)
                    s = max(0, i - 40)
                    e = min(len(text), i + len(q) + 80)
                    hits.append({"role": t, "snippet": text[s:e], "ts": obj.get("timestamp", "")})
                    if len(hits) >= 3:
                        break
            if hits:
                results.append({
                    "project": proj_dir.name,
                    "sid": f.stem,
                    "mtime": f.stat().st_mtime,
                    "hits": hits,
                })
    results.sort(key=lambda r: r.get("mtime", 0), reverse=True)
    return jsonify({"results": results})


@app.route("/api/export/<project>/<sid>")
def api_export(project: str, sid: str):
    fmt = request.args.get("format", "md").lower()
    f = _safe_session(project, sid)
    if fmt == "json":
        return send_file(f, as_attachment=True, download_name=f"{sid}.jsonl", mimetype="application/jsonl")
    # markdown
    lines = [f"# Claude Code Session {sid}", ""]
    cwd_shown = False
    for obj in _iter_jsonl(f):
        t = obj.get("type")
        if t == "summary":
            lines.append(f"> **Summary:** {obj.get('summary','')}")
            lines.append("")
            continue
        if t not in ("user", "assistant"):
            continue
        msg = obj.get("message") or {}
        text = _extract_text(msg.get("content"))
        if not text:
            continue
        if not cwd_shown and obj.get("cwd"):
            lines.insert(1, f"- cwd: `{obj.get('cwd')}`")
            lines.insert(2, f"- gitBranch: `{obj.get('gitBranch','')}`")
            lines.insert(3, "")
            cwd_shown = True
        is_tool_result = bool(msg.get("content") and isinstance(msg["content"], list) and
                              any(isinstance(c, dict) and c.get("type") == "tool_result" for c in msg["content"]))
        role = "🧑 User" if t == "user" else "🤖 Assistant"
        if is_tool_result:
            role = "🔧 Tool Result"
        ts = obj.get("timestamp", "")
        lines.append(f"## {role}  `{ts}`")
        lines.append("")
        lines.append(text)
        lines.append("")
    data = "\n".join(lines).encode("utf-8")
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=f"{sid}.md", mimetype="text/markdown")


@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    f = _safe_session(project, sid)
    try:
        f.unlink()
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    # also remove sidecar dir (file-history snapshots etc.) if present
    sidecar = f.parent / sid
    if sidecar.exists() and sidecar.is_dir():
        try:
            import shutil
            shutil.rmtree(sidecar, ignore_errors=True)
        except Exception:
            pass
    return jsonify({"ok": True})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    f = _safe_session(project, sid)
    cwd = ""
    for obj in _iter_jsonl(f):
        if obj.get("cwd"):
            cwd = obj["cwd"]
            break
    if not cwd or not Path(cwd).exists():
        return jsonify({"ok": False, "error": f"cwd not found: {cwd}"}), 400
    try:
        if sys.platform.startswith("win"):
            cmd = f'start "" cmd /k "cd /d \"{cwd}\" && claude --resume {sid}"'
            subprocess.Popen(cmd, shell=True)
        elif sys.platform == "darwin":
            script = f'tell app "Terminal" to do script "cd {json.dumps(cwd)} && claude --resume {sid}"'
            subprocess.Popen(["osascript", "-e", script])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e", f"bash -c 'cd {cwd!r} && claude --resume {sid}; exec bash'"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "cwd": cwd})


@app.route("/api/active")
def api_active():
    """Lightweight: return just the ids of sessions with recent mtime."""
    if not PROJECTS_DIR.exists():
        return jsonify({"active": []})
    now = time.time()
    active = []
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if (now - mtime) < ACTIVE_WINDOW_SECS:
                active.append({"project": proj_dir.name, "sid": f.stem, "mtime": mtime})
    return jsonify({"active": active, "windowSecs": ACTIVE_WINDOW_SECS})


@app.route("/api/stats")
def api_stats():
    """Aggregate session activity for the usage panel (heatmap + stats)."""
    if not PROJECTS_DIR.exists():
        return jsonify({"heatmap": [], "totals": {}})
    from collections import Counter
    day_count = Counter()            # date -> session count
    model_count = Counter()
    total_sessions = 0
    total_bytes = 0
    longest = 0
    most_msgs_day = ("", 0)
    streak_set = set()

    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            total_sessions += 1
            try:
                total_bytes += f.stat().st_size
            except OSError:
                pass
            first_ts = last_ts = ""
            msg_count = 0
            for obj in _iter_jsonl(f):
                t = obj.get("type")
                ts = obj.get("timestamp") or ""
                if t == "assistant":
                    m = (obj.get("message") or {}).get("model")
                    if m:
                        model_count[m] += 1
                if t in ("user", "assistant"):
                    msg_count += 1
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts
            if first_ts:
                day = first_ts[:10]
                day_count[day] += 1
                streak_set.add(day)
                if msg_count > most_msgs_day[1]:
                    most_msgs_day = (day, msg_count)
            if first_ts and last_ts:
                try:
                    d = (datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                         - datetime.fromisoformat(first_ts.replace("Z", "+00:00"))).total_seconds()
                    if d > longest:
                        longest = d
                except Exception:
                    pass

    today = datetime.utcnow().date()
    streak = 0
    cur = today
    while cur.isoformat() in streak_set:
        streak += 1
        cur = cur.fromordinal(cur.toordinal() - 1)

    # activity buckets for plan-limit panel
    today_iso = today.isoformat()
    day_sessions = day_count.get(today_iso, 0)
    week_start = today.fromordinal(today.toordinal() - today.weekday())  # Mon=0
    week_sessions = 0
    month_sessions = 0
    for d_iso, cnt in day_count.items():
        try:
            d = datetime.fromisoformat(d_iso).date()
        except Exception:
            continue
        if d >= week_start:
            week_sessions += cnt
        if d.year == today.year and d.month == today.month:
            month_sessions += cnt

    def _fmt_delta(seconds: int) -> str:
        if seconds <= 0:
            return "即将重置"
        h, rem = divmod(seconds, 3600)
        m, _ = divmod(rem, 60)
        if h >= 24:
            d = h // 24
            return f"{d} 天后重置"
        if h > 0:
            return f"{h}h {m}m 后重置"
        return f"{m} 分钟后重置"

    now = datetime.utcnow()
    next_midnight = datetime.combine(today.fromordinal(today.toordinal() + 1), datetime.min.time())
    days_to_sunday = (6 - today.weekday()) % 7 or 7
    next_sunday = datetime.combine(today.fromordinal(today.toordinal() + days_to_sunday), datetime.min.time())
    if today.month == 12:
        first_next = today.replace(year=today.year + 1, month=1, day=1)
    else:
        first_next = today.replace(month=today.month + 1, day=1)
    next_month = datetime.combine(first_next, datetime.min.time())

    # heatmap: 53 weeks x 7 days ending today
    import math
    weeks = 53
    from_date = today.fromordinal(today.toordinal() - weeks * 7 + 1)
    maxv = max(day_count.values()) if day_count else 1
    # build 7 x weeks grid, day 0 = Sunday
    grid = [[0] * weeks for _ in range(7)]
    for i in range(weeks * 7):
        d = from_date.fromordinal(from_date.toordinal() + i)
        cnt = day_count.get(d.isoformat(), 0)
        w = i // 7
        dow = d.weekday()  # Mon=0..Sun=6
        dow = (dow + 1) % 7  # shift so Sun=0 (Mon=1) to match common heatmap
        if not cnt:
            level = 0
        else:
            level = min(4, 1 + math.floor(cnt / max(1, maxv) * 3.999))
        grid[dow][w] = level

    longest_txt = ""
    if longest:
        h, m = divmod(int(longest) // 60, 60)
        d, h = divmod(h, 24)
        parts = []
        if d: parts.append(f"{d}d")
        if h: parts.append(f"{h}h")
        parts.append(f"{m}m")
        longest_txt = " ".join(parts)

    fav_model = model_count.most_common(1)
    totals = {
        "favoriteModel": fav_model[0][0].replace("claude-", "").replace("-", " ") if fav_model else "",
        "totalTokens": f"{(total_bytes / 4 / 1_000_000):.1f}m" if total_bytes else "0",
        "sessions": total_sessions,
        "longest": longest_txt or "—",
        "mostActiveDay": most_msgs_day[0] or "—",
        "streak": f"{streak} day{'s' if streak != 1 else ''}",
    }
    plans = [
        {"label": "今日会话", "count": day_sessions, "cap": 20, "reset": _fmt_delta(int((next_midnight - now).total_seconds())), "sub": "每日"},
        {"label": "本周会话", "count": week_sessions, "cap": 80, "reset": _fmt_delta(int((next_sunday - now).total_seconds())), "sub": "每周"},
        {"label": "本月会话", "count": month_sessions, "cap": 300, "reset": _fmt_delta(int((next_month - now).total_seconds())), "sub": "每月"},
        {"label": "累计会话", "count": total_sessions, "cap": max(total_sessions, 500), "reset": "不重置", "sub": "全部历史"},
    ]
    return jsonify({"heatmap": grid, "totals": totals, "plans": plans})


def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/")
def index():
    return _no_cache(send_from_directory(str(WEB_DIR), "index.html"))


@app.route("/<path:filename>")
def static_file(filename: str):
    if ".." in filename or filename.startswith("/"):
        abort(404)
    target = (WEB_DIR / filename).resolve()
    if WEB_DIR.resolve() not in target.parents:
        abort(404)
    if not target.is_file():
        abort(404)
    return _no_cache(send_from_directory(str(WEB_DIR), filename))


def _run_flask():
    from werkzeug.serving import make_server
    srv = make_server(HOST, PORT, app, threaded=True)
    srv.serve_forever()


def _wait_for_server(timeout: float = 5.0) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    print("Claude Conversation Manager")
    print(f"Projects dir: {PROJECTS_DIR}")
    print(f"Serving on http://{HOST}:{PORT}")

    threading.Thread(target=_run_flask, daemon=True).start()
    _wait_for_server()

    # Prefer a native window via pywebview. Fall back to the default browser
    # if pywebview or its backend (e.g. WebView2 runtime) is unavailable.
    use_browser = "--browser" in sys.argv
    if not use_browser:
        try:
            import webview  # type: ignore
            webview.create_window(
                "Claude 对话管理器",
                f"http://{HOST}:{PORT}",
                width=1920, height=1260,  # 1.5x of 1280x840 to pair with CSS zoom
                min_size=(1280, 800),
                text_select=True,
            )
            webview.start()
            return
        except Exception as e:
            print(f"pywebview unavailable ({e}); falling back to browser…")

    threading.Thread(
        target=lambda: (time.sleep(0.3), webbrowser.open(f"http://{HOST}:{PORT}")),
        daemon=True,
    ).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
