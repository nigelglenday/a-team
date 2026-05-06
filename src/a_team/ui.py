"""Themed Console, splash, and Questionary pickers for a-team."""

import sys
from typing import Optional

import questionary
from rich.console import Console
from rich.theme import Theme

from .splash_art import A_TEAM_BANNER

# Theme tokens — A-Team van colors (orange, red, black accents).
_theme = Theme(
    {
        "ateam": "bold orange3",
        "border": "bold red3",
        "nav": "orange1",
        "accent": "bright_red",
        "soft": "grey50",
    }
)

console = Console(theme=_theme)

# Special sentinel values returned by the main picker so cli.py can
# route to sub-flows.
ACTION_CREATE = {"_action": "create"}
ACTION_MANAGE = {"_action": "manage"}
ACTION_REGISTER_CWD = {"_action": "register_cwd"}
ACTION_CANCEL = {"_action": "cancel"}

# Questionary style shared across all pickers.
_picker_style = questionary.Style(
    [
        ("question", "bold"),
        ("pointer", "fg:#ff8800 bold"),
        ("highlighted", "bold reverse"),
        ("selected", "fg:#ff8800"),
        ("answer", "fg:#ff8800 bold"),
        ("instruction", "fg:#888888"),
    ]
)


def _is_tty() -> bool:
    return sys.stdout.isatty()


def print_splash(agent_count: int) -> None:
    """Render the orange/red A-Team splash banner with tagline.

    Suppressed when stdout is not a TTY.
    """
    if not _is_tty():
        return

    console.print(f"[border]{'═' * 52}[/border]")
    console.print(f"[ateam]{A_TEAM_BANNER}[/ateam]", end="")
    suffix = f"{agent_count} agent{'s' if agent_count != 1 else ''} ready"
    console.print(
        f"  [nav]I love it when a plan comes together.[/nav]   [soft]{suffix}[/soft]"
    )
    console.print(f"[border]{'═' * 52}[/border]\n")


def _format_agent_row(agent: dict, name_width: int) -> str:
    name = agent["name"]
    kind = agent["kind"]
    path = agent["path"]
    return f"  {name:<{name_width}}  {kind:<10}  {path}"


def pick_agent(agents: list[dict], cwd_unregistered: bool = False) -> Optional[dict]:
    """Show the main picker.

    Returns one of:
    - an agent dict (selected for opening)
    - ACTION_CREATE / ACTION_MANAGE / ACTION_REGISTER_CWD / ACTION_CANCEL
    - None if the user cancelled (Ctrl-C / ESC)
    """
    # Sort: persistent first, then ephemeral; alphabetical within each.
    persistent = sorted(
        [a for a in agents if a["kind"] == "persistent"], key=lambda a: a["name"].lower()
    )
    ephemeral = sorted(
        [a for a in agents if a["kind"] == "ephemeral"], key=lambda a: a["name"].lower()
    )
    sorted_agents = persistent + ephemeral

    name_width = max((len(a["name"]) for a in sorted_agents), default=12)
    name_width = max(name_width, 12)

    choices: list = []

    if cwd_unregistered:
        import os

        choices.append(
            questionary.Choice(
                title=f"  + Register $PWD as agent  ({os.getcwd()})",
                value=ACTION_REGISTER_CWD,
            )
        )
        choices.append(questionary.Separator())

    for agent in sorted_agents:
        choices.append(
            questionary.Choice(
                title=_format_agent_row(agent, name_width),
                value=agent,
            )
        )

    if sorted_agents:
        choices.append(questionary.Separator())
    choices.append(questionary.Choice(title="  + Create new agent", value=ACTION_CREATE))
    if sorted_agents:
        choices.append(
            questionary.Choice(
                title="  - Manage (rename / remove / edit path)", value=ACTION_MANAGE
            )
        )
    choices.append(questionary.Choice(title="  Cancel", value=ACTION_CANCEL))

    result = questionary.select(
        "Pick an agent",
        choices=choices,
        style=_picker_style,
        instruction="(arrow keys + type to filter)",
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()
    return result


def prompt_new_agent(default_path: Optional[str] = None) -> Optional[dict]:
    """Walk the user through creating a new agent. Returns the new
    agent dict (with name/path/kind), or None if cancelled."""
    name = questionary.text(
        "Name:",
        style=_picker_style,
        validate=lambda v: True if v.strip() else "name is required",
    ).ask()
    if not name:
        return None

    path = questionary.path(
        "Folder:",
        default=default_path or "",
        only_directories=True,
        style=_picker_style,
    ).ask()
    if not path:
        return None

    kind = questionary.select(
        "Kind:",
        choices=[
            questionary.Choice(
                title="persistent  (restored by `a-team all`)", value="persistent"
            ),
            questionary.Choice(
                title="ephemeral   (one-off; not restored)", value="ephemeral"
            ),
        ],
        style=_picker_style,
    ).ask()
    if not kind:
        return None

    return {"name": name.strip(), "path": path, "kind": kind}


def prompt_manage_agent(agent: dict) -> Optional[dict]:
    """Ask what to do with an agent. Returns a dict like:
    - {"action": "rename", "new_name": "..."}
    - {"action": "edit_path", "new_path": "..."}
    - {"action": "remove"}
    - None if cancelled.
    """
    action = questionary.select(
        f"What to do with '{agent['name']}'?",
        choices=[
            questionary.Choice(title="Rename", value="rename"),
            questionary.Choice(title="Edit path", value="edit_path"),
            questionary.Choice(title="Remove", value="remove"),
            questionary.Choice(title="Cancel", value="cancel"),
        ],
        style=_picker_style,
    ).ask()

    if action in (None, "cancel"):
        return None

    if action == "rename":
        new_name = questionary.text(
            "New name:",
            default=agent["name"],
            style=_picker_style,
            validate=lambda v: True if v.strip() else "name is required",
        ).ask()
        if not new_name:
            return None
        return {"action": "rename", "new_name": new_name.strip()}

    if action == "edit_path":
        new_path = questionary.path(
            "New folder:",
            default=agent["path"],
            only_directories=True,
            style=_picker_style,
        ).ask()
        if not new_path:
            return None
        return {"action": "edit_path", "new_path": new_path}

    if action == "remove":
        confirm = questionary.confirm(
            f"Remove '{agent['name']}'? (folder is NOT deleted)",
            default=False,
            style=_picker_style,
        ).ask()
        return {"action": "remove"} if confirm else None

    return None


def pick_agent_for_management(agents: list[dict]) -> Optional[dict]:
    """Secondary picker — used after `- Manage` is chosen from the main picker."""
    if not agents:
        console.print("[soft]No agents to manage.[/soft]")
        return None

    name_width = max(len(a["name"]) for a in agents)
    choices = [
        questionary.Choice(title=_format_agent_row(a, name_width), value=a)
        for a in agents
    ]
    choices.append(questionary.Choice(title="  Cancel", value=None))

    return questionary.select(
        "Manage which agent?",
        choices=choices,
        style=_picker_style,
        instruction="(arrow keys + type to filter)",
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()


def info(msg: str) -> None:
    console.print(f"[nav]{msg}[/nav]")


def warn(msg: str) -> None:
    console.print(f"[accent]{msg}[/accent]")


def error(msg: str) -> None:
    console.print(f"[bold red]error:[/bold red] {msg}")
