"""Spawn Ghostty windows running Claude Code via AppleScript.

Ghostty's `+new-window` CLI is unsupported on macOS, so we drive the
GUI via AppleScript "System Events" — same pattern as the existing
Launchpad-style .app bundles.
"""

import subprocess
import time

# The keystroked command sets the window title via OSC-0, then cd's
# and resumes the most recent Claude Code session in that folder.
#
# The double backslashes in the AppleScript become single backslashes
# in the runtime AppleScript string, then bash's printf interprets
# \e (ESC) and \a (BEL) to emit the OSC-0 title sequence.
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
    keystroke "printf '\\e]0;{name}\\a' && cd '{path}' && claude --continue"
    key code 36
end tell
'''


def open_agent(name: str, path: str) -> None:
    """Open a new Ghostty window for the agent.

    Spawns a Ghostty window, sets the title to `name`, cd's into
    `path`, and runs `claude --continue` to resume the most recent
    session in that folder.
    """
    script = _APPLESCRIPT_TEMPLATE.format(name=name, path=path)
    subprocess.run(["osascript", "-e", script], check=True)


def open_all(agents: list[dict], delay_between: float = 1.0) -> None:
    """Open Ghostty windows for every agent, with a small delay between
    spawns so Ghostty has time to settle between menu clicks."""
    for agent in agents:
        open_agent(agent["name"], agent["path"])
        time.sleep(delay_between)
