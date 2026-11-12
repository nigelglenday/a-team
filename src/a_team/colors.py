"""Session colors: one hue per client, read from a shared table.

The table is a tab-separated file with three columns, `match tint accent`:

    # comment
    celink	#1c2733	#5B9BD5
    *	#262624	#8A8F98

`match` is a case-insensitive substring of the agent's tmux session name or its
name; the first row that matches wins, and `*` matches anything. `tint` is the
pane background (tmux window-style), `accent` the strong color for a status
bar or a cmux workspace.

a-team keeps no copy of the colors. It reads the same file the tmux side reads
(the toolkit's `bin/session-color`), so one edit changes both. The file is,
first found: `$SESSION_COLORS`, `session_colors` under [settings], then
`~/agents/toolkit/config/session-colors.tsv`. With no file, agents have no
color and nothing is colored.
"""

from __future__ import annotations

import re

import os
from pathlib import Path

DEFAULT_TABLE = "~/agents/toolkit/config/session-colors.tsv"
# What bin/session-color prints when no row matches: the untinted background
# and a neutral gray.
FALLBACK = ("#262624", "#8A8F98")


def table_path() -> Path | None:
    """The colors table in use, or None if there is none."""
    raw = os.environ.get("SESSION_COLORS")
    if not raw:
        try:
            from . import config
            raw = config.load_settings().get("session_colors")
        except Exception:
            raw = None
    p = Path(os.path.expanduser(raw or DEFAULT_TABLE))
    return p if p.is_file() else None


def parse(text: str) -> list[tuple[str, str, str]]:
    """Rows of (match, tint, accent), skipping blanks, comments and short rows."""
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if not parts[0] or parts[0].startswith("#") or len(parts) < 3:
            continue
        rows.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rows


def lookup(text: str, rows: list[tuple[str, str, str]]) -> tuple[str, str]:
    """(tint, accent) for the first row whose match is in `text`, ignoring case."""
    low = text.lower()
    for match, tint, accent in rows:
        if match == "*" or match.lower() in low:
            return tint, accent
    return FALLBACK


def for_agent(agent: dict, path: Path | None = None) -> dict | None:
    """{"tint", "accent"} for an agent, or None when there is no table.

    Matches on the tmux session name and the agent name together, as
    bin/session-color matches on the session name and its @agent.
    """
    path = path or table_path()
    if not path:
        return None
    rows = parse(path.read_text())
    session = agent.get("session") or agent.get("id") or ""
    tint, accent = lookup(f"{session} {agent.get('name', '')}", rows)
    return {"tint": tint, "accent": accent}


def workspace_color(agent: dict) -> str | None:
    """The color for the agent's cmux workspace: its own `color` field if set
    (an explicit override), else its accent from the table."""
    if agent.get("color"):
        return agent["color"]
    c = for_agent(agent)
    # The table's catch-all accent is "default" (tmux's word for no color); cmux takes
    # only a hex value or its own color names, so anything but #RRGGBB means none.
    accent = c["accent"] if c else None
    return accent if accent and re.fullmatch(r"#[0-9A-Fa-f]{6}", accent) else None
