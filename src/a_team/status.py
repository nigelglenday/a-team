"""Live status for agents: running harness sessions and unread inbox messages.

Pure data, no UI. Kept separate from `tui.py` so the view stays thin and this
can be tested (and reused) on its own.

A "live session" is an interactive harness process (``claude`` or ``codex``)
whose working directory is the agent's folder. An agent can have several
(parallel chats in the same folder), so the counts are meaningful, not just a
yes/no. Attribution is by directory AND harness, so a Claude session and a Codex
session in the same folder are never conflated — and a Codex *service* process
(``codex app-server`` / ``mcp-server`` / ``remote-control``) is never counted or
killable as if it were an agent session.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from . import harness as _harness
from .config import resolve_harness, slugify

INBOX_ROOT = Path.home() / "Documents" / "Tasks" / "messages" / "inbox"

# Session = (pid, harness_key). live_sessions() maps cwd -> list of these.
Session = tuple[int, str]

# Codex subcommands that are servers/tools, not an interactive agent session.
# These must never be attributed to an agent or killed by a stop action.
_CODEX_SERVICE_SUBCMDS = frozenset(
    {"app-server", "mcp-server", "mcp", "remote-control", "exec", "e"}
)


def _pids_for(executable: str) -> list[int]:
    """PIDs of running processes whose exact name is `executable`."""
    try:
        out = subprocess.run(
            ["pgrep", "-x", executable], capture_output=True, text=True, timeout=3
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []
    return [int(tok) for tok in out.stdout.split() if tok.isdigit()]


def _is_codex_service(pid: int) -> bool:
    """True if this codex pid is a server/tool subcommand rather than an
    interactive session. Reads the process command; on failure returns False
    (treat as a session) — the directory+harness match is the real guard, and a
    codex service almost never runs in an agent's project folder."""
    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False
    parts = out.stdout.strip().split()
    for i, tok in enumerate(parts):
        if Path(tok).name == "codex":
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            return nxt in _CODEX_SERVICE_SUBCMDS
    return False


def _agent_pids() -> dict[int, str]:
    """Map pid -> harness_key for interactive harness processes, excluding codex
    service subcommands."""
    result: dict[int, str] = {}
    for h in _harness.HARNESSES.values():
        for pid in _pids_for(h.executable):
            if h.key == "codex" and _is_codex_service(pid):
                continue
            result[pid] = h.key
    return result


def live_sessions() -> dict[str, list[Session]]:
    """Map resolved working directory -> list of (pid, harness) running there.

    One `lsof` call for every pid (not one per pid) so this is cheap enough to
    poll on a timer.
    """
    pid_harness = _agent_pids()
    if not pid_harness:
        return {}
    try:
        out = subprocess.run(
            ["lsof", "-a", "-p", ",".join(map(str, pid_harness)), "-d", "cwd", "-Fpn"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return {}

    sessions: dict[str, list[Session]] = {}
    current: int | None = None
    for line in out.stdout.splitlines():
        if line.startswith("p"):
            current = int(line[1:]) if line[1:].isdigit() else None
        elif line.startswith("n") and current is not None:
            hk = pid_harness.get(current)
            if hk is not None:
                sessions.setdefault(str(Path(line[1:])), []).append((current, hk))
    return sessions


def running_pids(agent: dict, sessions: dict[str, list[Session]] | None = None) -> list[int]:
    """PIDs of live sessions for this agent, matching its folder AND harness.

    A Codex agent's stop targets only codex pids in its folder, never a Claude
    session that happens to share the directory (and vice versa)."""
    if sessions is None:
        sessions = live_sessions()
    want = resolve_harness(agent).key
    return [pid for (pid, hk) in sessions.get(str(Path(agent["path"])), []) if hk == want]


def kill_pids(pids: list[int]) -> int:
    """SIGTERM each pid. Returns how many signals were delivered."""
    sent = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            sent += 1
        except (ProcessLookupError, PermissionError):
            continue
    return sent


def inbox_dir(agent: dict) -> Path:
    """The agent's eagent inbox directory (slug of its display name)."""
    return INBOX_ROOT / slugify(agent["name"])


def inbox_messages(agent: dict) -> list[Path]:
    """Unread messages in the agent's inbox, newest first. Read ones are archived."""
    d = inbox_dir(agent)
    if not d.is_dir():
        return []
    msgs = [p for p in d.glob("*.md") if p.is_file()]
    return sorted(msgs, key=lambda p: p.stat().st_mtime, reverse=True)


def inbox_count(agent: dict) -> int:
    return len(inbox_messages(agent))
