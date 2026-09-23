"""Spawn Ghostty windows running Claude Code.

Approach: open a new window in the *existing* Ghostty instance via the
File > New Window menu (AppleScript / System Events), then deliver the
launch command by **clipboard paste** (Cmd-V), not by keystroking it.

Why not keystroke the command (the old approach): System Events
`keystroke` types faster than a GPU terminal absorbs on long strings and
silently drops characters — notably spaces — mangling the command into
something bash can't parse (`trap"kill$TPID..."`, `cd'...'&&claude`). It's
also racy. Pasting is atomic: the whole command lands intact regardless
of length.

Why not `open -na Ghostty.app --args -e <cmd>` (native launch): it works
and needs no accessibility, but on macOS each call spawns a *separate*
Ghostty instance (no single-instance option exists), which fragments a
session manager that opens many windows. The menu approach keeps every
agent window in one instance.

The command itself is set on the clipboard with `pbcopy` (via stdin), so
it never passes through AppleScript string escaping — no quoting layers
to get wrong. The clipboard is saved and restored around the paste.

Title persistence: claude emits its own OSC-0 title sequences, which
would clobber a one-time printf. A backgrounded loop re-emits the agent
name every second; a trap kills it when claude exits or the window closes.
"""

import shlex
import subprocess
import time

from . import harness as _harness
from . import hosts as _hosts


_APPLESCRIPT = r'''
tell application "Ghostty" to activate
tell application "System Events"
    tell process "Ghostty"
        set n0 to count of windows
        click menu item "New Window" of menu "File" of menu bar 1
        -- Wait for the new window to actually appear (up to ~4s) rather than a
        -- blind delay. Window-open latency varies with system load and OS/Ghostty
        -- version; a too-short fixed delay pastes into a window that isn't ready
        -- yet, so nothing runs (the failure this fixes).
        repeat 40 times
            if (count of windows) > n0 then exit repeat
            delay 0.1
        end repeat
    end tell
end tell
delay 0.4
tell application "System Events"
    -- Clear anything the restored shell may have buffered at the prompt, then
    -- paste the launch command (atomic — no dropped chars) and submit it.
    keystroke "u" using control down
    delay 0.1
    keystroke "v" using command down
    delay 0.3
    key code 36
end tell
'''


def _validate(name: str, path: str) -> None:
    """Reject inputs that would break the launch command's quoting."""
    if any(ch in name for ch in ("'", "\n", "\r")):
        raise ValueError(f"agent name cannot contain single quotes or newlines: {name!r}")
    if any(ch in path for ch in ("'", "\n", "\r")):
        raise ValueError(f"agent path cannot contain single quotes or newlines: {path!r}")


def _build_command(
    display_name: str,
    path: str,
    harness: _harness.Harness,
    session_mode: str,
    config_dir: str | None = None,
    host: "_hosts.Host | None" = None,
    session: str | None = None,
) -> str:
    r"""The plain bash command pasted into the new window. Single backslashes
    (``\\e``, ``\\a`` in source -> literal ``\e``, ``\a``) so printf emits real escapes.

    The harness supplies both the launch verb (new/continue/resume) and the
    per-account config export — and it exports only its OWN config variable, so
    a Claude config dir can never leak into Codex."""
    seq = f"\\e]0;{display_name}\\a\\e]1;{display_name}\\a\\e]2;{display_name}\\a"
    h = host if host is not None else _hosts.LOCAL
    # Remote agents start with Remote Control on, named after the agent. Two
    # reasons: the session is then reachable from the phone and by SendMessage
    # from other sessions, and it carries a real name instead of the
    # auto-generated `hostname-ancient-wirth` the runtime would pick. Local
    # agents are left alone: you are already sitting at that machine.
    rc_args = harness.remote_control_args(display_name) if h.is_remote else ""
    engine_cmd = harness.launch_command(session_mode, rc_args)
    # Account config is a local-machine concept (CLAUDE_CONFIG_DIR). A remote
    # host runs under its OWN login, so we never export it across the SSH hop.
    env = harness.env_prefix(config_dir) if not h.is_remote else ""
    body = h.launch_command(path, engine_cmd, session or "agent")
    return (
        "{ "
        f"{env}"
        f"( while :; do printf '{seq}'; sleep 1; done ) & "
        "TPID=$!; "
        'trap "kill $TPID 2>/dev/null" EXIT INT TERM HUP; '
        f"{body}; "
        "}"
    )


def open_agent(
    name: str,
    path: str,
    *,
    session_mode: str = "continue",
    topic: str | None = None,
    config_dir: str | None = None,
    harness: str = _harness.DEFAULT_HARNESS,
    host: str = _hosts.DEFAULT_HOST,
    session: str | None = None,
) -> None:
    """Open a new Ghostty window for the agent under the chosen harness.

    Opens a window in the running Ghostty instance, sets the title to
    `name` (kept set via a re-emit loop), cd's into `path`, and runs the
    harness. `session_mode` selects how it starts:
      - "continue": resume the most-recent session in this dir (fresh fallback)
      - "new":      a fresh session
      - "resume":   the harness's own past-session picker (fresh fallback)
    `topic` is an optional label appended to the window title. `config_dir`
    selects the account config home for harnesses that support it (Claude:
    CLAUDE_CONFIG_DIR); None = default/personal. `harness` is "claude" | "codex".

    Raises RuntimeError with an actionable message if the harness executable is
    not on PATH, so a missing `codex` reports setup instead of a mangled window.
    """
    h = _harness.get(harness)
    target = _hosts.get(host)
    if target.is_remote:
        # The harness runs on the REMOTE box, so a local `which` proves nothing.
        # What matters here is that we can reach the host at all.
        if not target.reachable():
            raise RuntimeError(
                f"{target.label} is not reachable (check `ssh {target.ssh_alias}` "
                f"and that Tailscale is up)."
            )
    elif not h.is_available():
        raise RuntimeError(
            f"{h.label} is not installed or not on PATH (need `{h.executable}`). "
            f"Install it or choose a different harness."
        )
    _validate(name, path)
    if topic:
        _validate(topic, path)
        display_name = f"{name}: {topic}"
    else:
        display_name = name
    command = _build_command(
        display_name, path, h, session_mode, config_dir, host=target, session=session
    )

    # Save the clipboard, set our command, paste it, restore. pbcopy via stdin
    # means the command never hits AppleScript escaping.
    try:
        prev = subprocess.run(["pbpaste"], capture_output=True).stdout
    except Exception:
        prev = b""
    subprocess.run(["pbcopy"], input=command.encode(), check=True)
    try:
        subprocess.run(["osascript", "-e", _APPLESCRIPT], check=True)
    finally:
        # Restore the user's clipboard (best-effort; the paste has already
        # been consumed by the time osascript returns).
        try:
            subprocess.run(["pbcopy"], input=prev, check=False)
        except Exception:
            pass


TMUX_BIN = "/opt/homebrew/bin/tmux"


def tmux_sessions(host: str = _hosts.DEFAULT_HOST) -> list[str] | None:
    """tmux session names on a host, or None if the host could not be reached.

    None is not []: "cannot tell" and "nothing running" lead to different
    actions, and collapsing them makes an unreachable host look idle.
    """
    target = _hosts.get(host)
    cmd = [TMUX_BIN, "ls", "-F", "#S"]
    if target.is_remote:
        # Every argument must survive a second shell on the far side. "#S"
        # unquoted starts a COMMENT there, so `tmux ls -F` ran with no format
        # and the whole call read as an unreachable host.
        cmd = ["ssh", "-o", "ConnectTimeout=8", target.ssh_alias,
               " ".join(shlex.quote(c) for c in cmd)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        # tmux exits non-zero with "no server running" when nothing is up,
        # which IS an answer. An ssh failure is not.
        if "no server running" in (r.stderr or "").lower():
            return []
        return None
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def attach_window(session: str, host: str = _hosts.DEFAULT_HOST) -> None:
    """Open a Ghostty window attached to an existing session on `host`.

    Never `open -na Ghostty`: -n starts a separate copy of the application
    every time, and six accumulated that way in one evening. macOS offers no
    way to ask a running app for a new window from the command line, so this
    drives File > New Window the same way open_agent does.

    MOSH_TITLE_NOPREFIX stops mosh prefixing every tab with "[mosh] ", which
    pushed the distinguishing part of the name off the end of the tab.
    """
    target = _hosts.get(host)
    if target.is_remote:
        command = (
            f"MOSH_TITLE_NOPREFIX=1 mosh {target.ssh_alias} -- "
            f"{TMUX_BIN} attach -t {shlex.quote(session)}"
        )
    else:
        command = f"{TMUX_BIN} attach -t {shlex.quote(session)}"

    try:
        prev = subprocess.run(["pbpaste"], capture_output=True).stdout
    except Exception:
        prev = b""
    subprocess.run(["pbcopy"], input=command.encode(), check=True)
    try:
        subprocess.run(["osascript", "-e", _APPLESCRIPT], check=True)
    finally:
        try:
            subprocess.run(["pbcopy"], input=prev, check=False)
        except Exception:
            pass


def open_all(agents: list[dict], delay_between: float = 1.0) -> None:
    """Open Ghostty windows for every agent, respecting each agent's saved
    harness AND resolved account config (both previously dropped here), with a
    small delay so Ghostty settles between menu clicks."""
    from . import config  # local import avoids a module-load cycle

    for agent in config._normalized(agents):
        harness_key = agent.get("harness", _harness.DEFAULT_HARNESS)
        open_agent(
            agent["name"],
            agent["path"],
            harness=harness_key,
            host=agent.get("host", _hosts.DEFAULT_HOST),
            session=agent.get("id"),
            config_dir=config.resolve_config_dir(agent, harness=harness_key),
        )
        time.sleep(delay_between)
