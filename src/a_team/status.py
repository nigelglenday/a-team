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


# --- remote hosts ----------------------------------------------------------
#
# Agents can live on another machine (see hosts.py), where local pgrep/lsof see
# nothing. Without this, every remote agent reads as "stopped" while it is
# happily running. The probe is one SSH round trip per host, cached, because the
# TUI repaints on a timer.

_REMOTE_TTL = 8.0  # seconds; long enough that a repaint never re-SSHes
_remote_cache: dict[str, tuple[float, dict[str, list[Session]]]] = {}

# Prints one "pid<TAB>harness<TAB>cwd" line per interactive session, after a
# single "HOME<TAB><path>" line so a `~` in the registry can be expanded against
# the REMOTE home rather than this machine's.
_PROBE = r"""printf 'HOME\t%s\n' "$HOME"
for exe in claude codex; do
  for p in $(pgrep -x $exe 2>/dev/null); do
    d=$(lsof -a -p $p -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
    [ -n "$d" ] && printf '%s\t%s\t%s\n' "$p" "$exe" "$d"
  done
done"""


def remote_sessions(host_key: str, *, force: bool = False) -> dict[str, list[Session]] | None:
    """Map cwd -> sessions on a remote host, or None if it could not be reached.

    None is meaningful and must not be flattened into {}: "cannot tell" is a
    different answer from "nothing running", and the UI shows them differently.
    """
    import time

    from . import hosts as _hosts

    now = time.monotonic()
    if not force:
        hit = _remote_cache.get(host_key)
        if hit and (now - hit[0]) < _REMOTE_TTL:
            return hit[1]
    try:
        host = _hosts.get(host_key)
    except (ValueError, KeyError):
        return None
    if not host.is_remote:
        return live_sessions()
    try:
        out = host.run(_PROBE, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0:
        return None

    home = ""
    found: dict[str, list[Session]] = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] == "HOME":
            home = parts[1].rstrip("/")
            continue
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        pid, hk, cwd = int(parts[0]), parts[1], parts[2]
        found.setdefault(cwd, []).append((pid, hk))
    _remote_cache[host_key] = (now, found)
    _remote_cache[host_key + "\x00home"] = (now, home)  # type: ignore[assignment]
    return found


def _remote_home(host_key: str) -> str:
    entry = _remote_cache.get(host_key + "\x00home")
    return entry[1] if entry else ""  # type: ignore[return-value]


def _match_path(agent_path: str, home: str) -> str:
    """Registry paths for remote agents keep a literal `~`; expand it against
    that machine's home, not this one's."""
    if agent_path.startswith("~"):
        return (home + agent_path[1:]) if home else agent_path
    return str(Path(agent_path))


def agent_state(agent: dict) -> tuple[str, int]:
    """(state, session_count) where state is 'running' | 'stopped' | 'unknown'.

    'unknown' means the agent lives on a host we could not reach just now. That
    is deliberately distinct from 'stopped': reporting a remote agent as stopped
    because SSH timed out is a lie the UI should not tell.
    """
    from . import hosts as _hosts

    host_key = (agent.get("host") or _hosts.DEFAULT_HOST).strip().lower()
    want = resolve_harness(agent).key

    if host_key == _hosts.DEFAULT_HOST:
        sessions = live_sessions()
        hits = [1 for (_, hk) in sessions.get(str(Path(agent["path"])), []) if hk == want]
        return ("running" if hits else "stopped", len(hits))

    found = remote_sessions(host_key)
    if found is None:
        return ("unknown", 0)
    key = _match_path(str(agent["path"]), _remote_home(host_key))
    hits = [1 for (_, hk) in found.get(key, []) if hk == want]
    return ("running" if hits else "stopped", len(hits))


def running_pids(agent: dict, sessions: dict[str, list[Session]] | None = None) -> list[int]:
    """PIDs of live LOCAL sessions for this agent, matching folder AND harness.

    A Codex agent's stop targets only codex pids in its folder, never a Claude
    session that happens to share the directory (and vice versa).

    Remote agents always return [] — deliberately. These pids are fed to
    kill_pids(), which calls os.kill() on THIS machine: returning a remote pid
    would signal whatever unrelated local process happens to hold that number.
    Stopping a remote agent has to go over SSH, so it is not offered here.
    """
    from . import hosts as _hosts

    if (agent.get("host") or _hosts.DEFAULT_HOST).strip().lower() != _hosts.DEFAULT_HOST:
        return []
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
