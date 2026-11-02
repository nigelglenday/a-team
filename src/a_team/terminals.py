"""Terminal backends: the app that shows an agent's window.

Every agent runs inside a named tmux session (see hosts.launch_command), so the
terminal only VIEWS it. That makes the terminal a swappable part: each backend
takes a title and a shell command and puts that command on screen somewhere.

A backend is a class with:

    name                      the key used in `[settings] terminal = "..."`
    available() -> (ok, why)  can it be used right now; `why` says what to fix
    open(title, command, *, group=None, color=None, tab=False)

`group` is the agent's a-team window group (the one `a-team layout` uses) and
`color` the optional registry field `color`. A backend that has no use for one
ignores it. `tab` asks for a tab in the frontmost window instead of a window of
its own; backends with no such idea ignore it too.

Adding a terminal is one class plus one line in TERMINALS.

Where an ITerm2 backend goes: a class `ITerm2(Terminal)` with name "iterm2",
placed after `Cmux` below and registered in TERMINALS. iTerm2 has a real
AppleScript dictionary, so unlike Ghostty it needs no menu clicking or
clipboard paste: `available()` checks that /Applications/iTerm.app exists, and
`open()` runs osascript with `create window with default profile command ...`
(or `create tab ...` in the current window when `tab` is set), then sets the
session name to `title`. Pass the command through an argv item (`on run argv`)
rather than splicing it into the script source, so it never needs AppleScript
escaping. iTerm2 has no workspace groups or colors to map `group` and `color`
onto, beyond an optional tab color.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess

DEFAULT_TERMINAL = "ghostty"


def zsh_safe_quote(s: str) -> str:
    """shlex.quote, but never leaving a word that starts with `=` bare.

    shlex treats `=` as safe, so `shlex.quote("=x")` returns `=x`, and zsh
    expands a bare `=x` word into the path of a command named x (or fails with
    "x not found"). Spaces are already handled by shlex."""
    q = shlex.quote(s)
    if q.startswith("="):
        q = "'" + s + "'"  # shlex left it bare, so it has no quote to escape
    return q


def bash_wrapped(command: str) -> str:
    """Run `command` in bash whatever the user's login shell is.

    The launch command is written for bash. A terminal that types its initial
    command into the user's shell (zsh on macOS) would otherwise apply zsh's
    rules to it, such as expanding a bare `=word`. Wrapping it as one
    single-quoted argument leaves zsh nothing to interpret."""
    return f"/bin/bash -c {zsh_safe_quote(command)}"


class Terminal:
    name = ""

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def open(self, title: str, command: str, *, group: str | None = None,
             color: str | None = None, tab: bool = False) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Ghostty
# ---------------------------------------------------------------------------

_GHOSTTY_WINDOW = r'''
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
    -- paste the launch command (atomic: no dropped chars) and submit it.
    keystroke "u" using control down
    delay 0.1
    keystroke "v" using command down
    delay 0.3
    key code 36
end tell
'''


_GHOSTTY_TAB = r"""
tell application "Ghostty" to activate
tell application "System Events"
    tell process "Ghostty"
        -- A tab needs a window to live in. With none open, "New Tab" is either
        -- disabled or makes a window anyway depending on version, so be explicit.
        if (count of windows) is 0 then
            click menu item "New Window" of menu "File" of menu bar 1
            repeat 40 times
                if (count of windows) > 0 then exit repeat
                delay 0.1
            end repeat
        else
            set t0 to 0
            try
                set t0 to count of (tabs of window 1)
            end try
            click menu item "New Tab" of menu "File" of menu bar 1
            -- Wait for the tab to exist rather than guessing at a delay. Some
            -- Ghostty builds do not expose `tabs` to System Events at all; fall
            -- back to a bounded wait rather than failing the open.
            repeat 40 times
                try
                    if (count of (tabs of window 1)) > t0 then exit repeat
                on error
                    delay 0.4
                    exit repeat
                end try
                delay 0.1
            end repeat
        end if
    end tell
end tell
delay 0.4
tell application "System Events"
    keystroke "u" using control down
    delay 0.1
    keystroke "v" using command down
    delay 0.3
    key code 36
end tell
"""


class Ghostty(Terminal):
    """A window (or tab) in the RUNNING Ghostty instance.

    Opened through File > New Window over AppleScript, with the command
    delivered by clipboard paste. Why not keystroke it: System Events drops
    characters on long strings. Why not `open -na Ghostty.app --args -e`: each
    call starts a separate Ghostty instance. The clipboard is saved and
    restored around the paste, and the command reaches the clipboard through
    pbcopy's stdin, so it never passes through AppleScript escaping.

    The title is set by the command itself (an OSC title loop), so `title` is
    not used here; `group` and `color` have no Ghostty equivalent."""

    name = "ghostty"

    def available(self) -> tuple[bool, str]:
        if not shutil.which("osascript"):
            return False, "osascript not found (Ghostty windows need macOS)"
        return True, ""

    def open(self, title: str, command: str, *, group: str | None = None,
             color: str | None = None, tab: bool = False) -> None:
        try:
            prev = subprocess.run(["pbpaste"], capture_output=True).stdout
        except Exception:
            prev = b""
        subprocess.run(["pbcopy"], input=command.encode(), check=True)
        try:
            subprocess.run(["osascript", "-e",
                            _GHOSTTY_TAB if tab else _GHOSTTY_WINDOW], check=True)
        finally:
            # Restore the user's clipboard (best-effort; the paste has already
            # been consumed by the time osascript returns).
            try:
                subprocess.run(["pbcopy"], input=prev, check=False)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# cmux
# ---------------------------------------------------------------------------

CMUX_DEFAULT_BIN = "/opt/homebrew/bin/cmux"
CMUX_PASSWORD_VAR = "CMUX_SOCKET_PASSWORD"

_ACCESS_FIX = (
    "set a socket password in cmux Settings and export CMUX_SOCKET_PASSWORD, "
    "or run a-team from inside cmux"
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "group"


def parse_workspace_list(text: str) -> dict[str, str]:
    """`cmux workspace list` output -> {name: "workspace:<n>"}.

    Lines look like `  workspace:3  Name [..] (selected) *`; the trailing
    decorations are not part of the name."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.search(r"(workspace:\d+)\s+(.*)$", line)
        if not m:
            continue
        name = m.group(2).strip()
        while True:
            stripped = re.sub(r"\s*(\[[^\]]*\]|\(selected\)|\*)\s*$", "", name)
            if stripped == name:
                break
            name = stripped
        if name and name not in out:
            out[name] = m.group(1)
    return out


class Cmux(Terminal):
    """A workspace in cmux, driven through its CLI.

    One workspace per agent, named after it. Opening an agent that already has
    a workspace of that exact name selects it instead of creating a second
    one. The a-team window group becomes a cmux workspace group, created
    idempotently, and the registry's `color` field colors the workspace.

    cmux accepts socket commands only from processes it started, unless a
    password is supplied. The password is read from CMUX_SOCKET_PASSWORD (or
    the variable named by `[settings] cmux_password_env`) and passed to cmux
    in its environment, never on the command line."""

    name = "cmux"

    def __init__(self, binary: str | None = None, password_env: str | None = None):
        self.binary = binary or shutil.which("cmux") or CMUX_DEFAULT_BIN
        self.password_env = password_env

    def _env(self) -> dict:
        env = dict(os.environ)
        env["CMUX_QUIET"] = "1"
        if self.password_env and self.password_env != CMUX_PASSWORD_VAR:
            pw = os.environ.get(self.password_env)
            if pw:
                env[CMUX_PASSWORD_VAR] = pw
        return env

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.binary, *args], capture_output=True,
                              text=True, env=self._env(), timeout=15)

    def _ok(self, r: subprocess.CompletedProcess, what: str) -> str:
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or "access denied" in out.lower():
            raise RuntimeError(f"cmux {what} failed: {out.strip() or r.returncode}")
        return r.stdout or ""

    def available(self) -> tuple[bool, str]:
        if not os.path.exists(self.binary):
            return False, f"cmux CLI not found ({self.binary} or on PATH)"
        try:
            r = self._run("ping")
        except (subprocess.SubprocessError, OSError) as e:
            return False, f"cmux did not answer ({e})"
        out = (r.stdout or "") + (r.stderr or "")
        if "access denied" in out.lower():
            return False, f"cmux refused the connection: {_ACCESS_FIX}"
        if r.returncode != 0:
            return False, f"cmux is not running or not answering ({out.strip()})"
        return True, ""

    def _group_ref(self, group: str) -> str:
        out = self._ok(self._run("workspace-group", "create", "--name", group,
                                 "--idempotency-key", f"a-team-{_slug(group)}"),
                       "workspace-group create")
        m = re.search(r"workspace_group:\d+", out)
        if not m:
            raise RuntimeError(f"cmux workspace-group create gave no ref: {out.strip()}")
        return m.group(0)

    def open(self, title: str, command: str, *, group: str | None = None,
             color: str | None = None, tab: bool = False) -> None:
        existing = parse_workspace_list(
            self._ok(self._run("workspace", "list"), "workspace list"))
        if title in existing:
            # A duplicate set of workspaces is worse than no window: the agent
            # is already on screen, so bring it forward.
            self._ok(self._run("workspace", "select", existing[title]), "workspace select")
            return
        args = ["new-workspace", "--name", title, "--command", bash_wrapped(command),
                "--focus", "true"]
        if group:
            args += ["--group", self._group_ref(group), "--group-placement", "end"]
        out = self._ok(self._run(*args), "new-workspace")
        if color:
            m = re.search(r"workspace:\d+", out)
            if m:
                self._ok(self._run("workspace-action", "--workspace", m.group(0),
                                   "--action", "set-color", "--color", color),
                         "workspace-action set-color")


TERMINALS: dict[str, type[Terminal]] = {
    "ghostty": Ghostty,
    "cmux": Cmux,
}


def make(name: str, settings: dict) -> Terminal:
    if name == "cmux":
        return Cmux(password_env=settings.get("cmux_password_env"))
    return TERMINALS[name]()


def resolve(override: str | None = None, *, settings: dict | None = None,
            warn=None) -> Terminal:
    """The terminal to open windows in: `override` (a --terminal flag), else
    `[settings] terminal`, else Ghostty. An unknown or unavailable choice falls
    back to Ghostty with one line saying why."""
    if settings is None:
        from . import config
        settings = config.load_settings()
    if warn is None:
        from . import ui
        warn = ui.warn
    name = (override or settings.get("terminal") or DEFAULT_TERMINAL).strip().lower()
    if name not in TERMINALS:
        warn(f"unknown terminal {name!r} (known: {', '.join(TERMINALS)}); using Ghostty")
        return Ghostty()
    term = make(name, settings)
    if name == DEFAULT_TERMINAL:
        return term
    ok, why = term.available()
    if not ok:
        warn(f"{name} unavailable: {why}; using Ghostty")
        return Ghostty()
    return term
