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
    display_name: str, path: str, claude_cmd: str, config_dir: str | None = None
) -> str:
    r"""The plain bash command pasted into the new window. Single backslashes
    (``\\e``, ``\\a`` in source -> literal ``\e``, ``\a``) so printf emits real escapes.

    If `config_dir` is given, export CLAUDE_CONFIG_DIR first so the session (and
    the claude it launches) runs under that account's login."""
    seq = f"\\e]0;{display_name}\\a\\e]1;{display_name}\\a\\e]2;{display_name}\\a"
    env = f"export CLAUDE_CONFIG_DIR={shlex.quote(config_dir)}; " if config_dir else ""
    return (
        "{ "
        f"{env}"
        f"( while :; do printf '{seq}'; sleep 1; done ) & "
        "TPID=$!; "
        'trap "kill $TPID 2>/dev/null" EXIT INT TERM HUP; '
        f"cd {shlex.quote(path)} && {claude_cmd}; "
        "}"
    )


def open_agent(
    name: str,
    path: str,
    *,
    session_mode: str = "continue",
    topic: str | None = None,
    config_dir: str | None = None,
) -> None:
    """Open a new Ghostty window for the agent.

    Opens a window in the running Ghostty instance, sets the title to
    `name` (kept set via a re-emit loop), cd's into `path`, and runs
    Claude Code. `session_mode` selects how claude starts:
      - "continue": resume the most-recent session (`claude --continue`, fresh fallback)
      - "new":      a fresh session (`claude`)
      - "resume":   Claude's own past-session picker (`claude --resume`, fresh fallback)
    `topic` is an optional label appended to the window title. `config_dir`
    selects the Claude account (CLAUDE_CONFIG_DIR); None = personal.
    """
    _validate(name, path)
    if topic:
        _validate(topic, path)
        display_name = f"{name}: {topic}"
    else:
        display_name = name
    claude_cmd = {
        "new": "claude",
        "continue": "{ claude --continue || claude; }",
        "resume": "{ claude --resume || claude; }",
    }.get(session_mode, "{ claude --continue || claude; }")
    command = _build_command(display_name, path, claude_cmd, config_dir)

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


def open_all(agents: list[dict], delay_between: float = 1.0) -> None:
    """Open Ghostty windows for every agent, with a small delay between
    spawns so Ghostty has time to settle between menu clicks."""
    for agent in agents:
        open_agent(agent["name"], agent["path"])
        time.sleep(delay_between)
