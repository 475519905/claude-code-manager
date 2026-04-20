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


import re as _re
_CMD_NAME_RE = _re.compile(r"<command-name>\s*(\S+?)\s*</command-name>", _re.DOTALL)
_CMD_ARGS_RE = _re.compile(r"<command-args>\s*([\s\S]*?)\s*</command-args>", _re.DOTALL)


def _is_command_wrapper(text: str) -> bool:
    s = text.lstrip()
    return s.startswith("<command-") or s.startswith("<local-command")


def _clean_user_text(text: str) -> str:
    """If `text` is a slash-command wrapper, return the real user intent; else return text."""
    if not _is_command_wrapper(text):
        return text
    args = _CMD_ARGS_RE.search(text)
    if args and args.group(1).strip():
        return args.group(1).strip()
    name = _CMD_NAME_RE.search(text)
    if name:
        return name.group(1).strip()
    # system caveats / empty wrappers — return empty to skip
    return ""


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
            cleaned = _clean_user_text(text) if text else ""
            if cleaned and not is_meta and not is_tool_result:
                if not first_user_text:
                    first_user_text = cleaned[:200]
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
        # Collapse slash-command wrappers into a friendlier display
        if t == "user" and _is_command_wrapper(text):
            cleaned = _clean_user_text(text)
            if not cleaned:
                continue
            text = f"/{cleaned}" if not cleaned.startswith("/") and len(cleaned.split()) == 1 else cleaned
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


def _find_cli(name: str) -> str | None:
    """Locate a CLI binary without requiring shell resolution."""
    import shutil as _sh
    # common Windows / PATH locations
    for candidate in (name, f"{name}.cmd", f"{name}.exe"):
        p = _sh.which(candidate)
        if p:
            return p
    return None


def _run_cli(args: list[str], stdin_text: str = "", timeout: int = 90,
             cwd: str | None = None) -> tuple[int, str, str]:
    """Spawn a CLI hidden (no console window) and collect output."""
    startup = None
    if sys.platform.startswith("win"):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            args, input=stdin_text, text=True, capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, startupinfo=startup, cwd=cwd,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return -1, "", str(e)


_SCRATCH_CWD = Path.home() / ".claude-manager-scratch"


def _encoded_project(path: Path) -> str:
    """Match Claude Code's `~/.claude/projects/<encoded>` encoding."""
    return str(path).replace(":", "-").replace("\\", "-").replace("/", "-")


def _run_claude_isolated(args: list[str], stdin_text: str = "", timeout: int = 90) -> tuple[int, str, str]:
    """Run the claude CLI in an isolated scratch cwd, then purge whatever
    session jsonl it created — Claude Code auto-persists every -p invocation
    as a session, which would otherwise pollute the session browser."""
    _SCRATCH_CWD.mkdir(exist_ok=True)
    code, out, err = _run_cli(args, stdin_text=stdin_text, timeout=timeout, cwd=str(_SCRATCH_CWD))
    proj = PROJECTS_DIR / _encoded_project(_SCRATCH_CWD)
    if proj.exists():
        import shutil as _shutil
        _shutil.rmtree(proj, ignore_errors=True)
    return code, out, err


def _purge_assistant_leftovers() -> int:
    """One-shot cleanup at startup: remove session files that are obvious
    leftovers from the assistant/merge endpoints (they begin with our
    system prompt). Returns count removed."""
    if not PROJECTS_DIR.exists():
        return 0
    markers = (
        "You are a session management assistant",
        "你是一个会话归纳助手",
    )
    removed = 0
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in list(proj_dir.glob("*.jsonl")):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    head = fh.read(4000)
            except OSError:
                continue
            if any(m in head for m in markers):
                try:
                    f.unlink()
                    removed += 1
                    # Also remove the sidecar snapshot dir if present
                    sidecar = proj_dir / f.stem
                    if sidecar.exists() and sidecar.is_dir():
                        import shutil as _shutil
                        _shutil.rmtree(sidecar, ignore_errors=True)
                except OSError:
                    pass
        # If the project dir ends up empty, drop it too
        try:
            if not any(proj_dir.iterdir()):
                proj_dir.rmdir()
        except OSError:
            pass
    return removed


def _session_as_markdown(project: str, sid: str) -> tuple[str, str]:
    """Return (cwd, markdown) for a given session."""
    f = _safe_session(project, sid)
    lines = [f"# Session {sid}", ""]
    cwd = ""
    for obj in _iter_jsonl(f):
        t = obj.get("type")
        if t == "summary":
            lines.append(f"> **Summary:** {obj.get('summary','')}")
            lines.append("")
            continue
        if t not in ("user", "assistant"):
            continue
        if not cwd and obj.get("cwd"):
            cwd = obj["cwd"]
        msg = obj.get("message") or {}
        text = _extract_text(msg.get("content"))
        if not text:
            continue
        is_tool_result = bool(msg.get("content") and isinstance(msg["content"], list) and
                              any(isinstance(c, dict) and c.get("type") == "tool_result" for c in msg["content"]))
        role = "User" if t == "user" and not is_tool_result else ("Tool" if is_tool_result else "Assistant")
        lines.append(f"## {role}")
        lines.append(text[:4000])
        lines.append("")
    return cwd, "\n".join(lines)


@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    """Natural-language command → JSON intent via `claude -p`.

    Returns {ok, action, sessionIds, reply} where action ∈ {filter, delete, merge, info, unknown}.
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "empty query"}), 400

    claude = _find_cli("claude")
    if not claude:
        return jsonify({"ok": False, "error": "claude CLI not found on PATH"}), 500

    # Build a compact catalog: up to 400 most-recent sessions, each one line
    catalog_rows = []
    if PROJECTS_DIR.exists():
        entries = []
        for proj_dir in PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                entries.append((m, proj_dir.name, f))
        entries.sort(key=lambda x: x[0], reverse=True)
        for m, proj_name, f in entries[:400]:
            summary = ""
            first_user = ""
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh):
                        if i > 40:
                            break
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if obj.get("type") == "summary" and not summary:
                            summary = obj.get("summary", "") or ""
                        if obj.get("type") == "user" and not first_user:
                            msg = obj.get("message") or {}
                            first_user = _extract_text(msg.get("content"))[:120]
                        if summary and first_user:
                            break
            except OSError:
                continue
            title = (summary or first_user).replace("\n", " ")[:100]
            date = datetime.fromtimestamp(m).strftime("%Y-%m-%d")
            catalog_rows.append(f"{date} | {proj_name} | {f.stem} | {title}")
    catalog = "\n".join(catalog_rows)

    prompt = (
        "You are a session management assistant for a local Claude Code session browser.\n"
        "Below is the catalog of sessions (date | project | sid | title):\n"
        "===CATALOG START===\n"
        + catalog + "\n"
        "===CATALOG END===\n\n"
        f"User's request (Chinese or English):\n{query}\n\n"
        "Respond with a single JSON object, no prose, no markdown fences, with keys:\n"
        '  "action": one of "filter", "delete", "merge", "info"\n'
        '  "sessionIds": array of sid strings from the catalog (empty if not applicable)\n'
        '  "reply": short Chinese sentence summarising what you are doing\n'
        "Rules:\n"
        "- action='filter' → only return sids that match the user's criteria; do NOT delete.\n"
        "- action='delete' → only if user explicitly asks to delete; list every sid to remove.\n"
        "- action='merge'  → user wants multiple sessions merged; list all sids to merge.\n"
        "- action='info'   → user asks a question that needs no mutation.\n"
        "- Never invent sids that aren't in the catalog.\n"
    )

    code, out, err = _run_claude_isolated([claude, "-p"], stdin_text=prompt, timeout=180)
    if code != 0:
        msg = (err.strip() or out.strip() or "")[:2000]
        return jsonify({
            "ok": False,
            "error": f"claude exit {code}" + (f": {msg}" if msg else " (no output)"),
            "stderr": err[:2000], "stdout": out[:2000], "code": code,
        }), 500

    # Try to locate the JSON object in the output
    raw = out.strip()
    try:
        # trim any stray prose before the first {
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON in response")
        parsed = json.loads(raw[start:end + 1])
    except Exception as e:
        return jsonify({"ok": False, "error": f"bad JSON from claude: {e}", "raw": raw[:800]}), 500

    action = parsed.get("action", "unknown")
    sids = parsed.get("sessionIds") or []
    reply = parsed.get("reply", "")
    # Attach project info so frontend can execute mutations
    resolved = []
    if PROJECTS_DIR.exists():
        for proj_dir in PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                if f.stem in sids:
                    resolved.append({"project": proj_dir.name, "sid": f.stem})
    return jsonify({"ok": True, "action": action, "targets": resolved, "reply": reply})


@app.route("/api/merge", methods=["POST"])
def api_merge():
    """Summarise N sessions into a single meeting-minutes markdown via claude."""
    data = request.get_json(silent=True) or {}
    targets = data.get("targets") or []
    if not targets:
        return jsonify({"ok": False, "error": "no targets"}), 400

    claude = _find_cli("claude")
    if not claude:
        return jsonify({"ok": False, "error": "claude CLI not found"}), 500

    auth = _auth_status()
    if not auth["ok"]:
        return _needs_login_response(auth["reason"])

    sections = []
    for t in targets[:20]:  # safety cap
        proj, sid = t.get("project", ""), t.get("sid", "")
        try:
            _, md = _session_as_markdown(proj, sid)
            sections.append(f"\n\n===== SESSION {sid} =====\n\n{md[:18000]}")
        except Exception as e:
            sections.append(f"\n\n===== SESSION {sid} (read failed: {e}) =====\n")

    combined = "".join(sections)
    prompt = (
        "你是一个会话归纳助手。下面是若干条 Claude Code 会话原文(按顺序)。\n"
        "请生成一份会议纪要风格的合并 Markdown,包含:\n"
        "1. 总览(一段,说明共 N 次对话、主题范围)\n"
        "2. 按主题分组的要点(每组 3-8 条子项)\n"
        "3. 待办/未决事项(如有)\n"
        "4. 涉及的代码/文件清单\n"
        "不要原样复述对话,提炼为简洁条目。使用中文,合理使用 ## / - / ` 代码风格。\n\n"
        "===== 原始对话 =====\n"
        + combined
    )

    code, out, err = _run_claude_isolated([claude, "-p"], stdin_text=prompt, timeout=420)
    if code != 0:
        msg = (err.strip() or out.strip() or "")[:2000]
        return jsonify({"ok": False, "error": f"claude exit {code}" + (f": {msg}" if msg else "")}), 500

    from datetime import datetime as _dt
    fname = f"merged-{_dt.now().strftime('%Y%m%d-%H%M%S')}.md"
    # Write directly to the user's Downloads folder — programmatic <a download>
    # in a pywebview window is unreliable, so we let the backend own the filesystem.
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    out_path = downloads / fname
    try:
        out_path.write_text(out, encoding="utf-8")
    except OSError as e:
        return jsonify({"ok": False, "error": f"write failed: {e}"}), 500
    return jsonify({
        "ok": True,
        "path": str(out_path),
        "filename": fname,
        "bytes": len(out.encode("utf-8")),
        "count": len(targets),
    })


@app.route("/api/codex", methods=["POST"])
def api_codex():
    """Export session as MD into its cwd and launch codex in that cwd."""
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    cwd, md = _session_as_markdown(project, sid)
    if not cwd or not Path(cwd).exists():
        return jsonify({"ok": False, "error": f"cwd not found: {cwd}"}), 400
    md_path = Path(cwd) / f"_claude_manager_{sid}.md"
    try:
        md_path.write_text(md, encoding="utf-8")
    except OSError as e:
        return jsonify({"ok": False, "error": f"write failed: {e}"}), 500

    codex_path = _find_cli("codex")
    if not codex_path:
        return jsonify({"ok": False, "error": "codex CLI not found"}), 500
    # codex itself doesn't need Claude OAuth, but this endpoint ran
    # _session_as_markdown which has no network, so no pre-flight required.

    prompt = (
        f"参考同目录下 {md_path.name} 中的先前对话,继续帮我推进这个任务。"
    )
    try:
        if sys.platform.startswith("win"):
            # Escape the cwd path + embed a short initial prompt referencing the md file.
            safe_prompt = prompt.replace('"', '\\"')
            cmd = f'start "" cmd /k "cd /d \"{cwd}\" && codex \"{safe_prompt}\""'
            subprocess.Popen(cmd, shell=True)
        elif sys.platform == "darwin":
            script = f'tell app "Terminal" to do script "cd {json.dumps(cwd)} && codex {json.dumps(prompt)}"'
            subprocess.Popen(["osascript", "-e", script])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e",
                              f"bash -c 'cd {cwd!r} && codex {json.dumps(prompt)}; exec bash'"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "cwd": cwd, "mdPath": str(md_path)})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """In-app continuation: non-interactively send one message to a resumed
    session via `claude --resume <sid> -p <msg> --output-format json`.

    This bypasses the interactive-mode auto-compaction that triggers
    "Request not allowed" 403s for some users, at the cost of losing
    slash-commands / tool use. The CLI appends the new exchange to the
    existing jsonl so the conversation view picks it up on refresh.
    """
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "empty message"}), 400

    f = _safe_session(project, sid)
    cwd = ""
    for obj in _iter_jsonl(f):
        if obj.get("cwd"):
            cwd = obj["cwd"]
            break
    if not cwd or not Path(cwd).exists():
        return jsonify({"ok": False, "error": f"cwd not found: {cwd}"}), 400

    claude = _find_cli("claude")
    if not claude:
        return jsonify({"ok": False, "error": "claude CLI not found"}), 500

    args = [claude, "--resume", sid, "-p", message,
            "--output-format", "json"]
    code, out, err = _run_cli(args, stdin_text="", timeout=300, cwd=cwd)
    if code != 0:
        snippet = (err.strip() or out.strip() or "")[:1500]
        return jsonify({"ok": False,
                        "error": f"claude exit {code}" + (f": {snippet}" if snippet else "")}), 500

    # claude -p --output-format=json returns a single JSON object like:
    #   {"type":"result","result":"...","session_id":"...","usage":{...}}
    reply = ""
    new_sid = sid
    usage = None
    try:
        parsed = json.loads(out)
        if isinstance(parsed, dict):
            reply = parsed.get("result") or ""
            new_sid = parsed.get("session_id") or sid
            usage = parsed.get("usage")
    except Exception:
        reply = out.strip()

    return jsonify({
        "ok": True,
        "reply": reply,
        "sessionId": new_sid,
        "usage": usage,
    })


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
    # No pre-flight auth gate here: token validity doesn't predict whether
    # Anthropic's policy engine will accept the compaction call, and spawning
    # a terminal that just runs `claude --resume <sid>` is exactly what the
    # user would type manually — we shouldn't second-guess it.
    cmdline = f"claude --resume {sid}"
    try:
        if sys.platform.startswith("win"):
            cmd = f'start "" cmd /k "cd /d \"{cwd}\" && {cmdline}"'
            subprocess.Popen(cmd, shell=True)
        elif sys.platform == "darwin":
            script = f'tell app "Terminal" to do script "cd {json.dumps(cwd)} && {cmdline}"'
            subprocess.Popen(["osascript", "-e", script])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e",
                              f"bash -c 'cd {cwd!r} && {cmdline}; exec bash'"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "cwd": cwd, "command": cmdline})


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


def _read_oauth() -> dict:
    """Return the claudeAiOauth block from ~/.claude/.credentials.json, or {}."""
    cred_path = Path.home() / ".claude" / ".credentials.json"
    if not cred_path.exists():
        return {}
    try:
        with open(cred_path, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("claudeAiOauth") or {}
    except Exception:
        return {}


def _auth_status(buffer_secs: int = 120) -> dict:
    """Return {ok, expiresInSec, reason}. ok=False if the token is missing /
    expired / expiring within `buffer_secs`."""
    oauth = _read_oauth()
    if not oauth:
        return {"ok": False, "reason": "no_credentials", "expiresInSec": None}
    exp = oauth.get("expiresAt")
    if not isinstance(exp, (int, float)):
        return {"ok": False, "reason": "no_expires", "expiresInSec": None}
    now_ms = time.time() * 1000
    remaining = (exp - now_ms) / 1000
    if remaining <= 0:
        return {"ok": False, "reason": "expired", "expiresInSec": int(remaining)}
    if remaining < buffer_secs:
        return {"ok": False, "reason": "expiring", "expiresInSec": int(remaining)}
    return {"ok": True, "reason": "ok", "expiresInSec": int(remaining)}


def _needs_login_response(reason: str):
    human = {
        "no_credentials": "未找到 Claude 登录凭证",
        "no_expires":     "凭证无过期字段,无法校验",
        "expired":        "Claude 登录已过期",
        "expiring":       "Claude 登录即将过期",
    }.get(reason, "Claude 登录需要刷新")
    return jsonify({
        "ok": False,
        "needsLogin": True,
        "error": human,
        "reason": reason,
    }), 401


@app.route("/api/auth-status")
def api_auth_status():
    return jsonify(_auth_status())


@app.route("/api/claude-login", methods=["POST"])
def api_claude_login():
    """Spawn a visible terminal running `claude /login` so the user can
    complete the OAuth flow. Non-blocking."""
    claude = _find_cli("claude")
    if not claude:
        return jsonify({"ok": False, "error": "claude CLI not found"}), 500
    try:
        if sys.platform.startswith("win"):
            # /k keeps the window open after /login returns so user sees the result.
            cmd = f'start "Claude Login" cmd /k "\"{claude}\" /login"'
            subprocess.Popen(cmd, shell=True)
        elif sys.platform == "darwin":
            script = f'tell app "Terminal" to do script {json.dumps(f"{claude} /login")}'
            subprocess.Popen(["osascript", "-e", script])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e",
                              f"bash -c '{claude!r} /login; exec bash'"])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/account")
def api_account():
    """Return whatever Claude plan info we can glean from ~/.claude/.credentials.json."""
    cred_path = Path.home() / ".claude" / ".credentials.json"
    if not cred_path.exists():
        return jsonify({"ok": False, "error": "credentials file not found"})
    try:
        with open(cred_path, "r", encoding="utf-8") as f:
            cred = json.load(f)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    oauth = cred.get("claudeAiOauth") or {}
    sub_type = (oauth.get("subscriptionType") or "").lower()
    tier = oauth.get("rateLimitTier") or ""
    plan_map = {"max": "Max", "pro": "Pro", "free": "Free", "team": "Team"}
    tier_pretty = ""
    if "20x" in tier:
        tier_pretty = "Max · 20×"
    elif "5x" in tier:
        tier_pretty = "Max · 5×"
    elif tier:
        tier_pretty = tier.replace("default_", "").replace("_", " ").title()
    expires_at = oauth.get("expiresAt")
    expires_iso = ""
    if isinstance(expires_at, (int, float)):
        try:
            expires_iso = datetime.fromtimestamp(expires_at / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    auth = _auth_status()
    return jsonify({
        "ok": True,
        "plan": plan_map.get(sub_type, sub_type.title() or "—"),
        "tier": tier_pretty,
        "tokenExpiresAt": expires_iso,
        "auth": auth,
    })


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
                f_bytes = f.stat().st_size
            except OSError:
                f_bytes = 0
            total_bytes += f_bytes
            first_ts = last_ts = ""
            msg_count = 0
            session_models = Counter()
            for obj in _iter_jsonl(f):
                t = obj.get("type")
                ts = obj.get("timestamp") or ""
                if t == "assistant":
                    m = (obj.get("message") or {}).get("model")
                    if m:
                        model_count[m] += 1
                        session_models[m] += 1
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
    active_days_total = len([d for d, c in day_count.items() if c > 0])
    # Flat per-day timeline for the last 90 days (so the 7d/30d chips can render
    # a clean horizontal strip instead of being a sliver of the 7×53 column grid).
    recent_days = []
    for offset in range(89, -1, -1):
        d = today.fromordinal(today.toordinal() - offset)
        iso = d.isoformat()
        cnt = day_count.get(iso, 0)
        level = 0 if not cnt else min(4, 1 + math.floor(cnt / max(1, maxv) * 3.999))
        recent_days.append({"date": iso, "count": cnt, "level": level})
    totals = {
        "favoriteModel": fav_model[0][0].replace("claude-", "").replace("-", " ") if fav_model else "",
        "totalTokens": f"{(total_bytes / 4 / 1_000_000):.1f}m" if total_bytes else "0",
        "sessions": total_sessions,
        "longest": longest_txt or "—",
        "mostActiveDay": most_msgs_day[0] or "—",
        "streak": f"{streak} day{'s' if streak != 1 else ''}",
        "activeDays": active_days_total,
    }
    plans = [
        {"label": "今日会话", "count": day_sessions, "cap": 20, "reset": _fmt_delta(int((next_midnight - now).total_seconds())), "sub": "每日"},
        {"label": "本周会话", "count": week_sessions, "cap": 80, "reset": _fmt_delta(int((next_sunday - now).total_seconds())), "sub": "每周"},
        {"label": "本月会话", "count": month_sessions, "cap": 300, "reset": _fmt_delta(int((next_month - now).total_seconds())), "sub": "每月"},
        {"label": "累计会话", "count": total_sessions, "cap": max(total_sessions, 500), "reset": "不重置", "sub": "全部历史"},
    ]
    return jsonify({"heatmap": grid, "totals": totals, "plans": plans, "recentDays": recent_days})


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
    print("Claude Manager")
    print(f"Projects dir: {PROJECTS_DIR}")
    print(f"Serving on http://{HOST}:{PORT}")
    purged = _purge_assistant_leftovers()
    if purged:
        print(f"Purged {purged} assistant-leftover session file(s)")

    threading.Thread(target=_run_flask, daemon=True).start()
    _wait_for_server()

    # Prefer a native window via pywebview. Fall back to the default browser
    # if pywebview or its backend (e.g. WebView2 runtime) is unavailable.
    use_browser = "--browser" in sys.argv
    if not use_browser:
        try:
            import webview  # type: ignore
            webview.create_window(
                "Claude Manager",
                f"http://{HOST}:{PORT}",
                width=1280, height=840,
                min_size=(960, 640),
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
