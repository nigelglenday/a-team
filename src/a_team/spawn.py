"""Spawn Ghostty windows running Claude Code via AppleScript.

Ghostty's `+new-window` CLI is unsupported on macOS, so we drive the
GUI via AppleScript "System Events" — same pattern as the existing
Launchpad-style .app bundles.

Title persistence: Claude Code (and other apps) frequently emit their
own OSC-0 title sequences, which would clobber a one-time printf at
the start. To keep the agent name visible, we spawn a background loop
that re-emits the OSC-0 sequence every second. A trap on the parent
shell cleans it up when claude exits or the window is closed.
"""

import subprocess
import time

# Bash command keystroked into the new Ghostty window. The grouped
# command:
#   1. Backgrounds a loop that re-emits OSC-0 every second so other
#      programs (e.g., claude) can't permanently clobber the title
#   2. Stores its PID and traps EXIT/HUP/INT/TERM to kill it on cleanup
#   3. cd's into the agent folder
#   4. Runs claude --continue
#
# Raw strings throughout so the `\e`, `\a`, and `\"` characters survive
# Python → AppleScript → terminal as literal `\e`, `\a`, and `"`.
_BASH_COMMAND = (
    r"{ "
    r"( while :; do printf '\\e]0;__NAME__\\a\\e]1;__NAME__\\a\\e]2;__NAME__\\a'; sleep 1; done ) & "
    r"TPID=$!; "
    r'trap \"kill $TPID 2>/dev/null\" EXIT INT TERM HUP; '
    r"cd '__PATH__' && __CLAUDE_CMD__; "
    r"}"
)

_APPLESCRIPT_TEMPLATE = r'''
tell application "Ghostty"
    activate
end tell
tell application "System Events"
    tell process "Ghostty"
        click menu item "New Window" of menu "File" of menu bar 1
    end tell
end tell
delay 0.5
tell application "System Events"
    -- Clear any text the restored shell may have buffered at the
    -- prompt (Ghostty sometimes restores the prior session's typed-
    -- but-unsubmitted characters). Ctrl-U deletes from cursor to
    -- beginning of line in both zsh and bash.
    keystroke "u" using control down
    delay 0.05
    keystroke "__BASH_COMMAND__"
    key code 36
end tell
'''


def _validate(name: str, path: str) -> None:
    """Reject inputs that would break AppleScript or bash quoting."""
    if any(ch in name for ch in ('"', "\\", "\n", "\r")):
        raise ValueError(f"agent name cannot contain quotes, backslashes, or newlines: {name!r}")
    if any(ch in path for ch in ("'", "\n", "\r")):
        raise ValueError(f"agent path cannot contain single quotes or newlines: {path!r}")


def open_agent(
    name: str,
    path: str,
    *,
    fresh_chat: bool = False,
    topic: str | None = None,
) -> None:
    """Open a new Ghostty window for the agent.

    Spawns a Ghostty window, sets the title to `name` (and keeps it
    set via a re-emit loop so other programs can't clobber it), cd's
    into `path`, and runs Claude Code.

    By default resumes the most-recent session (`claude --continue`,
    falling back to fresh if no session exists). Pass `fresh_chat=True`
    to force a new session — useful for running multiple parallel
    chats in the same folder on different topics.

    `topic` is an optional label appended to the window title (e.g.
    "Navigator: pricing") so parallel chats on the same agent are
    visually distinguishable in Ghostty.
    """
    _validate(name, path)
    if topic:
        _validate(topic, path)  # same quoting rules apply to title content
        display_name = f"{name}: {topic}"
    else:
        display_name = name
    claude_cmd = "claude" if fresh_chat else "{ claude --continue || claude; }"
    bash = (
        _BASH_COMMAND
        .replace("__NAME__", display_name)
        .replace("__PATH__", path)
        .replace("__CLAUDE_CMD__", claude_cmd)
    )
    script = _APPLESCRIPT_TEMPLATE.replace("__BASH_COMMAND__", bash)
    subprocess.run(["osascript", "-e", script], check=True)


def open_all(agents: list[dict], delay_between: float = 1.0) -> None:
    """Open Ghostty windows for every agent, with a small delay between
    spawns so Ghostty has time to settle between menu clicks."""
    for agent in agents:
        open_agent(agent["name"], agent["path"])
        time.sleep(delay_between)
