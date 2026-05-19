"""Codex 对话管理器 - 本地 Web UI."""
from __future__ import annotations

import io
import json
import os
import re as _re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Flask is imported lazily inside _init_flask() so the splash window can show
# before paying its ~200ms import cost. Names below are filled in then.
Flask = None  # type: ignore
Response = None  # type: ignore
abort = None  # type: ignore
jsonify = None  # type: ignore
request = None  # type: ignore
send_file = None  # type: ignore
send_from_directory = None  # type: ignore

_PROXY_URL = "http://127.0.0.1:18001"
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.setdefault(_v, _PROXY_URL)

APP_NAME = "Codex Manager"
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
SESSIONS_DIR = CODEX_HOME / "sessions"
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME") or (Path.home() / ".claude"))
CLAUDE_PROJECTS_DIR = CLAUDE_HOME / "projects"
CODEX_BACKUP_HOME = Path.home() / ".codex_backup"
BACKUP_SESSIONS_DIR = CODEX_BACKUP_HOME / "sessions"
BACKUP_ARCHIVED_SESSIONS_DIR = CODEX_BACKUP_HOME / "archived_sessions"
NEW_CHAT_EXE_NAME = "Codex.exe"
INDEX_FILE = Path.home() / ".codex_conv_manager" / "index.json"
INDEX_VERSION = 2
USAGE_ROWS_VERSION = 2
HOST = "127.0.0.1"
PORT = int(os.environ.get("CODEX_MANAGER_PORT", "8766"))
CLAUDE_LAUNCH_PERMISSION_ARGS = ["--permission-mode", "bypassPermissions"]
ACTIVE_WINDOW_SECS = 180  # file mtime within this window → session is "active"
_UUID_RE = _re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

_INDEX_LOCK = threading.Lock()
_INDEX_CACHE: dict | None = None
_NEW_CHAT_LOCK = threading.Lock()
_NEW_CHAT_LAST_TS = 0.0


def _load_index() -> dict:
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == INDEX_VERSION:
            _INDEX_CACHE = data
            return data
    except (OSError, json.JSONDecodeError):
        pass
    _INDEX_CACHE = {"version": INDEX_VERSION, "entries": {}}
    return _INDEX_CACHE


def _save_index(data: dict) -> None:
    try:
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(INDEX_FILE)
    except OSError:
        pass


def _clear_data_caches(clear_index: bool = False) -> None:
    global _INDEX_CACHE
    if clear_index:
        _INDEX_CACHE = {"version": INDEX_VERSION, "entries": {}}
        try:
            INDEX_FILE.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    else:
        # Keep the persisted index. /api/sessions already validates each entry
        # by mtime and size, so refresh can be incremental instead of forcing a
        # full re-parse of very large Codex JSONL files.
        _INDEX_CACHE = None
    try:
        _SEARCH_BLOBS.clear()
    except NameError:
        pass


def _resource_dir() -> Path:
    """Return path to the web/ directory (handles PyInstaller _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "web"
    return Path(__file__).resolve().parent / "web"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _new_chat_exe() -> Path:
    return _app_dir() / NEW_CHAT_EXE_NAME


WEB_DIR = _resource_dir()

# Routes are captured into _ROUTES by the `_route` decorator at import time,
# then bound to the real Flask app inside _init_flask().
_ROUTES: list[tuple[str, dict, Any]] = []


def _route(rule: str, **options: Any):
    def deco(fn):
        _ROUTES.append((rule, options, fn))
        return fn
    return deco


def _session_roots() -> list[tuple[str, Path]]:
    roots = [
        ("current", SESSIONS_DIR),
        ("backup", BACKUP_SESSIONS_DIR),
        ("backup-archived", BACKUP_ARCHIVED_SESSIONS_DIR),
    ]
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, root in roots:
        key = _norm_path_str(root)
        if key in seen or not root.is_dir():
            continue
        seen.add(key)
        out.append((label, root))
    return out


def _norm_path_str(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _path_is_relative_to(path: Path, root: Path) -> bool:
    path_s = _norm_path_str(path)
    root_s = _norm_path_str(root)
    return path_s == root_s or path_s.startswith(root_s.rstrip("\\/") + os.sep)


def _session_source(path: Path) -> tuple[str, Path]:
    for label, root in _session_roots():
        try:
            path.relative_to(root)
            return label, root
        except ValueError:
            pass
        if _path_is_relative_to(path, root):
            return label, root
    return "unknown", path.parent


def _session_index_key(path: Path) -> str:
    label, root = _session_source(path)
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path.name
    rel_s = str(rel).replace("\\", "/")
    return f"{label}:{rel_s}"


def _iter_session_files(include_backups: bool = True) -> list[Path]:
    roots = _session_roots() if include_backups else [("current", SESSIONS_DIR)] if SESSIONS_DIR.exists() else []
    items: list[tuple[float, int, Path]] = []
    for label, root in roots:
        priority = 1 if label == "current" else 0
        for p in root.rglob("*.jsonl"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0
            items.append((mtime, priority, p))
    items.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [p for _, _, p in items]


def _restore_session_if_needed(path: Path) -> Path:
    """Copy a backup/archived session into the active Codex sessions tree.

    Codex CLI resume/fork only looks in the active CODEX_HOME. Viewing can read
    backups in place, but launching a backup session needs a non-destructive
    restore into ~/.codex/sessions.
    """
    if _path_is_relative_to(path, SESSIONS_DIR):
        return path

    label, root = _session_source(path)
    if label == "backup":
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = Path(path.name)
    elif label == "backup-archived":
        m = _re.search(r"rollout-(\d{4})-(\d{2})-(\d{2})T", path.name)
        rel = Path(m.group(1), m.group(2), m.group(3), path.name) if m else Path("restored", path.name)
    else:
        return path

    dest = SESSIONS_DIR / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return dest


def _ensure_session_available(project: str, sid: str) -> Path:
    return _restore_session_if_needed(_safe_session(project, sid))


def _session_id_from_path(path: Path) -> str:
    match = _UUID_RE.search(path.stem)
    return match.group(1).lower() if match else path.stem


def _project_id_for_cwd(cwd: str) -> str:
    if not cwd:
        return "unknown"
    cleaned = cwd.replace(":", "-").replace("\\", "-").replace("/", "-")
    cleaned = _re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-")
    return cleaned or "unknown"


def _read_session_meta(path: Path) -> dict:
    meta: dict[str, Any] = {
        "sid": _session_id_from_path(path),
        "cwd": "",
        "created": "",
        "cliVersion": "",
        "source": "",
        "modelProvider": "",
    }
    for obj in _iter_jsonl(path):
        if obj.get("type") == "session_meta":
            payload = obj.get("payload") or {}
            meta["sid"] = (payload.get("id") or meta["sid"]).lower()
            meta["cwd"] = payload.get("cwd") or ""
            meta["created"] = payload.get("timestamp") or obj.get("timestamp") or ""
            meta["cliVersion"] = payload.get("cli_version") or ""
            meta["source"] = payload.get("source") or payload.get("originator") or ""
            meta["modelProvider"] = payload.get("model_provider") or ""
            break
    return meta


def _session_project(path: Path) -> str:
    return _project_id_for_cwd(_read_session_meta(path).get("cwd", ""))


def _safe_session(project: str, sid: str) -> Path:
    if "/" in project or "\\" in project or ".." in project:
        abort(400, "bad project")
    if "/" in sid or "\\" in sid or ".." in sid:
        abort(400, "bad sid")
    sid_l = sid.lower()
    matches: list[Path] = []
    for f in _dedupe_session_files(_iter_session_files()):
        if _session_id_from_path(f) == sid_l and _session_project(f) == project:
            matches.append(f)
    for f in matches:
        if _path_is_relative_to(f, SESSIONS_DIR):
            return f
    if matches:
        return matches[0]
    abort(404, "session not found")


def _dedupe_session_files(files: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[tuple[str, str]] = set()
    for f in files:
        project = _session_project(f)
        key = (project, _session_id_from_path(f))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


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


def _iter_jsonl_from_offset(path: Path, offset: int):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, offset))
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


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
            if t in ("text", "input_text", "output_text"):
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
            elif t in ("input_image", "local_image", "image"):
                out.append("[image]")
        return "\n".join(out)
    return ""


_MOJIBAKE_MARKERS = (
    "锛", "锟", "涓", "甯", "鈥", "鈼", "绋", "璇", "浠", "鐢",
    "瑙", "妯", "鎸", "杩", "鍚", "澶", "缂", "娑", "棰", "鏃",
    "勫", "彂", "殑", "€", "�",
)


def _looks_like_mojibake(text: str) -> bool:
    return any(marker in text for marker in _MOJIBAKE_MARKERS)


def _text_quality_score(text: str) -> int:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    marker_penalty = sum(text.count(marker) for marker in _MOJIBAKE_MARKERS) * 24
    replacement_penalty = text.count("\ufffd") * 16
    return cjk - marker_penalty - replacement_penalty


def _best_mojibake_repair(text: str) -> str:
    if not text or not _looks_like_mojibake(text):
        return text
    best = text
    best_score = _text_quality_score(text)
    for encoding in ("mbcs", "oem", "gb18030", "gbk", "cp936"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except (LookupError, UnicodeError):
            continue
        if "\x00" in candidate:
            continue
        score = _text_quality_score(candidate)
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _repair_tool_output_text(text: str) -> str:
    """Repair common UTF-8-as-GBK mojibake in command output only."""
    if not text or not _looks_like_mojibake(text):
        return text
    repaired = _best_mojibake_repair(text)
    if repaired != text:
        return repaired
    parts = text.splitlines(keepends=True)
    fixed_parts = [_best_mojibake_repair(part) for part in parts]
    fixed = "".join(fixed_parts)
    return fixed if fixed != text else text


def _is_internal_codex_text(text: str) -> bool:
    s = (text or "").strip()
    return (
        not s
        or s.startswith("<environment_context>")
        or s.startswith("<turn_aborted>")
        or s.startswith("<permissions instructions>")
        or s.startswith("<collaboration_mode>")
        or s.startswith("<skills_instructions>")
    )


def _codex_tool_text(payload: dict) -> str:
    ptype = payload.get("type")
    if ptype == "function_call":
        name = payload.get("name") or "tool"
        args = payload.get("arguments") or ""
        return f"{name}\n{args}".strip()
    if ptype == "function_call_output":
        return _repair_tool_output_text(str(payload.get("output") or ""))
    return ""


def _usage_int(obj: dict, key: str) -> int:
    try:
        return int(obj.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _codex_usage_snapshot(usage: dict) -> dict[str, int]:
    input_t = _usage_int(usage, "input_tokens")
    output_t = _usage_int(usage, "output_tokens")
    total_t = _usage_int(usage, "total_tokens") or (input_t + output_t)
    return {
        "input": input_t,
        "cached": _usage_int(usage, "cached_input_tokens"),
        "output": output_t,
        "reasoning": _usage_int(usage, "reasoning_output_tokens"),
        "total": total_t,
    }


def _codex_usage_delta(current: dict[str, int], previous: dict[str, int] | None) -> dict[str, int]:
    if not previous:
        return dict(current)
    out: dict[str, int] = {}
    for key, value in current.items():
        prev = previous.get(key, 0)
        out[key] = value - prev if value >= prev else value
    return out


def _scan_session(project: str, path: Path) -> tuple[dict, list]:
    """Walk JSONL once; return (summary_dict, usage_rows).

    usage_rows is a list of [model, date_yyyy_mm_dd, input, cached_input,
    output, reasoning_output, total]. Codex token_count events are cumulative
    per session, so rows store deltas between snapshots and can be aggregated
    without double counting.
    """
    meta = _read_session_meta(path)
    sid = meta.get("sid") or _session_id_from_path(path)
    first_user_text = ""
    cwd = meta.get("cwd", "") or ""
    git_branch = ""
    first_ts = meta.get("created", "") or ""
    last_ts = first_ts
    user_count = 0
    assistant_count = 0
    summary = ""
    usage_rows: list = []
    model = ""
    usage_prev: dict[str, int] | None = None
    usage_last: dict[str, int] | None = None
    usage_last_ts = ""
    usage_rate_limits: dict[str, Any] = {}
    usage_plan_type = ""
    usage_context_window = 0

    for obj in _iter_jsonl(path):
        ts = obj.get("timestamp") or ""
        t = obj.get("type")
        payload = obj.get("payload") or {}
        if t == "turn_context":
            if not cwd:
                cwd = payload.get("cwd", "") or cwd
            model = payload.get("model") or model
            continue
        if t == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total_usage = info.get("total_token_usage") or {}
            usage_context_window = _usage_int(info, "model_context_window") or usage_context_window
            rate_limits = payload.get("rate_limits") or {}
            if isinstance(rate_limits, dict) and rate_limits:
                usage_rate_limits = rate_limits
                usage_plan_type = rate_limits.get("plan_type") or usage_plan_type
            if total_usage:
                snapshot = _codex_usage_snapshot(total_usage)
                delta = _codex_usage_delta(snapshot, usage_prev)
                usage_prev = snapshot
                usage_last = snapshot
                usage_last_ts = ts or usage_last_ts
                date = (ts or last_ts or first_ts)[:10]
                if any(delta.get(k, 0) for k in ("input", "cached", "output", "reasoning", "total")):
                    usage_rows.append([
                        model or "codex",
                        date,
                        delta.get("input", 0),
                        delta.get("cached", 0),
                        delta.get("output", 0),
                        delta.get("reasoning", 0),
                        delta.get("total", 0),
                    ])
            if ts:
                if not first_ts:
                    first_ts = ts
                last_ts = ts
            continue
        if t != "response_item":
            if ts:
                if not first_ts:
                    first_ts = ts
                last_ts = ts
            continue

        ptype = payload.get("type")
        if ptype == "message":
            role = payload.get("role")
            if role == "user":
                text = _extract_text(payload.get("content"))
                if _is_internal_codex_text(text):
                    continue
                cleaned = _clean_user_text(text) if text else ""
                if cleaned:
                    if not first_user_text:
                        first_user_text = cleaned[:200]
                    user_count += 1
            elif role == "assistant":
                text = _extract_text(payload.get("content"))
                if text.strip():
                    assistant_count += 1
        elif ptype in ("function_call", "function_call_output"):
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
    source_label, _source_root = _session_source(path)
    summary_dict = {
        "project": project,
        "sid": sid,
        "storage": source_label,
        "cwd": cwd,
        "gitBranch": git_branch,
        "model": model,
        "firstTs": first_ts,
        "lastTs": last_ts,
        "mtime": mtime,
        "size": size,
        "userCount": user_count,
        "assistantCount": assistant_count,
        "summary": summary or first_user_text,
        "preview": first_user_text,
        "active": active,
        "usage": {
            "lastTs": usage_last_ts,
            "tokens": usage_last or {},
            "rateLimits": usage_rate_limits,
            "planType": usage_plan_type,
            "contextWindow": usage_context_window,
        },
    }
    return summary_dict, usage_rows


def _summarize_session(project: str, path: Path) -> dict:
    return _scan_session(project, path)[0]


def _scan_session_incremental(project: str, path: Path, cached: dict, st: os.stat_result) -> tuple[dict, list]:
    old_size = int(cached.get("size") or 0)
    if old_size <= 0 or old_size > st.st_size:
        raise ValueError("cannot incrementally scan this file")

    summary = dict(cached.get("data") or {})
    costs = list(cached.get("costs") or [])
    if old_size == st.st_size:
        summary["mtime"] = st.st_mtime
        summary["size"] = st.st_size
        summary["active"] = (time.time() - st.st_mtime) < ACTIVE_WINDOW_SECS if st.st_mtime else False
        return summary, costs

    first_user_text = summary.get("preview") or ""
    cwd = summary.get("cwd") or ""
    first_ts = summary.get("firstTs") or ""
    last_ts = summary.get("lastTs") or first_ts
    user_count = int(summary.get("userCount") or 0)
    assistant_count = int(summary.get("assistantCount") or 0)
    model = summary.get("model") or ""
    usage_meta = summary.get("usage") or {}
    usage_prev = dict(usage_meta.get("tokens") or {}) or None
    usage_last = dict(usage_meta.get("tokens") or {}) or None
    usage_last_ts = usage_meta.get("lastTs") or ""
    usage_rate_limits = dict(usage_meta.get("rateLimits") or {})
    usage_plan_type = usage_meta.get("planType") or ""
    usage_context_window = int(usage_meta.get("contextWindow") or 0)

    for obj in _iter_jsonl_from_offset(path, old_size):
        ts = obj.get("timestamp") or ""
        t = obj.get("type")
        payload = obj.get("payload") or {}
        if t == "turn_context":
            if not cwd:
                cwd = payload.get("cwd", "") or cwd
            model = payload.get("model") or model
        elif t == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total_usage = info.get("total_token_usage") or {}
            usage_context_window = _usage_int(info, "model_context_window") or usage_context_window
            rate_limits = payload.get("rate_limits") or {}
            if isinstance(rate_limits, dict) and rate_limits:
                usage_rate_limits = rate_limits
                usage_plan_type = rate_limits.get("plan_type") or usage_plan_type
            if total_usage:
                snapshot = _codex_usage_snapshot(total_usage)
                delta = _codex_usage_delta(snapshot, usage_prev)
                usage_prev = snapshot
                usage_last = snapshot
                usage_last_ts = ts or usage_last_ts
                date = (ts or last_ts or first_ts)[:10]
                if any(delta.get(k, 0) for k in ("input", "cached", "output", "reasoning", "total")):
                    costs.append([
                        model or "codex",
                        date,
                        delta.get("input", 0),
                        delta.get("cached", 0),
                        delta.get("output", 0),
                        delta.get("reasoning", 0),
                        delta.get("total", 0),
                    ])
        elif t == "response_item":
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                if role == "user":
                    text = _extract_text(payload.get("content"))
                    if not _is_internal_codex_text(text):
                        cleaned = _clean_user_text(text) if text else ""
                        if cleaned:
                            if not first_user_text:
                                first_user_text = cleaned[:200]
                            user_count += 1
                elif role == "assistant":
                    text = _extract_text(payload.get("content"))
                    if text.strip():
                        assistant_count += 1
            elif ptype in ("function_call", "function_call_output"):
                assistant_count += 1
        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

    source_label, _source_root = _session_source(path)
    active = (time.time() - st.st_mtime) < ACTIVE_WINDOW_SECS if st.st_mtime else False
    summary.update({
        "project": project,
        "storage": source_label,
        "cwd": cwd,
        "model": model,
        "firstTs": first_ts,
        "lastTs": last_ts,
        "mtime": st.st_mtime,
        "size": st.st_size,
        "userCount": user_count,
        "assistantCount": assistant_count,
        "summary": summary.get("summary") or first_user_text,
        "preview": first_user_text,
        "active": active,
        "usage": {
            "lastTs": usage_last_ts,
            "tokens": usage_last or {},
            "rateLimits": usage_rate_limits,
            "planType": usage_plan_type,
            "contextWindow": usage_context_window,
        },
    })
    return summary, costs


# Pricing per million tokens (USD). These are only API-equivalent estimates;
# Codex CLI usage through a ChatGPT plan is not billed per request here.
_MODEL_PRICES: list[tuple[str, tuple[float, float, float, float]]] = [
    # (substring, (input, output, cache_write, cache_read))
    ("gpt-5.5", (0.0, 0.0, 0.0, 0.0)),
    ("gpt-5.4", (0.0, 0.0, 0.0, 0.0)),
    ("gpt-5.3", (0.0, 0.0, 0.0, 0.0)),
    ("gpt-5",   (0.0, 0.0, 0.0, 0.0)),
    ("o",       (0.0, 0.0, 0.0, 0.0)),
]


def _model_price(model: str) -> tuple[float, float, float, float]:
    m = (model or "").lower()
    for key, p in _MODEL_PRICES:
        if key in m:
            return p
    return (0.0, 0.0, 0.0, 0.0)


def _load_session_summaries() -> tuple[list[dict], list[dict]]:
    raw_files = _iter_session_files()
    if not raw_files:
        return [], []

    sessions: list[dict] = []
    project_counts: dict[str, int] = {}
    with _INDEX_LOCK:
        index = _load_index()
        entries = index["entries"]
        seen_keys = set()
        seen_sessions = set()
        dirty = False
        now = time.time()

        for f in raw_files:
            try:
                st = f.stat()
            except OSError:
                continue
            key = _session_index_key(f)
            seen_keys.add(key)
            cached = entries.get(key)
            fresh = (
                cached
                and cached.get("mtime") == st.st_mtime
                and cached.get("size") == st.st_size
                and isinstance(cached.get("data"), dict)
            )
            cached_data = cached.get("data") if fresh else None
            project = (cached_data or {}).get("project") or _session_project(f)
            session_key = (project, _session_id_from_path(f))
            if session_key in seen_sessions:
                continue
            seen_sessions.add(session_key)
            if fresh:
                summary = dict(cached_data)
            else:
                try:
                    if cached and isinstance(cached.get("data"), dict):
                        try:
                            summary, costs = _scan_session_incremental(project, f, cached, st)
                        except ValueError:
                            summary, costs = _scan_session(project, f)
                    else:
                        summary, costs = _scan_session(project, f)
                    entries[key] = {
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                        "data": summary,
                        "costs": costs,
                        "costsVersion": USAGE_ROWS_VERSION,
                    }
                    dirty = True
                except Exception as e:
                    summary = {
                        "project": project, "sid": _session_id_from_path(f), "error": str(e),
                        "mtime": st.st_mtime, "size": st.st_size,
                        "summary": "", "preview": "", "cwd": "", "firstTs": "", "lastTs": "",
                        "userCount": 0, "assistantCount": 0,
                    }
            summary["active"] = (now - st.st_mtime) < ACTIVE_WINDOW_SECS if st.st_mtime else False
            sessions.append(summary)
            project_counts[summary.get("project") or project] = project_counts.get(summary.get("project") or project, 0) + 1

        projects = [
            {"name": name, "count": count}
            for name, count in sorted(project_counts.items(), key=lambda kv: kv[0].lower())
        ]

        # Drop entries for files that no longer exist
        stale = [k for k in entries if k not in seen_keys]
        if stale:
            for k in stale:
                del entries[k]
            dirty = True

        if dirty:
            _save_index(index)

    sessions.sort(key=lambda s: s.get("mtime", 0), reverse=True)
    return projects, sessions


@_route("/api/sessions")
def api_sessions():
    projects, sessions = _load_session_summaries()
    return jsonify({"projects": projects, "sessions": sessions})


@_route("/api/refresh", methods=["POST"])
def api_refresh():
    with _INDEX_LOCK:
        _clear_data_caches()
    return jsonify({"ok": True})


@_route("/api/costs")
def api_costs():
    """Aggregate Codex token usage from JSONL.

    Reads from the same on-disk index cache as /api/sessions; any file with
    no current cached usage rows gets re-scanned and the cache updated.
    """
    all_files = _dedupe_session_files(_iter_session_files())
    if not all_files:
        return jsonify({
            "total": 0, "tokens": {
                "input": 0, "cachedInput": 0, "nonCachedInput": 0,
                "output": 0, "reasoningOutput": 0, "total": 0,
            },
            "byModel": {}, "byDay": {}, "byDayTokens": {},
            "sessions": 0, "rateLimits": {},
        })

    by_model: dict[str, dict] = {}
    by_day: dict[str, int] = {}
    by_day_tokens: dict[str, dict] = {}
    total_input = total_cached = total_output = total_reasoning = total_tokens = 0
    sessions_with_usage = 0
    latest_rate_limits: dict[str, Any] = {}
    latest_rate_ts = ""

    with _INDEX_LOCK:
        index = _load_index()
        entries = index["entries"]
        dirty = False

        for f in all_files:
            try:
                st = f.stat()
            except OSError:
                continue
            project = _session_project(f)
            key = _session_index_key(f)
            cached = entries.get(key)
            fresh = (
                cached
                and cached.get("mtime") == st.st_mtime
                and cached.get("size") == st.st_size
                and cached.get("costsVersion") == USAGE_ROWS_VERSION
            )
            summary_data = (cached or {}).get("data") or {}
            if fresh and isinstance(cached.get("costs"), list):
                rows = cached["costs"]
            else:
                try:
                    summary, rows = _scan_session(project, f)
                except Exception:
                    continue
                summary_data = summary
                entries[key] = {
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "data": summary,
                    "costs": rows,
                    "costsVersion": USAGE_ROWS_VERSION,
                }
                dirty = True

            usage_meta = summary_data.get("usage") if isinstance(summary_data, dict) else {}
            if isinstance(usage_meta, dict):
                rate_limits = usage_meta.get("rateLimits") or {}
                rate_ts = usage_meta.get("lastTs") or ""
                if rate_limits and rate_ts >= latest_rate_ts:
                    latest_rate_ts = rate_ts
                    latest_rate_limits = {
                        **rate_limits,
                        "lastTs": rate_ts,
                        "contextWindow": usage_meta.get("contextWindow") or 0,
                    }

            if rows:
                sessions_with_usage += 1
            for row in rows:
                if not isinstance(row, (list, tuple)):
                    continue
                try:
                    if len(row) >= 7:
                        model, date, input_t, cached_t, output_t, reasoning_t, row_total = row[:7]
                    else:
                        # Backward compatibility for stale in-memory rows from older builds:
                        # [model, date, non_cached_input, output, cache_write, cached_input]
                        model, date, non_cached_t, output_t, _cw_t, cached_t = row[:6]
                        input_t = int(non_cached_t or 0) + int(cached_t or 0)
                        reasoning_t = 0
                        row_total = input_t + int(output_t or 0)
                    input_t = int(input_t or 0)
                    cached_t = int(cached_t or 0)
                    output_t = int(output_t or 0)
                    reasoning_t = int(reasoning_t or 0)
                    row_total = int(row_total or (input_t + output_t))
                except (ValueError, TypeError):
                    continue

                non_cached_t = max(0, input_t - cached_t)
                total_input += input_t
                total_cached += cached_t
                total_output += output_t
                total_reasoning += reasoning_t
                total_tokens += row_total

                label = model or "unknown"
                bm = by_model.setdefault(label, {
                    "input": 0, "cachedInput": 0, "nonCachedInput": 0,
                    "output": 0, "reasoningOutput": 0, "total": 0,
                })
                bm["input"] += input_t
                bm["cachedInput"] += cached_t
                bm["nonCachedInput"] += non_cached_t
                bm["output"] += output_t
                bm["reasoningOutput"] += reasoning_t
                bm["total"] += row_total

                if date:
                    by_day[date] = by_day.get(date, 0) + row_total
                    bd = by_day_tokens.setdefault(date, {
                        "input": 0, "cachedInput": 0, "nonCachedInput": 0,
                        "output": 0, "reasoningOutput": 0, "total": 0,
                    })
                    bd["input"] += input_t
                    bd["cachedInput"] += cached_t
                    bd["nonCachedInput"] += non_cached_t
                    bd["output"] += output_t
                    bd["reasoningOutput"] += reasoning_t
                    bd["total"] += row_total

        if dirty:
            _save_index(index)

    # Sort byDay descending by date for the frontend.
    by_day_sorted = dict(sorted(by_day.items(), reverse=True))
    by_day_tokens_sorted = dict(sorted(by_day_tokens.items(), reverse=True))
    return jsonify({
        "total": total_tokens,
        "tokens": {
            "input": total_input,
            "cachedInput": total_cached,
            "nonCachedInput": max(0, total_input - total_cached),
            "output": total_output,
            "reasoningOutput": total_reasoning,
            "total": total_tokens,
        },
        "byModel": by_model,
        "byDay": by_day_sorted,
        "byDayTokens": by_day_tokens_sorted,
        "sessions": sessions_with_usage,
        "rateLimits": latest_rate_limits,
    })


@_route("/api/session/<project>/<sid>")
def api_session_detail(project: str, sid: str):
    f = _safe_session(project, sid)
    messages = []
    meta = _read_session_meta(f)
    cwd = meta.get("cwd", "") or ""
    git_branch = ""
    model = ""
    for obj in _iter_jsonl(f):
        t = obj.get("type")
        payload = obj.get("payload") or {}
        if t == "turn_context":
            model = payload.get("model") or model
            if not cwd:
                cwd = payload.get("cwd", "") or cwd
            continue
        if t != "response_item":
            continue
        ptype = payload.get("type")
        if ptype == "message":
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _extract_text(payload.get("content"))
            if role == "user" and _is_internal_codex_text(text):
                continue
            if not text.strip():
                continue
            messages.append({
                "role": role,
                "text": text,
                "ts": obj.get("timestamp", ""),
                "meta": False,
                "toolResult": False,
                "model": model if role == "assistant" else "",
            })
        elif ptype in ("function_call", "function_call_output"):
            text = _codex_tool_text(payload)
            if not text:
                continue
            messages.append({
                "role": "assistant",
                "text": text,
                "ts": obj.get("timestamp", ""),
                "meta": False,
                "toolResult": True,
                "model": "",
            })
    return jsonify({
        "project": project, "sid": sid, "cwd": cwd, "gitBranch": git_branch,
        "messages": messages,
    })


# In-memory search index: project/sid → (mtime, size, lowercase_blob).
# Built lazily on first search, reused for subsequent queries — string scan
# instead of JSONL re-parse. Stale entries are detected via (mtime, size).
@_route("/api/open-cwd", methods=["POST"])
def api_open_cwd():
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    f = _safe_session(project, sid)
    meta = _read_session_meta(f)
    cwd = meta.get("cwd", "") or ""
    if not cwd:
        for obj in _iter_jsonl(f):
            if obj.get("type") == "turn_context":
                payload = obj.get("payload") or {}
                cwd = payload.get("cwd", "") or ""
                if cwd:
                    break
    p = Path(cwd).expanduser() if cwd else None
    if not p or not p.exists() or not p.is_dir():
        return jsonify({"ok": False, "error": f"cwd not found: {cwd}"}), 404
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "cwd": str(p)})


_SEARCH_BLOBS: dict[str, tuple[float, int, str]] = {}


def _build_search_blob(path: Path) -> str:
    """Concat all user/assistant/summary text in lowercase. Used for substring search."""
    parts: list[str] = []
    for obj in _iter_jsonl(path):
        t = obj.get("type")
        if t != "response_item":
            continue
        payload = obj.get("payload") or {}
        ptype = payload.get("type")
        text = ""
        if ptype == "message":
            if payload.get("role") not in ("user", "assistant"):
                continue
            text = _extract_text(payload.get("content"))
            if payload.get("role") == "user" and _is_internal_codex_text(text):
                continue
        elif ptype in ("function_call", "function_call_output"):
            text = _codex_tool_text(payload)
        if text:
            parts.append(text)
    return "\n".join(parts).lower()


def _ensure_blob(arg):
    proj_name, sid, f = arg
    try:
        st = f.stat()
    except OSError:
        return None
    key = f"{proj_name}/{sid}/{_session_index_key(f)}"
    cached = _SEARCH_BLOBS.get(key)
    if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
        blob = cached[2]
    else:
        try:
            blob = _build_search_blob(f)
        except Exception:
            return None
        _SEARCH_BLOBS[key] = (st.st_mtime, st.st_size, blob)
    return (proj_name, sid, f, st.st_mtime, blob)


@_route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    ql = q.lower()
    all_files = _dedupe_session_files(_iter_session_files())
    if not all_files:
        return jsonify({"results": []})

    # Gather files
    files: list[tuple[str, str, Path]] = []
    for f in all_files:
        files.append((_session_project(f), _session_id_from_path(f), f))

    # Cheap evict: drop blob entries for files that no longer exist.
    seen_keys = {f"{p}/{sid}/{_session_index_key(f)}" for p, sid, f in files}
    for stale in [k for k in _SEARCH_BLOBS if k not in seen_keys]:
        _SEARCH_BLOBS.pop(stale, None)

    # Phase 1: ensure each file's blob is cached, in parallel for cold starts.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        prepared = list(ex.map(_ensure_blob, files))

    # Phase 2: filter candidates by substring on the cached blob.
    candidates = []
    for entry in prepared:
        if not entry:
            continue
        proj_name, sid, f, mtime, blob = entry
        if ql in blob:
            candidates.append((proj_name, sid, f, mtime))

    # Phase 3: only candidates re-parse JSONL to extract snippets.
    results = []
    for proj_name, sid, f, mtime in candidates:
        hits = []
        for obj in _iter_jsonl(f):
            if obj.get("type") != "response_item":
                continue
            text = ""
            payload = obj.get("payload") or {}
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = _extract_text(payload.get("content"))
                if role == "user" and _is_internal_codex_text(text):
                    continue
            elif ptype in ("function_call", "function_call_output"):
                role = "tool"
                text = _codex_tool_text(payload)
            else:
                continue
            if not text:
                continue
            tl = text.lower()
            i = tl.find(ql)
            if i >= 0:
                s = max(0, i - 40)
                e = min(len(text), i + len(q) + 80)
                hits.append({"role": role, "snippet": text[s:e], "ts": obj.get("timestamp", "")})
                if len(hits) >= 3:
                    break
        if hits:
            results.append({
                "project": proj_name,
                "sid": sid,
                "mtime": mtime,
                "hits": hits,
            })

    results.sort(key=lambda r: r.get("mtime", 0), reverse=True)
    return jsonify({"results": results})


@_route("/api/export/<project>/<sid>")
def api_export(project: str, sid: str):
    fmt = request.args.get("format", "md").lower()
    f = _safe_session(project, sid)
    if fmt == "json":
        return send_file(f, as_attachment=True, download_name=f"{sid}.jsonl", mimetype="application/jsonl")
    # markdown
    lines = [f"# Codex Session {sid}", ""]
    cwd_shown = False
    for obj in _iter_jsonl(f):
        if obj.get("type") == "session_meta":
            payload = obj.get("payload") or {}
            if not cwd_shown and payload.get("cwd"):
                lines.insert(1, f"- cwd: `{payload.get('cwd')}`")
                lines.insert(2, f"- cli: `{payload.get('cli_version','')}`")
                lines.insert(3, "")
                cwd_shown = True
            continue
        if obj.get("type") != "response_item":
            continue
        payload = obj.get("payload") or {}
        ptype = payload.get("type")
        text = ""
        role = ""
        if ptype == "message":
            msg_role = payload.get("role")
            if msg_role not in ("user", "assistant"):
                continue
            text = _extract_text(payload.get("content"))
            if msg_role == "user" and _is_internal_codex_text(text):
                continue
            role = "User" if msg_role == "user" else "Assistant"
        elif ptype in ("function_call", "function_call_output"):
            text = _codex_tool_text(payload)
            role = "Tool"
        else:
            continue
        if not text:
            continue
        ts = obj.get("timestamp", "")
        lines.append(f"## {role}  `{ts}`")
        lines.append("")
        lines.append(text)
        lines.append("")
    data = "\n".join(lines).encode("utf-8")
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=f"{sid}.md", mimetype="text/markdown")


@_route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    f = _safe_session(project, sid)
    try:
        f.unlink()
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


def _find_cli(name: str) -> str | None:
    """Locate a CLI binary without requiring shell resolution."""
    import shutil as _sh

    def same_path(a: Path, b: Path) -> bool:
        try:
            return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
        except OSError:
            return os.path.normcase(str(a)) == os.path.normcase(str(b))

    def is_sidecar(path: Path) -> bool:
        sidecars = (_new_chat_exe(), Path.cwd() / NEW_CHAT_EXE_NAME)
        return any(same_path(path, sidecar) for sidecar in sidecars)

    candidates = (f"{name}.exe", f"{name}.cmd", name) if sys.platform.startswith("win") else (name,)
    for candidate in candidates:
        for raw_dir in os.environ.get("PATH", "").split(os.pathsep):
            if not raw_dir:
                continue
            p = Path(raw_dir).expanduser() / candidate
            try:
                if p.is_file() and not is_sidecar(p):
                    return str(p.resolve())
            except OSError:
                continue
        p = _sh.which(candidate)
        if p:
            resolved = Path(p).resolve()
            if not is_sidecar(resolved):
                return str(resolved)
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


_SCRATCH_CWD = Path.home() / ".codex-manager-scratch"


_SECRET_PATTERNS: list[tuple[_re.Pattern[str], str]] = [
    (_re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"), "[REDACTED_ALIYUN_ACCESS_KEY_ID]"),
    (_re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY_ID]"),
    (_re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "[REDACTED_GOOGLE_API_KEY]"),
    (_re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (_re.compile(r"(?i)\b(accesskey secret|access key secret|api[_ -]?key|secret|token|password)(\s*[,=:]\s*)[^\s,;]+"),
     r"\1\2[REDACTED]"),
]


def _repair_mojibake(text: str) -> str:
    """Repair UTF-8 text that was decoded as latin-1/cp1252 in Claude logs."""
    if not isinstance(text, str) or not text:
        return text
    buf = bytearray()
    try:
        for ch in text:
            code = ord(ch)
            if code <= 0xFF:
                buf.append(code)
            else:
                buf.extend(ch.encode("cp1252"))
        repaired = bytes(buf).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    markers = ("Ã", "Â", "�", "é", "å", "æ", "ç", "è")
    if sum(text.count(m) for m in markers) > sum(repaired.count(m) for m in markers):
        return repaired
    return text


def _redact_sensitive_text(text: str) -> str:
    text = text or ""
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _iter_claude_session_files() -> list[Path]:
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    files = [p for p in CLAUDE_PROJECTS_DIR.rglob("*.jsonl") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _claude_session_id(path: Path) -> str:
    return path.stem


def _find_claude_session(session_id: str | None = None) -> Path | None:
    files = _iter_claude_session_files()
    if not session_id:
        for path in files:
            if _claude_visible_message_count(path) >= 4:
                return path
        return files[0] if files else None
    needle = session_id.lower()
    for path in files:
        if _claude_session_id(path).lower() == needle:
            return path
    return None


def _extract_claude_content(content: Any) -> str:
    if isinstance(content, str):
        return _redact_sensitive_text(_repair_mojibake(content))
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        # Tool outputs often contain command output, file contents, and secrets.
        if ptype in ("tool_result", "tool_use"):
            continue
        if ptype == "text":
            chunks.append(str(part.get("text") or ""))
    return _redact_sensitive_text(_repair_mojibake("\n".join(chunks).strip()))


def _is_claude_noise_text(text: str) -> bool:
    s = (text or "").strip()
    return (
        not s
        or s.startswith("API Error:")
        or s in {"/status", "/login", "1", "1q", "ok"}
    )


def _claude_visible_message_count(path: Path) -> int:
    count = 0
    for obj in _iter_jsonl(path):
        if obj.get("isSidechain") or obj.get("type") not in ("user", "assistant"):
            continue
        msg = obj.get("message") or {}
        role = msg.get("role") or obj.get("type")
        if role not in ("user", "assistant"):
            continue
        text = _extract_claude_content(msg.get("content"))
        if _is_claude_noise_text(text):
            continue
        count += 1
        if count >= 4:
            return count
    return count


def _claude_session_as_markdown(session_id: str | None = None, limit: int = 20) -> tuple[str, str, str]:
    path = _find_claude_session(session_id)
    if not path:
        raise FileNotFoundError("Claude session not found")

    messages: list[dict[str, str]] = []
    cwd = ""
    for obj in _iter_jsonl(path):
        if obj.get("isSidechain"):
            continue
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            continue
        msg = obj.get("message") or {}
        role = msg.get("role") or typ
        if role not in ("user", "assistant"):
            continue
        text = _extract_claude_content(msg.get("content"))
        if _is_claude_noise_text(text):
            continue
        if not cwd:
            cwd = obj.get("cwd") or ""
        messages.append({
            "role": "User" if role == "user" else "Claude",
            "timestamp": obj.get("timestamp") or "",
            "text": text,
        })

    try:
        limit = max(1, min(int(limit), 80))
    except (TypeError, ValueError):
        limit = 20
    messages = messages[-limit:]

    sid = _claude_session_id(path)
    lines = [
        f"# Claude Session Transfer {sid}",
        "",
        "This is context imported from a local Claude Code session.",
        "Continue the user's work in Codex. Treat any credentials or tokens as unavailable; ask the user to rotate exposed secrets when relevant.",
        "",
    ]
    if cwd:
        lines.extend([f"- original cwd: `{cwd}`", ""])
    for m in messages:
        ts = f" `{m['timestamp']}`" if m.get("timestamp") else ""
        lines.extend([f"## {m['role']}{ts}", "", m["text"][:6000], ""])
    return cwd, "\n".join(lines), sid


def _write_transfer_prompt(text: str, source: str) -> Path:
    out_dir = INDEX_FILE.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_source = _re.sub(r"[^A-Za-z0-9._-]+", "-", source).strip("-") or "claude"
    path = out_dir / f"claude-transfer-{safe_source}-{int(time.time())}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _write_codex_to_claude_prompt(text: str, source: str, kind: str = "full") -> Path:
    out_dir = INDEX_FILE.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_source = _re.sub(r"[^A-Za-z0-9._-]+", "-", source).strip("-") or "codex"
    safe_kind = _re.sub(r"[^A-Za-z0-9._-]+", "-", kind).strip("-") or "full"
    path = out_dir / f"codex-to-claude-{safe_kind}-{safe_source}-{int(time.time())}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _claude_launch_prompt(full_prompt: str, full_prompt_path: Path, limit: int = 20000) -> str:
    header = (
        "The full Codex transfer transcript is saved at:\n"
        f"{full_prompt_path}\n\n"
        "Continue the user's work in Claude Code. Use the transcript below first; "
        "read the full file if more context is needed.\n\n"
    )
    budget = max(1000, limit - len(header))
    if len(full_prompt) <= budget:
        return header + full_prompt
    return header + "[Transcript excerpt: latest context only]\n\n" + full_prompt[-budget:]


def _run_codex_prompt(prompt: str, timeout: int = 180) -> tuple[int, str, str]:
    codex = _find_cli("codex")
    if not codex:
        return -1, "", "codex CLI not found on PATH"
    _SCRATCH_CWD.mkdir(exist_ok=True)
    return _run_cli(
        [codex, "exec", "--ephemeral", "--skip-git-repo-check", "-"],
        stdin_text=prompt,
        timeout=timeout,
        cwd=str(_SCRATCH_CWD),
    )


def _shell_single_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _spawn_terminal(cwd: str, command: str, title: str = APP_NAME) -> None:
    if sys.platform.startswith("win"):
        import base64 as _b64
        ps_script = (
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
            "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
            "chcp 65001 > $null\n"
            f"Set-Location -LiteralPath {_shell_single_quote(cwd)}\n"
            f"{command}\n"
        )
        encoded = _b64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
        subprocess.Popen(f'start "{title}" powershell -NoExit -EncodedCommand {encoded}', shell=True)
    elif sys.platform == "darwin":
        script = f'tell app "Terminal" to do script "cd {json.dumps(cwd)} && {command}"'
        subprocess.Popen(["osascript", "-e", script])
    else:
        subprocess.Popen(["x-terminal-emulator", "-e", f"bash -c 'cd {cwd!r} && {command}; exec bash'"])


def _purge_assistant_leftovers() -> int:
    return 0


def _session_as_markdown(project: str, sid: str) -> tuple[str, str]:
    """Return (cwd, markdown) for a given session."""
    f = _safe_session(project, sid)
    meta = _read_session_meta(f)
    lines = [f"# Codex Session {sid}", ""]
    cwd = meta.get("cwd", "") or ""
    if cwd:
        lines.append(f"- cwd: `{cwd}`")
        lines.append("")
    for obj in _iter_jsonl(f):
        if obj.get("type") != "response_item":
            continue
        payload = obj.get("payload") or {}
        ptype = payload.get("type")
        if ptype == "message":
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _extract_text(payload.get("content"))
            if role == "user" and _is_internal_codex_text(text):
                continue
            label = "User" if role == "user" else "Assistant"
        elif ptype in ("function_call", "function_call_output"):
            text = _codex_tool_text(payload)
            label = "Tool"
        else:
            continue
        if not text:
            continue
        lines.append(f"## {label}")
        lines.append(text[:4000])
        lines.append("")
    return cwd, "\n".join(lines)


def _clip_middle(text: str, limit: int = 70000) -> str:
    if len(text) <= limit:
        return text
    head_len = max(1000, limit // 3)
    tail_len = max(1000, limit - head_len)
    return (
        text[:head_len]
        + "\n\n[... transcript clipped for length ...]\n\n"
        + text[-tail_len:]
    )


def _skill_slug(value: str) -> str:
    raw = (value or "").strip().lower()
    raw = _re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not raw:
        raw = "codex-session-sop"
    if not raw[0].isalpha():
        raw = "skill-" + raw
    return raw[:72].strip("-") or "codex-session-sop"


def _single_line(value: str, fallback: str) -> str:
    text = " ".join((value or "").strip().split())
    return text or fallback


def _strip_markdown_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return s


def _strip_frontmatter(markdown: str) -> str:
    s = (markdown or "").lstrip()
    if not s.startswith("---"):
        return markdown.strip()
    lines = s.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).strip()
    return markdown.strip()


def _parse_skill_json(raw: str) -> dict:
    cleaned = _strip_markdown_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _compose_skill_markdown(name: str, description: str, body: str) -> str:
    body = _strip_frontmatter(_strip_markdown_fence(body)).strip()
    if not body:
        body = (
            "# Workflow\n\n"
            "Use the source conversation as context and extract a concise, repeatable SOP before acting."
        )
    if not body.lstrip().startswith("#"):
        body = f"# {name}\n\n{body}"
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )


def _unique_desktop_skill_dir(name: str) -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    base = desktop / name
    if not base.exists():
        return base
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = desktop / f"{name}-{stamp}"
    n = 2
    while candidate.exists():
        candidate = desktop / f"{name}-{stamp}-{n}"
        n += 1
    return candidate


def _skill_generation_prompt(project: str, sid: str, cwd: str, markdown: str) -> str:
    transcript = _clip_middle(_redact_sensitive_text(markdown), 70000)
    return (
        "You create Codex Skills from completed Codex conversations.\n"
        "Infer the reusable SOP/workflow from the transcript and write a compact skill.\n\n"
        "Return one JSON object only, with no markdown fences and no prose outside JSON:\n"
        "{\n"
        '  "name": "lowercase-kebab-case-skill-name",\n'
        '  "description": "trigger-oriented sentence describing when to use this skill",\n'
        '  "body": "SKILL.md body only, without YAML frontmatter"\n'
        "}\n\n"
        "Skill requirements:\n"
        "- The name must be ASCII lowercase kebab-case and specific to the workflow.\n"
        "- The description must tell Codex when this skill should trigger.\n"
        "- The body must be concise, procedural, and useful as an SOP.\n"
        "- Preserve concrete commands, file patterns, checks, and gotchas only when grounded in the transcript.\n"
        "- Generalize private paths, usernames, secrets, and one-off task details.\n"
        "- Do not include the raw transcript, changelog, README, install guide, or unrelated commentary.\n"
        "- Prefer Chinese if the transcript is mostly Chinese; otherwise use English.\n\n"
        f"Session project: {project}\n"
        f"Session id: {sid}\n"
        f"Working directory: {cwd or '(unknown)'}\n\n"
        "=== TRANSCRIPT START ===\n"
        + transcript
        + "\n=== TRANSCRIPT END ===\n"
    )


@_route("/api/generate-skill/<project>/<sid>", methods=["POST"])
def api_generate_skill(project: str, sid: str):
    f = _safe_session(project, sid)
    auth = _auth_status()
    if not auth["ok"]:
        return _needs_login_response(auth["reason"])

    cwd, markdown = _session_as_markdown(project, sid)
    if not markdown.strip():
        return jsonify({"ok": False, "error": "empty session"}), 400

    prompt = _skill_generation_prompt(project, sid, cwd, markdown)
    code, out, err = _run_codex_prompt(prompt, timeout=480)
    if code != 0:
        msg = (err.strip() or out.strip() or "")[:2000]
        return jsonify({
            "ok": False,
            "error": f"codex exit {code}" + (f": {msg}" if msg else ""),
            "stderr": err[:2000],
            "stdout": out[:2000],
        }), 500

    try:
        parsed = _parse_skill_json(out)
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"bad skill JSON from codex: {e}",
            "raw": out[:1200],
        }), 500

    fallback_desc = f"Use when applying the reusable SOP inferred from Codex session {sid[:8]}."
    name = _skill_slug(str(parsed.get("name") or "codex-session-sop"))
    description = _single_line(str(parsed.get("description") or ""), fallback_desc)
    body = str(parsed.get("body") or "")
    skill_md = _compose_skill_markdown(name, description, body)

    out_dir = _unique_desktop_skill_dir(name)
    skill_path = out_dir / "SKILL.md"
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
        skill_path.write_text(skill_md, encoding="utf-8")
    except OSError as e:
        return jsonify({"ok": False, "error": f"write failed: {e}"}), 500

    return jsonify({
        "ok": True,
        "name": name,
        "path": str(out_dir),
        "skillFile": str(skill_path),
        "bytes": len(skill_md.encode("utf-8")),
        "source": str(f),
    })


@_route("/api/assistant", methods=["POST"])
def api_assistant():
    """Natural-language command → JSON intent via `codex exec --ephemeral`.

    Returns {ok, action, sessionIds, reply} where action ∈ {filter, delete, merge, info, unknown}.
    """
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "empty query"}), 400

    # Build a compact catalog: up to 400 most-recent sessions, each one line
    catalog_rows = []
    for f in _dedupe_session_files(_iter_session_files())[:400]:
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        proj_name = _session_project(f)
        summary, _ = _scan_session(proj_name, f)
        title = (summary.get("summary") or summary.get("preview") or "").replace("\n", " ")[:100]
        date = datetime.fromtimestamp(m).strftime("%Y-%m-%d")
        catalog_rows.append(f"{date} | {proj_name} | {summary.get('sid') or _session_id_from_path(f)} | {title}")
    catalog = "\n".join(catalog_rows)

    auth = _auth_status()
    if not auth["ok"]:
        return _needs_login_response(auth["reason"])

    prompt = (
        "You are a session management assistant for a local Codex session browser.\n"
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
        "- action='filter' means only return sids that match the user's criteria; do not delete.\n"
        "- action='delete' only if user explicitly asks to delete; list every sid to remove.\n"
        "- action='merge' means user wants multiple sessions merged; list all sids to merge.\n"
        "- action='info' means user asks a question that needs no mutation.\n"
        "- Never invent sids that aren't in the catalog.\n"
    )

    code, out, err = _run_codex_prompt(prompt, timeout=240)
    if code != 0:
        msg = (err.strip() or out.strip() or "")[:2000]
        return jsonify({
            "ok": False,
            "error": f"codex exit {code}" + (f": {msg}" if msg else " (no output)"),
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
        return jsonify({"ok": False, "error": f"bad JSON from codex: {e}", "raw": raw[:800]}), 500

    action = parsed.get("action", "unknown")
    sids = parsed.get("sessionIds") or []
    reply = parsed.get("reply", "")
    # Attach project info so frontend can execute mutations
    resolved = []
    wanted = {str(s).lower() for s in sids}
    for f in _iter_session_files():
        file_sid = _session_id_from_path(f)
        if file_sid in wanted:
            resolved.append({"project": _session_project(f), "sid": file_sid})
    return jsonify({"ok": True, "action": action, "targets": resolved, "reply": reply})


@_route("/api/merge", methods=["POST"])
def api_merge():
    """Summarise N sessions into a single meeting-minutes markdown via Codex."""
    data = request.get_json(silent=True) or {}
    targets = data.get("targets") or []
    if not targets:
        return jsonify({"ok": False, "error": "no targets"}), 400

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
        "你是一个会话归纳助手。下面是若干条 Codex 会话原文(按顺序)。\n"
        "请生成一份会议纪要风格的合并 Markdown,包含:\n"
        "1. 总览(一段,说明共 N 次对话、主题范围)\n"
        "2. 按主题分组的要点(每组 3-8 条子项)\n"
        "3. 待办/未决事项(如有)\n"
        "4. 涉及的代码/文件清单\n"
        "不要原样复述对话,提炼为简洁条目。使用中文,合理使用 ## / - / ` 代码风格。\n\n"
        "===== 原始对话 =====\n"
        + combined
    )

    code, out, err = _run_codex_prompt(prompt, timeout=420)
    if code != 0:
        msg = (err.strip() or out.strip() or "")[:2000]
        return jsonify({"ok": False, "error": f"codex exit {code}" + (f": {msg}" if msg else "")}), 500

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


@_route("/api/claude", methods=["POST"])
def api_claude():
    """Start Claude with context imported from the selected Codex session."""
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    cwd, markdown = _session_as_markdown(project, sid)
    if not cwd or not Path(cwd).exists():
        return jsonify({"ok": False, "error": f"cwd not found: {cwd}"}), 400

    claude_path = _find_cli("claude")
    if not claude_path:
        return jsonify({"ok": False, "error": "claude CLI not found"}), 500

    prompt = (
        "This is context imported from a local Codex session. Continue the user's work in Claude Code.\n"
        "Treat any credentials or tokens in the transcript as unavailable; ask the user to rotate exposed secrets when relevant.\n\n"
        + markdown
    )
    prompt_path = _write_codex_to_claude_prompt(prompt, sid)
    launch_prompt = _claude_launch_prompt(prompt, prompt_path)
    launch_prompt_path = _write_codex_to_claude_prompt(launch_prompt, sid, kind="launch")

    try:
        if sys.platform.startswith("win"):
            claude_permission_args_ps = " ".join(_shell_single_quote(x) for x in CLAUDE_LAUNCH_PERMISSION_ARGS)
            cmd = (
                f"$prompt = Get-Content -LiteralPath {_shell_single_quote(str(launch_prompt_path))} -Raw -Encoding UTF8\n"
                f"& {_shell_single_quote(claude_path)} --add-dir {_shell_single_quote(str(prompt_path.parent))} "
                f"{claude_permission_args_ps} -- $prompt"
            )
        else:
            claude_permission_args = " ".join(CLAUDE_LAUNCH_PERMISSION_ARGS)
            cmd = (
                f"claude --add-dir {json.dumps(str(prompt_path.parent))} "
                f"{claude_permission_args} -- \"$(cat {json.dumps(str(launch_prompt_path))})\""
            )
        _spawn_terminal(cwd, cmd, "Claude")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({
        "ok": True,
        "cwd": cwd,
        "promptPath": str(prompt_path),
        "launchPromptPath": str(launch_prompt_path),
        "command": "claude --permission-mode bypassPermissions <codex-transfer-prompt>",
    })


@_route("/api/claude-to-codex", methods=["POST"])
def api_claude_to_codex():
    """Start Codex with recent context imported from a local Claude session."""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("sessionId") or "").strip() or None
    limit = data.get("limit", 20)
    override_cwd = (data.get("cwd") or "").strip()

    try:
        claude_cwd, markdown, source_sid = _claude_session_as_markdown(session_id, limit=limit)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 404

    cwd = override_cwd or claude_cwd or str(Path.home())
    if not Path(cwd).exists():
        cwd = str(Path.home())

    prompt_path = _write_transfer_prompt(markdown, source_sid)
    codex_path = _find_cli("codex")
    if not codex_path:
        return jsonify({"ok": False, "error": "codex CLI not found"}), 500

    try:
        if sys.platform.startswith("win"):
            cmd = (
                f"$prompt = Get-Content -LiteralPath {_shell_single_quote(str(prompt_path))} -Raw -Encoding UTF8\n"
                f"& {_shell_single_quote(codex_path)} $prompt"
            )
        else:
            cmd = f"codex \"$(cat {json.dumps(str(prompt_path))})\""
        _spawn_terminal(cwd, cmd, "Claude to Codex")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({
        "ok": True,
        "cwd": cwd,
        "sourceSessionId": source_sid,
        "promptPath": str(prompt_path),
        "command": "codex <claude-transfer-prompt>",
    })


@_route("/api/resume", methods=["POST"])
def api_resume():
    data = request.get_json(silent=True) or {}
    project = data.get("project", "")
    sid = data.get("sid", "")
    cwd, _ = _session_as_markdown(project, sid)
    if not cwd or not Path(cwd).exists():
        return jsonify({"ok": False, "error": f"cwd not found: {cwd}"}), 400
    _ensure_session_available(project, sid)
    codex_path = _find_cli("codex")
    if not codex_path:
        return jsonify({"ok": False, "error": "codex CLI not found"}), 500
    cmdline = f"codex resume {sid}"
    try:
        if sys.platform.startswith("win"):
            cmd = f"& {_shell_single_quote(codex_path)} resume {sid}"
        else:
            cmd = cmdline
        _spawn_terminal(cwd, cmd, "Codex Resume")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "cwd": cwd, "command": cmdline})


@_route("/api/active")
def api_active():
    """Lightweight: return just the ids of sessions with recent mtime."""
    if not SESSIONS_DIR.exists():
        return jsonify({"active": []})
    now = time.time()
    active = []
    for f in _iter_session_files(include_backups=False):
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) < ACTIVE_WINDOW_SECS:
            active.append({"project": _session_project(f), "sid": _session_id_from_path(f), "mtime": mtime})
    return jsonify({"active": active, "windowSecs": ACTIVE_WINDOW_SECS})


@_route("/api/notify", methods=["POST"])
def api_notify():
    """Show a Windows toast notification. Falls back silently if PowerShell/WinRT unavailable."""
    if sys.platform != "win32":
        return jsonify({"ok": False, "error": "only-win32"}), 400
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or APP_NAME).replace("'", "''")[:120]
    body  = (payload.get("body")  or "").replace("'", "''")[:240]
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null;"
        "$tpl=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$nodes=$tpl.GetElementsByTagName('text');"
        f"$nodes.Item(0).AppendChild($tpl.CreateTextNode('{title}')) | Out-Null;"
        f"$nodes.Item(1).AppendChild($tpl.CreateTextNode('{body}')) | Out-Null;"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($tpl);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_NAME}').Show($toast);"
    )
    try:
        flags = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


def _read_codex_auth() -> dict:
    """Return ~/.codex/auth.json without exposing token values to the UI."""
    cred_path = CODEX_HOME / "auth.json"
    if not cred_path.exists():
        return {}
    try:
        with open(cred_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _jwt_payload(token: str) -> dict:
    if not token or token.count(".") < 2:
        return {}
    try:
        import base64
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def _auth_status(buffer_secs: int = 120) -> dict:
    """Return {ok, reason}; Codex auth.json does not always expose an expiry."""
    auth = _read_codex_auth()
    if not auth:
        return {"ok": False, "reason": "no_credentials", "expiresInSec": None}
    has_api_key = bool(auth.get("OPENAI_API_KEY"))
    tokens = auth.get("tokens") or {}
    has_chatgpt_tokens = bool(tokens.get("refresh_token") or tokens.get("access_token"))
    if has_api_key or has_chatgpt_tokens:
        return {"ok": True, "reason": "ok", "expiresInSec": None}
    return {"ok": False, "reason": "no_credentials", "expiresInSec": None}


def _needs_login_response(reason: str):
    human = {
        "no_credentials": "未找到 Codex 登录凭证",
    }.get(reason, "Codex 登录需要刷新")
    return jsonify({
        "ok": False,
        "needsLogin": True,
        "error": human,
        "reason": reason,
    }), 401


@_route("/api/auth-status")
def api_auth_status():
    return jsonify(_auth_status())


@_route("/api/new-chat", methods=["POST"])
def api_new_chat():
    """Launch the sidecar Codex.exe placed next to CodexManager.exe."""
    global _NEW_CHAT_LAST_TS
    exe = _new_chat_exe()
    if not exe.exists():
        return jsonify({"ok": False, "error": f"not found: {exe}"}), 404
    with _NEW_CHAT_LOCK:
        now = time.monotonic()
        if now - _NEW_CHAT_LAST_TS < 2.0:
            return jsonify({"ok": False, "error": "please wait before launching another chat"}), 429
        _NEW_CHAT_LAST_TS = now
    try:
        env = os.environ.copy()
        env.setdefault("HTTP_PROXY", _PROXY_URL)
        env.setdefault("HTTPS_PROXY", _PROXY_URL)
        proc = subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as e:
        with _NEW_CHAT_LOCK:
            _NEW_CHAT_LAST_TS = 0.0
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "pid": proc.pid, "path": str(exe)})


@_route("/api/codex-login", methods=["POST"])
def api_codex_login():
    """Spawn a visible terminal running `codex login`. Non-blocking."""
    codex = _find_cli("codex")
    if not codex:
        return jsonify({"ok": False, "error": "codex CLI not found"}), 500
    try:
        if sys.platform.startswith("win"):
            cmd = f"& {_shell_single_quote(codex)} login"
        else:
            cmd = "codex login"
        _spawn_terminal(str(Path.home()), cmd, "Codex Login")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@_route("/api/account")
def api_account():
    """Return non-secret Codex account status."""
    auth_data = _read_codex_auth()
    auth = _auth_status()
    tokens = auth_data.get("tokens") or {}
    claims = _jwt_payload(tokens.get("id_token") or "")
    auth_mode = auth_data.get("auth_mode") or ("api-key" if auth_data.get("OPENAI_API_KEY") else "")
    email = claims.get("email") or "local Codex"
    name = claims.get("name") or (email.split("@")[0] if "@" in email else "Codex")
    last_refresh = auth_data.get("last_refresh") or ""
    return jsonify({
        "ok": auth["ok"],
        "name": name,
        "email": email,
        "plan": "ChatGPT" if auth_mode == "chatgpt" else ("API Key" if auth_mode == "api-key" else "Codex"),
        "tier": "Codex CLI",
        "lastRefresh": last_refresh,
        "auth": auth,
    })


@_route("/api/stats")
def api_stats():
    """Aggregate session activity for the usage panel (heatmap + stats)."""
    _projects, summaries = _load_session_summaries()
    if not summaries:
        return jsonify({"heatmap": [], "totals": {}})
    from collections import Counter
    day_count = Counter()            # date -> session count
    model_count = Counter()
    total_sessions = 0
    total_tokens = 0
    longest = 0
    most_msgs_day = ("", 0)
    streak_set = set()
    latest_rate_limits = {}
    latest_rate_ts = ""

    def _local_date(ts: str) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone().date().isoformat()
        except Exception:
            return str(ts)[:10]

    def _summary_activity_date(summary: dict) -> str:
        last_day = _local_date(summary.get("lastTs") or "")
        if last_day:
            return last_day
        try:
            mtime = float(summary.get("mtime") or 0)
        except Exception:
            mtime = 0
        if mtime > 0:
            return datetime.fromtimestamp(mtime).astimezone().date().isoformat()
        return _local_date(summary.get("firstTs") or "")

    for summary in summaries:
        total_sessions += 1
        first_ts = summary.get("firstTs") or ""
        last_ts = summary.get("lastTs") or first_ts
        activity_day = _summary_activity_date(summary)
        msg_count = int(summary.get("userCount") or 0) + int(summary.get("assistantCount") or 0)
        usage = summary.get("usage") or {}
        tokens = usage.get("tokens") or {}
        total_tokens += int(tokens.get("total") or 0)
        rate_limits = usage.get("rateLimits") or {}
        rate_ts = usage.get("lastTs") or last_ts or first_ts
        if isinstance(rate_limits, dict) and rate_limits and rate_ts >= latest_rate_ts:
            latest_rate_ts = rate_ts
            latest_rate_limits = rate_limits
        model = summary.get("model") or ""
        if model:
            model_count[model] += 1
        if activity_day:
            day_count[activity_day] += 1
            streak_set.add(activity_day)
            if msg_count > most_msgs_day[1]:
                most_msgs_day = (activity_day, msg_count)
        if first_ts and last_ts:
            try:
                d = (datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                     - datetime.fromisoformat(first_ts.replace("Z", "+00:00"))).total_seconds()
                if d > longest:
                    longest = d
            except Exception:
                pass

    today = datetime.now().astimezone().date()
    streak = 0
    cur = today
    while cur.isoformat() in streak_set:
        streak += 1
        cur = cur.fromordinal(cur.toordinal() - 1)

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

    def _fmt_rate_reset(unix_seconds) -> str:
        try:
            seconds = int(float(unix_seconds) - datetime.now(timezone.utc).timestamp())
        except Exception:
            return "未知"
        return _fmt_delta(seconds)

    def _fmt_window(minutes) -> str:
        try:
            n = int(minutes)
        except Exception:
            return "真实额度"
        if n <= 0:
            return "真实额度"
        if n % 1440 == 0:
            return f"{n // 1440} 天窗口"
        if n % 60 == 0:
            return f"{n // 60} 小时窗口"
        return f"{n} 分钟窗口"

    def _rate_plan(label: str, limit: dict | None) -> dict:
        if not isinstance(limit, dict):
            return {
                "label": label,
                "count": 0,
                "cap": 100,
                "reset": "运行一次会话后更新",
                "sub": "真实额度",
                "displayValue": "未获取",
                "showBar": False,
            }
        try:
            used = float(limit.get("used_percent"))
        except Exception:
            used = 0.0
        used = max(0.0, min(100.0, used))
        display = f"{used:.1f}%" if used % 1 else f"{int(used)}%"
        return {
            "label": label,
            "count": used,
            "cap": 100,
            "reset": _fmt_rate_reset(limit.get("resets_at")),
            "sub": _fmt_window(limit.get("window_minutes")),
            "displayValue": display,
            "showBar": True,
        }

    now = datetime.now().astimezone()
    today = now.date()
    today_iso = today.isoformat()
    day_sessions = 0
    week_sessions = 0
    month_sessions = 0
    week_start = today.fromordinal(today.toordinal() - today.weekday())  # Mon=0
    for summary in summaries:
        day = _summary_activity_date(summary)
        if not day:
            continue
        try:
            d = datetime.fromisoformat(day).date()
        except Exception:
            continue
        if day == today_iso:
            day_sessions += 1
        if d >= week_start:
            week_sessions += 1
        if d.year == today.year and d.month == today.month:
            month_sessions += 1

    next_midnight = datetime.combine(today.fromordinal(today.toordinal() + 1), datetime.min.time(), tzinfo=now.tzinfo)
    days_to_sunday = (6 - today.weekday()) % 7 or 7
    next_sunday = datetime.combine(today.fromordinal(today.toordinal() + days_to_sunday), datetime.min.time(), tzinfo=now.tzinfo)

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
        "favoriteModel": fav_model[0][0].replace("-", " ") if fav_model else "",
        "totalTokens": f"{(total_tokens / 1_000_000):.1f}m" if total_tokens else "0",
        "sessions": total_sessions,
        "longest": longest_txt or "—",
        "mostActiveDay": most_msgs_day[0] or "—",
        "streak": f"{streak} day{'s' if streak != 1 else ''}",
        "activeDays": active_days_total,
    }
    plans = [
        {"label": "今日会话", "count": day_sessions, "cap": 20, "reset": _fmt_delta(int((next_midnight - now).total_seconds())), "sub": "每日"},
        {"label": "本周会话", "count": week_sessions, "cap": 80, "reset": _fmt_delta(int((next_sunday - now).total_seconds())), "sub": "每周"},
        _rate_plan("短周期额度", latest_rate_limits.get("primary")),
        _rate_plan("长周期额度", latest_rate_limits.get("secondary")),
    ]
    return jsonify({
        "heatmap": grid,
        "totals": totals,
        "plans": plans,
        "recentDays": recent_days,
        "rateLimits": latest_rate_limits,
    })


def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@_route("/")
def index():
    return _no_cache(send_from_directory(str(WEB_DIR), "index.html"))


@_route("/<path:filename>")
def static_file(filename: str):
    if ".." in filename or filename.startswith("/"):
        abort(404)
    target = (WEB_DIR / filename).resolve()
    if WEB_DIR.resolve() not in target.parents:
        abort(404)
    if not target.is_file():
        abort(404)
    return _no_cache(send_from_directory(str(WEB_DIR), filename))


def _init_flask():
    """Import Flask and bind captured routes. Called once from _run_flask."""
    global Flask, Response, abort, jsonify, request, send_file, send_from_directory
    from flask import Flask as _Flask, Response as _Response, abort as _abort
    from flask import jsonify as _jsonify, request as _request
    from flask import send_file as _send_file, send_from_directory as _send_from_directory
    Flask = _Flask
    Response = _Response
    abort = _abort
    jsonify = _jsonify
    request = _request
    send_file = _send_file
    send_from_directory = _send_from_directory
    app = Flask(__name__, static_folder=None)
    for rule, options, fn in _ROUTES:
        app.add_url_rule(rule, endpoint=fn.__name__, view_func=fn, **options)
    return app


def _run_flask():
    app = _init_flask()
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


_SPLASH_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/><title>Codex Manager</title>
<style>
html,body{margin:0;height:100%}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
  background:#fafaf7;color:#6b6b66;
  font:13px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif;letter-spacing:.02em}
.r{width:28px;height:28px;border-radius:50%;border:2px solid rgba(0,0,0,.08);border-top-color:#1f1f1c;
  animation:s .9s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
@media (prefers-color-scheme:dark){body{background:#1a1a18;color:#9a9a92}.r{border-color:rgba(255,255,255,.12);border-top-color:#e8e8e2}}
</style></head><body><div class="r"></div><div>Codex Manager · 加载中…</div></body></html>"""


def main():
    print(APP_NAME)
    print(f"Sessions dir: {SESSIONS_DIR}")
    print(f"Serving on http://{HOST}:{PORT}")

    # Start Flask immediately so we can show the window before it's ready.
    threading.Thread(target=_run_flask, daemon=True).start()

    # Run the leftover purge off the critical path.
    def _bg_purge():
        purged = _purge_assistant_leftovers()
        if purged:
            print(f"Purged {purged} assistant-leftover session file(s)")
    threading.Thread(target=_bg_purge, daemon=True).start()

    # Prefer a native window via pywebview. Fall back to the default browser
    # if pywebview or its backend (e.g. WebView2 runtime) is unavailable.
    use_browser = "--browser" in sys.argv
    if not use_browser:
        try:
            import webview  # type: ignore
            window = webview.create_window(
                APP_NAME,
                html=_SPLASH_HTML,
                width=1280, height=840,
                min_size=(960, 640),
                text_select=True,
            )

            def _switch_to_app():
                if _wait_for_server():
                    try:
                        window.load_url(f"http://{HOST}:{PORT}")
                    except Exception as e:
                        print(f"load_url failed: {e}")

            threading.Thread(target=_switch_to_app, daemon=True).start()
            webview.start()
            return
        except Exception as e:
            print(f"pywebview unavailable ({e}); falling back to browser…")

    _wait_for_server()
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
