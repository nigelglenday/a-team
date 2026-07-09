"""Live status for agents: running Claude Code sessions and unread inbox messages.

Pure data, no UI. Kept separate from `tui.py` so the view stays thin and this
can be tested (and reused) on its own.

A "live session" is a `claude` process whose working directory is the agent's
folder. An agent can have several (parallel chats in the same folder), so the
counts are meaningful, not just a yes/no.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from .config import slugify

INBOX_ROOT = Path.home() / "Documents" / "Tasks" / "messages" / "inbox"


def _claude_pids() -> list[int]:
    """PIDs of running `claude` processes (the CLI itself, not helpers)."""
    try:
        out = subprocess.run(
            ["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=3
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []
    return [int(tok) for tok in out.stdout.split() if tok.isdigit()]


def live_sessions() -> dict[str, list[int]]:
    """Map resolved working directory -> pids of claude processes running there.

    One `lsof` call for every pid (not one per pid) so this is cheap enough to
    poll on a timer.
    """
    pids = _claude_pids()
    if not pids:
        return {}
    try:
        out = subprocess.run(
            ["lsof", "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fpn"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return {}

    sessions: dict[str, list[int]] = {}
    current: int | None = None
    for line in out.stdout.splitlines():
        if line.startswith("p"):
            current = int(line[1:]) if line[1:].isdigit() else None
        elif line.startswith("n") and current is not None:
            sessions.setdefault(str(Path(line[1:])), []).append(current)
    return sessions


def running_pids(agent: dict, sessions: dict[str, list[int]] | None = None) -> list[int]:
    """PIDs of live sessions for this agent (empty list if none)."""
    if sessions is None:
        sessions = live_sessions()
    return sessions.get(str(Path(agent["path"])), [])


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
