"""Desks: one cmux workspace showing several agents side by side.

A desk is a `[[desk]]` table in agents.toml:

    [[desk]]
    name = "Client-A"
    group = "Clients"                 # optional cmux workspace group
    agents = ["Client-A Associate", "Researcher"]
    color = "Blue"                    # optional cmux color name or "#hex"
    pin = true                        # optional

The first agent fills the left half; the rest stack down the right half.
Every agent already runs in its own tmux session, so a pane only attaches to
it: rebuilding a desk closes and reopens views, and never touches an agent.

With no `[[desk]]` tables, `a-team layout --terminal cmux` behaves as before:
one workspace per agent.
"""

from __future__ import annotations

import json
import re
import time

from . import hosts as _hosts
from .terminals import Cmux, _slug, bash_wrapped, zsh_safe_quote


def parse(raw: list | None) -> list[dict]:
    """Validate the `[[desk]]` tables. Raises ValueError naming the bad desk."""
    out: list[dict] = []
    seen: set[str] = set()
    for i, d in enumerate(raw or [], 1):
        if not isinstance(d, dict):
            raise ValueError(f"desk {i}: expected a table")
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"desk {i}: `name` is required")
        name = name.strip()
        if name.lower() in seen:
            raise ValueError(f"desk {name!r}: name used twice")
        seen.add(name.lower())
        agents = d.get("agents")
        if (not isinstance(agents, list) or not agents
                or not all(isinstance(a, str) and a.strip() for a in agents)):
            raise ValueError(f"desk {name!r}: `agents` must be a non-empty list of agent names")
        for key in ("group", "color"):
            if d.get(key) is not None and not isinstance(d[key], str):
                raise ValueError(f"desk {name!r}: `{key}` must be a string")
        if not isinstance(d.get("pin", False), bool):
            raise ValueError(f"desk {name!r}: `pin` must be true or false")
        out.append({
            "name": name,
            "agents": [a.strip() for a in agents],
            "group": (d.get("group") or "").strip() or None,
            "color": d.get("color") or None,
            "pin": bool(d.get("pin", False)),
        })
    return out


def load() -> list[dict]:
    """The desks in the active registry, validated. Empty if none."""
    from . import config
    return parse(config._load_raw().get("desk"))


def index(agents: list[dict]) -> dict[str, dict]:
    """Lookup by id, and by name ignoring case."""
    out: dict[str, dict] = {}
    for a in agents:
        out.setdefault(a["id"], a)
        out.setdefault(a.get("name", "").lower(), a)
    return out


def lookup(name: str, by: dict[str, dict]) -> dict | None:
    return by.get(name) or by.get(name.lower())


def missing(desks: list[dict], agents: list[dict]) -> list[str]:
    """Agent names in desks that are not in the registry, in desk order."""
    by = index(agents)
    out: list[str] = []
    for d in desks:
        for n in d["agents"]:
            if lookup(n, by) is None and n not in out:
                out.append(n)
    return out


def desk_for(agent: dict, desks: list[dict]) -> dict | None:
    """The first desk that lists this agent, by id or name."""
    keys = {agent["id"], agent.get("name", "").lower()}
    for d in desks:
        if any(n in keys or n.lower() in keys for n in d["agents"]):
            return d
    return None


def plan_lines(desks: list[dict]) -> list[str]:
    """What `layout` will build, one line per desk, under its group."""
    lines: list[str] = []
    current = object()
    for d in desks:
        if d["group"] != current:
            current = d["group"]
            lines.append(f"  {current or '(no group)'}")
        extra = (f" [{d['color']}]" if d["color"] else "") + (" pinned" if d["pin"] else "")
        lines.append(f"    {d['name']}: {' | '.join(d['agents'])}{extra}")
    return lines


def pane_command(agent: dict) -> str:
    """The command one pane runs: attach to the agent's tmux session.

    Wrapped in bash, because cmux types it into the login shell and zsh reads
    a bare `=word` as a command lookup."""
    from .spawn import TMUX_BIN

    host = _hosts.get(agent.get("host"))
    if host.is_remote:
        session = agent.get('session') or agent['id']
        tmux = f"{TMUX_BIN} attach -t {zsh_safe_quote(session)}"
        cmd = ("MOSH_TITLE_NOPREFIX=1; export MOSH_TITLE_NOPREFIX; "
               + _hosts.reconnecting_attach(host.ssh_alias, tmux, session))
    else:
        tmux = _hosts.local_tmux() or TMUX_BIN
        cmd = f"exec {tmux} attach -t {zsh_safe_quote(agent['id'])}"
    return bash_wrapped(cmd)


def _ref(out: str, kind: str) -> str:
    m = re.search(rf"{kind}:\d+", out)
    if not m:
        raise RuntimeError(f"cmux gave no {kind} ref: {out.strip()}")
    return m.group(0)


def build(cmux: Cmux, desks: list[dict], agents: list[dict]) -> None:
    """Rebuild every desk in cmux.

    1. Close each workspace named after a desk or after an agent in a desk
       (views only; the agents keep running in tmux).
    2. Remove desk groups left empty by that, so a rebuild never shows a
       group twice.
    3. Create each group, then each desk: the first agent, a split to the
       right for the second, splits down for the rest; then color and pin.
    """
    by = index(agents)
    names = {d["name"].lower() for d in desks}
    for d in desks:
        for n in d["agents"]:
            names.add(lookup(n, by)["name"].lower())

    for title, ref in reversed(list(cmux.workspaces().items())):
        if title.lower() in names:
            cmux._ok(cmux._run("workspace", "close", ref, "--force"), "workspace close")

    group_names = {d["group"] for d in desks if d["group"]}
    try:
        raw = json.loads(cmux._run("workspace-group", "list", "--json").stdout or "[]")
        rows = raw.get("groups", []) if isinstance(raw, dict) else raw
        for g in rows or []:
            if g.get("name") in group_names:
                cmux._run("workspace-group", "ungroup", str(g.get("ref") or g.get("id")),
                          "--remove-generated-anchor")
    except (ValueError, AttributeError, TypeError):
        pass  # best effort: an old group header is cosmetic

    stamp = time.strftime("%Y%m%d%H%M%S")
    for d in desks:
        args = ["new-workspace", "--name", d["name"],
                "--command", pane_command(lookup(d["agents"][0], by)), "--focus", "false"]
        if d["group"]:
            if d["group"] not in cmux.groups:
                out = cmux._ok(cmux._run(
                    "workspace-group", "create", "--name", d["group"],
                    "--idempotency-key", f"a-team-desk-{stamp}-{_slug(d['group'])}"),
                    "workspace-group create")
                cmux.groups[d["group"]] = _ref(out, "workspace_group")
            args += ["--group", cmux.groups[d["group"]], "--group-placement", "end"]
        ws = _ref(cmux._ok(cmux._run(*args), "new-workspace"), "workspace")
        for i, n in enumerate(d["agents"][1:], 1):
            cmux._ok(cmux._run("new-split", "right" if i == 1 else "down", "--workspace", ws,
                               "--command", pane_command(lookup(n, by))), "new-split")
        if d["color"]:
            cmux._ok(cmux._run("workspace-action", "--workspace", ws, "--action", "set-color",
                               "--color", d["color"]), "workspace-action set-color")
        if d["pin"]:
            cmux._ok(cmux._run("workspace-action", "--workspace", ws, "--action", "pin"),
                     "workspace-action pin")
