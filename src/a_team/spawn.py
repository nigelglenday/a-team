"""Open terminal windows running agents.

This module builds the launch command (the harness, the account export, the
tmux attach-or-create, the title loop) and hands it to a terminal backend from
terminals.py, which decides how it reaches the screen: a Ghostty window by
default, or a cmux workspace. See terminals.py for why Ghostty is driven by menu
clicks and clipboard paste.

Title persistence: claude emits its own OSC-0 title sequences, which
would clobber a one-time printf. A backgrounded loop re-emits the agent
name every second; a trap kills it when claude exits or the window closes.
"""

import os
import shlex
import subprocess
import time

from . import colors as _colors
from . import harness as _harness
from . import hosts as _hosts
from . import terminals as _terminals


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
    # Every agent starts with Remote Control on, named after itself. Two
    # reasons: the session is then reachable from the phone and by SendMessage
    # from other sessions, and it carries a real name instead of the
    # auto-generated `hostname-ancient-wirth` the runtime would pick.
    #
    # Local agents used to be skipped, on the grounds that you are sitting at
    # that machine anyway. That stopped being true once the phone became a real
    # surface: an M4 session cannot be named any other way. The flag is read
    # ONLY at a conversation's first registration and is ignored on every
    # resume, and `/rc` can only auto-generate, so a session that starts without
    # it can never be given a chosen name. See toolkit/TRAPS.md.
    rc_args = harness.remote_control_args(display_name)
    engine_cmd = harness.launch_command(session_mode, rc_args)
    # Account config is a local-machine concept (CLAUDE_CONFIG_DIR). A remote
    # host runs under its OWN login, so we never export it across the SSH hop.
    env = harness.env_prefix(config_dir) if not h.is_remote else ""
    body = h.launch_command(path, engine_cmd, session or "agent", env=env)
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
    group: str | None = None,
    color: str | None = None,
    tab: bool = False,
    terminal: "_terminals.Terminal | None" = None,
) -> None:
    """Open a new terminal window for the agent under the chosen harness.

    Opens a window in the chosen terminal (`terminal`, else the one resolved
    from `[settings] terminal`, default Ghostty), sets the title to
    `name` (kept set via a re-emit loop), cd's into `path`, and runs the
    harness. `session_mode` selects how it starts:
      - "continue": resume the most-recent session in this dir (fresh fallback)
      - "new":      a fresh session
      - "resume":   the harness's own past-session picker (fresh fallback)
    `topic` is an optional label appended to the window title. `group` and
    `color` are passed to the terminal (cmux uses them; Ghostty ignores them). `config_dir`
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

    term = terminal or _terminals.resolve()
    term.open(display_name, command, group=group, color=color, tab=tab)


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
    if not target.is_remote and not os.path.exists(TMUX_BIN):
        # No tmux on this machine at all. That is a definite "nothing is
        # running here", not a failure to find out, and returning None made a
        # laptop with no tmux look unreachable.
        return []
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return []
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        # tmux exits non-zero with "no server running" when nothing is up,
        # which IS an answer. An ssh failure is not.
        err = (r.stderr or "").lower()
        if "no server running" in err or "no such file" in err:
            return []
        return None
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def attach_window(session: str, host: str = _hosts.DEFAULT_HOST,
                  tab: bool = False, *, title: str | None = None,
                  group: str | None = None, color: str | None = None,
                  terminal: "_terminals.Terminal | None" = None) -> None:
    """Open a terminal window attached to an existing session on `host`.

    `title` names the window where the terminal supports it (a cmux workspace
    name); it defaults to the session name.

    Never `open -na Ghostty`: -n starts a separate copy of the application
    every time, and six accumulated that way in one evening. macOS offers no
    way to ask a running app for a new window from the command line, so this
    drives File > New Window the same way open_agent does.

    MOSH_TITLE_NOPREFIX stops mosh prefixing every tab with "[mosh] ", which
    pushed the distinguishing part of the name off the end of the tab.

    `tab` opens it as a tab in the frontmost window instead of its own window,
    which is how a row of Associates is normally arranged.

    Attach-or-create, not attach. `tmux attach -t` exits when the session is not
    there, which leaves a dead window with no error on screen: over mosh it keeps
    showing the last frame it received, so a frozen window reads as an idle one.
    After a reboot that is every window opened this way, while the ones launched
    through Host.launch_command, which already used `new-session -A`, reattach
    themselves. Fourteen windows needed rescuing by hand and three never could,
    because they named sessions that had since been renamed.

    So use the same attach-or-create the launch path uses. The only change in
    behaviour is that opening a window for a session that does not exist now
    creates an empty one instead of failing, which is what `a-team open` has
    always done.
    """
    target = _hosts.get(host)
    tmux_cmd = f"{TMUX_BIN} new-session -A -s {_terminals.zsh_safe_quote(session)}"
    if target.is_remote:
        command = "MOSH_TITLE_NOPREFIX=1; export MOSH_TITLE_NOPREFIX; " + \
            _hosts.reconnecting_attach(target.ssh_alias, tmux_cmd)
    else:
        command = tmux_cmd

    term = terminal or _terminals.resolve()
    term.open(title or session, command, group=group, color=color, tab=tab)


def open_all(agents: list[dict], delay_between: float = 1.0,
             terminal: "_terminals.Terminal | None" = None) -> None:
    """Open a window for every agent, respecting each agent's saved
    harness AND resolved account config (both previously dropped here), with a
    small delay so Ghostty settles between menu clicks."""
    from . import config  # local import avoids a module-load cycle

    term = terminal or _terminals.resolve()

    for agent in config._normalized(agents):
        harness_key = agent.get("harness", _harness.DEFAULT_HARNESS)
        open_agent(
            agent["name"],
            agent["path"],
            harness=harness_key,
            host=agent.get("host", _hosts.DEFAULT_HOST),
            session=agent.get("id"),
            config_dir=config.resolve_config_dir(agent, harness=harness_key),
            group=config.window_for(agent.get("group")),
            color=_colors.workspace_color(agent),
            terminal=term,
        )
        time.sleep(delay_between)
