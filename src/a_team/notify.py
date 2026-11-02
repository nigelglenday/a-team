"""`a-team signal`: mark an agent's cmux workspace when it finishes or needs you.

Meant to run as a Claude Code Stop and Notification hook. It works out which
agent it is running for, finds that agent's workspace (or the desk that shows
it), and runs `cmux notify` on it, so cmux's jump-to-unread lands on the next
agent waiting for you.

Rate rules, so the sidebar stays readable:
  - at most one "done" per agent every 60 seconds;
  - Claude Code sends an `idle_prompt` notification about a minute after each
    finished turn; skip it within 10 minutes of a "done" for that agent.
The last "done" time per agent is kept in a locked JSON file, because several
hooks can fire at once.

Off switch: create ~/.config/a-team/signal-off.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

DONE_EVERY = 60
IDLE_AFTER_DONE = 600

STATE_DIR = Path.home() / ".local" / "state" / "a-team"
STATE_FILE = STATE_DIR / "signal.json"
LOG_FILE = STATE_DIR / "signal.log"
OFF_FILE = Path.home() / ".config" / "a-team" / "signal-off"

EVENTS = ("done", "needs-input")


def rate_ok(agent: str, event: str, kind: str = "", *, now: float | None = None,
            path: Path | None = None) -> tuple[bool, str]:
    """Apply the rate rules for one signal. Returns (send it, reason if not)."""
    import fcntl

    path = path or STATE_FILE
    now = time.time() if now is None else now
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            state = json.loads(fh.read() or "{}")
        except ValueError:
            state = {}
        last_done = float(state.get(agent, 0))
        if event == "done":
            if now - last_done < DONE_EVERY:
                return False, f"rate limited (done {int(now - last_done)}s ago)"
            state[agent] = now
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(state))
        elif kind == "idle_prompt" and now - last_done < IDLE_AFTER_DONE:
            return False, f"skipped idle_prompt (done {int(now - last_done)}s ago)"
    return True, ""


def body_for(event: str, text: str = "", *, now: float | None = None) -> str:
    """The sidebar line: "done at 4:32 PM" or "needs you: <message>"."""
    if event == "done":
        t = time.localtime(now) if now is not None else time.localtime()
        return "done at " + time.strftime("%I:%M %p", t).lstrip("0")
    text = " ".join(text.split())
    return (f"needs you: {text}" if text else "needs you")[:140]


def tmux_session() -> str | None:
    """The tmux session this process runs in, or None outside tmux."""
    if not os.environ.get("TMUX"):
        return None
    tmux = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
    argv = [tmux, "display-message", "-p"]
    if os.environ.get("TMUX_PANE"):
        argv += ["-t", os.environ["TMUX_PANE"]]
    try:
        r = subprocess.run(argv + ["#S"], capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return None
    return r.stdout.strip() or None


def detect(agents: list[dict], *, ref: str | None = None, session: str | None = None,
           cwd: str | None = None) -> dict | None:
    """Which agent this is.

    `ref` (the --agent flag) matches an id, tmux session or name. Otherwise
    the tmux session name matches an agent's session or id. Otherwise the
    working folder matches the deepest agent path that contains it.
    """
    def by_key(key: str) -> dict | None:
        low = key.lower()
        for field in ("id", "session", "name"):
            for a in agents:
                if str(a.get(field) or "").lower() == low:
                    return a
        return None

    if ref:
        return by_key(ref)
    if session:
        # A parallel session is "<id>-2", "<id>-3", ...
        hit = by_key(session)
        base = session.rsplit("-", 1)
        if hit is None and len(base) == 2 and base[1].isdigit():
            hit = by_key(base[0])
        if hit:
            return hit
    if cwd:
        here = os.path.realpath(cwd)
        best, best_len = None, -1
        for a in agents:
            p = a.get("path")
            if not p:
                continue
            p = os.path.realpath(os.path.expanduser(p))
            if (here == p or here.startswith(p.rstrip("/") + "/")) and len(p) > best_len:
                best, best_len = a, len(p)
        return best
    return None


def _log(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def send(event: str, *, text: str = "", kind: str = "", ref: str | None = None,
         agents: list[dict] | None = None, desks: list[dict] | None = None,
         cmux=None, session: str | None = None, cwd: str | None = None) -> tuple[bool, str]:
    """Resolve the agent and its workspace, apply the rate rules, notify.

    Returns (notified, outcome). Never raises for an expected failure: a hook
    must not break the turn it runs after."""
    from . import config, desks as _desks, terminals

    if OFF_FILE.exists():
        return False, f"off ({OFF_FILE} exists)"
    if kind == "auth_success":
        return False, "ignored auth_success"
    if agents is None:
        agents = config.load_agents_normalized()
    if desks is None:
        try:
            desks = _desks.load()
        except ValueError:
            desks = []
    if ref is None and session is None and cwd is None:
        session, cwd = tmux_session(), os.getcwd()
    agent = detect(agents, ref=ref, session=session, cwd=cwd)
    if agent is None:
        return False, "no a-team agent matches this session"
    desk = _desks.desk_for(agent, desks)
    workspace = desk["name"] if desk else agent["name"]
    tag = f"agent={agent['name']!r} workspace={workspace!r} event={event}"

    ok, why = rate_ok(agent["id"], event, kind)
    if not ok:
        _log(f"{tag} -> {why}")
        return False, why
    body = body_for(event, text)
    if cmux is None:
        cmux = terminals.make("cmux", config.load_settings())
    try:
        listed = cmux.workspaces()
        wref = listed.get(workspace) or next(
            (r for n, r in listed.items() if n.lower() == workspace.lower()), None)
        if not wref:
            _log(f"{tag} -> no cmux workspace named {workspace!r}")
            return False, f"no cmux workspace named {workspace!r}"
        cmux.notify(wref, agent["name"], body)
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        _log(f"{tag} -> not sent: {e}")
        return False, f"not sent: {e}"
    _log(f"{tag} ref={wref} -> notified")
    return True, f"notified {workspace} ({wref}): {body}"


def read_payload(stream) -> dict:
    """The hook's JSON payload from stdin, or {} when there is none."""
    try:
        if stream is None or stream.isatty():
            return {}
        data = stream.read()
    except (OSError, ValueError):
        return {}
    try:
        d = json.loads(data) if data.strip() else {}
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def hook_config(command: str) -> dict:
    """The Claude Code hooks block: Stop -> done, Notification -> needs-input."""
    return {"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": f"{command} done"}]}],
        "Notification": [{"hooks": [{"type": "command", "command": f"{command} needs-input"}]}],
    }}


def merge_hooks(settings: dict, hooks: dict) -> tuple[dict, bool]:
    """Add the hooks to a settings dict, skipping any already present.

    Returns (new settings, changed). Other hooks are left as they are."""
    out = json.loads(json.dumps(settings))
    have = out.setdefault("hooks", {})
    changed = False
    for event, entries in hooks["hooks"].items():
        current = have.setdefault(event, [])
        existing = {h.get("command") for e in current for h in e.get("hooks", [])}
        for e in entries:
            if all(h["command"] in existing for h in e["hooks"]):
                continue
            current.append(e)
            changed = True
    return out, changed
