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
ACTION_NEW_SCRATCH = {"_action": "new_scratch"}
ACTION_SHOW_ALL_SCRATCH = {"_action": "show_all_scratch"}
ACTION_HELP = {"_action": "help"}
ACTION_CANCEL = {"_action": "cancel"}

# How many scratch sessions to show in the picker by default before
# offering "Show all scratch".
SCRATCH_VISIBLE_LIMIT = 10

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


def _short_path(path: str, max_len: int = 60) -> str:
    """Replace home with ~ and truncate from the left if still too long."""
    from pathlib import Path

    home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) <= max_len:
        return path
    parts = path.split("/")
    if len(parts) <= 3:
        return path
    return ".../" + "/".join(parts[-2:])


def _format_agent_row(agent: dict, name_width: int) -> str:
    from .config import resolve_account

    name = agent["name"]
    acct = resolve_account(agent)
    # Badge non-personal accounts so it's obvious which login a session uses;
    # personal (the default) stays unbadged. Fixed width keeps the path aligned.
    badge = "" if acct == "personal" else f"⟨{acct}⟩"
    return f"  {name:<{name_width}}  {badge:<8}{_short_path(agent['path'])}"


_UNCATEGORIZED = "Other"


def _group_by_category(agents: list[dict]) -> dict[str, list[dict]]:
    """Bucket agents by category. Agents without a category land in 'Other'."""
    groups: dict[str, list[dict]] = {}
    for a in agents:
        cat = a.get("category") or _UNCATEGORIZED
        groups.setdefault(cat, []).append(a)
    for cat in groups:
        # Within a category: persistent first, ephemeral after, alpha within each.
        groups[cat].sort(key=lambda a: (a["kind"] != "persistent", a["name"].lower()))
    return groups


def pick_agent(
    agents: list[dict],
    cwd_unregistered: bool = False,
    expand_scratch: bool = False,
) -> Optional[dict]:
    """Show the main picker.

    Returns one of:
    - an agent dict (selected for opening)
    - ACTION_CREATE / ACTION_MANAGE / ACTION_REGISTER_CWD / ACTION_NEW_SCRATCH
      / ACTION_SHOW_ALL_SCRATCH / ACTION_CANCEL
    - None if the user cancelled (Ctrl-C / ESC)

    Agents are grouped by their `category` field; uncategorized fall under
    "Other". Regular categories render in insertion-order from the TOML.
    The "Scratch" category is always rendered last and capped at
    SCRATCH_VISIBLE_LIMIT entries unless `expand_scratch=True`.
    """
    from .config import SCRATCH_CATEGORY

    name_width = max((len(a["name"]) for a in agents), default=12)
    name_width = max(name_width, 12)

    groups = _group_by_category(agents)

    # Build the category render order: regular categories in TOML insertion
    # order first, Scratch last (regardless of where it appears in the TOML).
    category_order: list[str] = []
    for a in agents:
        cat = a.get("category") or _UNCATEGORIZED
        if cat == SCRATCH_CATEGORY:
            continue
        if cat not in category_order:
            category_order.append(cat)
    if SCRATCH_CATEGORY in groups:
        category_order.append(SCRATCH_CATEGORY)

    # Scratch is sorted newest-first by name (timestamps in the name make
    # this equivalent to creation order without touching the filesystem).
    if SCRATCH_CATEGORY in groups:
        groups[SCRATCH_CATEGORY].sort(key=lambda a: a["name"], reverse=True)

    choices: list = []

    if cwd_unregistered:
        import os

        cwd = os.getcwd()
        short = _short_path(cwd)
        choices.append(
            questionary.Choice(
                title=f"  + Register current folder as agent  ({short})",
                value=ACTION_REGISTER_CWD,
            )
        )
        choices.append(questionary.Separator())

    for i, cat in enumerate(category_order):
        if i > 0:
            choices.append(questionary.Separator())
        choices.append(questionary.Separator(f"── {cat} ──"))

        cat_agents = groups[cat]
        if cat == SCRATCH_CATEGORY and not expand_scratch:
            visible = cat_agents[:SCRATCH_VISIBLE_LIMIT]
            hidden_count = len(cat_agents) - len(visible)
            for agent in visible:
                choices.append(
                    questionary.Choice(
                        title=_format_agent_row(agent, name_width),
                        value=agent,
                    )
                )
            if hidden_count > 0:
                choices.append(
                    questionary.Choice(
                        title=f"  · Show all scratch ({len(cat_agents)})",
                        value=ACTION_SHOW_ALL_SCRATCH,
                    )
                )
        else:
            for agent in cat_agents:
                choices.append(
                    questionary.Choice(
                        title=_format_agent_row(agent, name_width),
                        value=agent,
                    )
                )

    if agents:
        choices.append(questionary.Separator())
    choices.append(questionary.Choice(title="  + Add agent (existing folder or new)", value=ACTION_CREATE))
    choices.append(questionary.Choice(title="  + New scratch session", value=ACTION_NEW_SCRATCH))
    if agents:
        choices.append(
            questionary.Choice(
                title="  - Manage (rename / remove / edit path)", value=ACTION_MANAGE
            )
        )
    choices.append(questionary.Choice(title="  ? Help", value=ACTION_HELP))
    choices.append(questionary.Choice(title="  Quit", value=ACTION_CANCEL))

    result = questionary.select(
        "Pick an agent",
        choices=choices,
        style=_picker_style,
        instruction="(arrow keys + type to filter)",
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()
    return result


def prompt_scratch_label() -> Optional[str]:
    """Quick one-line label prompt for a scratch session.

    Returns the user-entered label (may be empty string if they hit Enter),
    or None on cancel (Esc / Ctrl-C). Caller treats empty string as
    'timestamp-only' naming.
    """
    return questionary.text(
        "Label (optional, press Enter for none):",
        style=_picker_style,
    ).ask()


CHAT_MODE_CONTINUE = "continue"  # claude --continue (most recent)
CHAT_MODE_RESUME = "resume"      # claude --resume (pick from past sessions)
CHAT_MODE_NEW = "new"            # claude (fresh)
CHAT_MODE_CANCEL = "cancel"


def prompt_chat_mode(agent_name: str) -> Optional[str]:
    """Ask how to start the agent: continue the most recent session, start a new
    one, or pick from past sessions (Claude's own `--resume` picker).

    Returns one of CHAT_MODE_CONTINUE / CHAT_MODE_NEW / CHAT_MODE_RESUME /
    CHAT_MODE_CANCEL, or None on Esc / Ctrl-C. Continue is the default — enter on
    the highlighted row keeps the prior behavior.
    """
    return questionary.select(
        f"How should we start {agent_name}?",
        choices=[
            questionary.Choice(title="Continue last session", value=CHAT_MODE_CONTINUE),
            questionary.Choice(title="New session", value=CHAT_MODE_NEW),
            questionary.Choice(title="Resume a past session…", value=CHAT_MODE_RESUME),
            questionary.Choice(title="Cancel", value=CHAT_MODE_CANCEL),
        ],
        default=CHAT_MODE_CONTINUE,
        style=_picker_style,
        use_jk_keys=False,
    ).ask()


def prompt_chat_topic() -> Optional[str]:
    """Ask for an optional topic label for a new chat.

    Used to disambiguate parallel chats on the same agent (e.g. "pricing"
    vs "onboarding"). The label is appended to the Ghostty window title so
    you can tell windows apart at a glance. Returns the entered string
    (possibly empty), or None on cancel.
    """
    return questionary.text(
        "Topic label (optional, press Enter for none):",
        style=_picker_style,
    ).ask()


def prompt_new_agent(
    default_path: Optional[str] = None,
    existing_categories: Optional[list[str]] = None,
    default_parent: Optional[str] = None,
) -> Optional[dict]:
    """Walk the user through creating a new agent. Returns the new
    agent dict (with name/path/kind/category), or None if cancelled.

    Path field default order: explicit `default_path` arg → macOS
    clipboard → `<default_parent>/<name>/` → empty.
    """
    from pathlib import Path

    name = questionary.text(
        "Name:",
        style=_picker_style,
        validate=lambda v: True if v.strip() else "name is required",
    ).ask()
    if not name:
        return None
    name = name.strip()

    if not default_path:
        default_path = _clipboard_path_or_empty()

    if not default_path and default_parent:
        default_path = str(Path(default_parent).expanduser() / name)

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

    category_choices: list = []
    if existing_categories:
        for cat in existing_categories:
            category_choices.append(questionary.Choice(title=cat, value=cat))
        category_choices.append(questionary.Separator())
    category_choices.append(questionary.Choice(title="+ New category…", value="__new__"))
    category_choices.append(questionary.Choice(title="(none)", value=None))

    category = questionary.select(
        "Category:",
        choices=category_choices,
        style=_picker_style,
    ).ask()
    if category == "__new__":
        category = questionary.text(
            "New category name:",
            style=_picker_style,
            validate=lambda v: True if v.strip() else "category is required",
        ).ask()
        if not category:
            return None
        category = category.strip()

    # Account: which Claude login the session runs under. Default to the
    # category's mapped account so the common case (e.g. Work -> work) is
    # one keypress. We only persist `account` when it's an override of what the
    # category rule already implies, keeping the registry clean.
    from .config import load_account_by_category, load_accounts

    accounts = list(load_accounts().keys())
    category_default = (load_account_by_category().get(category) if category else None) or "personal"
    account_choices = [
        questionary.Choice(
            title=(f"{a}  ·  default for this category" if a == category_default else a),
            value=a,
        )
        for a in accounts
    ]
    account = questionary.select(
        "Account:",
        choices=account_choices,
        default=next((c for c in account_choices if c.value == category_default), None),
        style=_picker_style,
    ).ask()
    if account is None:
        return None

    result = {
        "name": name,
        "path": path,
        "kind": kind,
        "category": category,
    }
    if account != category_default:
        result["account"] = account  # explicit override
    return result


def _clipboard_path_or_empty() -> str:
    """Read clipboard via pbpaste; return only if it's an existing dir, else ''."""
    import subprocess
    from pathlib import Path

    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=2, check=True
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    candidate = result.stdout.strip()
    if candidate and Path(candidate).expanduser().is_dir():
        return candidate
    return ""


def prompt_manage_agent(
    agent: dict, existing_categories: Optional[list[str]] = None
) -> Optional[dict]:
    """Ask what to do with an agent. Returns a dict like:
    - {"action": "rename", "new_name": "..."}
    - {"action": "edit_path", "new_path": "..."}
    - {"action": "edit_category", "new_category": "..." | None}
    - {"action": "remove"}
    - None if cancelled.
    """
    action = questionary.select(
        f"What to do with '{agent['name']}'?",
        choices=[
            questionary.Choice(title="Rename", value="rename"),
            questionary.Choice(title="Edit path", value="edit_path"),
            questionary.Choice(title="Change category", value="edit_category"),
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

    if action == "edit_category":
        cat_choices: list = []
        if existing_categories:
            for cat in existing_categories:
                cat_choices.append(questionary.Choice(title=cat, value=cat))
            cat_choices.append(questionary.Separator())
        cat_choices.append(questionary.Choice(title="+ New category…", value="__new__"))
        cat_choices.append(questionary.Choice(title="(none)", value=""))
        new_category = questionary.select(
            "Category:",
            choices=cat_choices,
            style=_picker_style,
        ).ask()
        if new_category is None:
            return None
        if new_category == "__new__":
            new_category = questionary.text(
                "New category name:",
                style=_picker_style,
                validate=lambda v: True if v.strip() else "category is required",
            ).ask()
            if not new_category:
                return None
            new_category = new_category.strip()
        return {"action": "edit_category", "new_category": new_category}

    if action == "remove":
        confirm = questionary.confirm(
            f"Remove '{agent['name']}'? (folder is NOT deleted)",
            default=False,
            style=_picker_style,
        ).ask()
        return {"action": "remove"} if confirm else None

    return None


def pick_agent_for_management(agents: list[dict]) -> Optional[dict]:
    """Secondary picker — used after `- Manage` is chosen from the main picker.

    Uses agent names as choice values (rather than dicts) to sidestep a
    questionary edge case where filtered-search can return the typed
    string instead of the choice value. We look up the dict by name on
    return, and bail safely if the lookup fails.
    """
    if not agents:
        console.print("[soft]No agents to manage.[/soft]")
        return None

    name_width = max(len(a["name"]) for a in agents)
    choices = [
        questionary.Choice(title=_format_agent_row(a, name_width), value=a["name"])
        for a in agents
    ]
    choices.append(questionary.Choice(title="  Cancel", value=None))

    selected = questionary.select(
        "Manage which agent?",
        choices=choices,
        style=_picker_style,
        instruction="(arrow keys + type to filter)",
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()

    if not selected or not isinstance(selected, str):
        return None
    return next((a for a in agents if a["name"] == selected), None)


def show_help(interactive: bool = True) -> None:
    """Render a styled help panel covering CLI surface, keys, and config.

    When `interactive` (the default), waits for Enter and then clears
    the screen so the caller can re-render its menu fresh. When called
    from `a-team help` on the terminal, set interactive=False so output
    behaves like a normal command (no prompt, no clear).
    """
    console.clear() if interactive else None

    console.print()
    console.print("[ateam]A-TEAM HELP[/ateam]")
    console.print(f"[border]{'━' * 40}[/border]")
    console.print()

    console.print("[nav]Commands[/nav]")
    console.print("  [nav]a-team[/nav]                          splash + picker (this menu)")
    console.print("  [nav]a-team <name>[/nav]                   open that agent directly")
    console.print("  [nav]a-team all[/nav]                      restore every persistent agent")
    console.print("  [nav]a-team new <name> [<path>][/nav]      register agent")
    console.print("  [nav]a-team here [name][/nav]              register current folder")
    console.print("  [nav]a-team scratch [label][/nav]          one-off chat in ~/.a-team/scratch/")
    console.print("  [nav]a-team rm <name>[/nav]                unregister (folder kept)")
    console.print("  [nav]a-team ls[/nav]                       plain list (pipe-friendly)")
    console.print("  [nav]a-team config show[/nav]              show settings")
    console.print("  [nav]a-team config default-parent <p>[/nav] set scaffold parent")
    console.print()

    console.print("[nav]Picker keys[/nav]")
    console.print("  [nav]↑ / ↓[/nav]                           navigate")
    console.print("  [nav]type[/nav]                            fuzzy filter")
    console.print("  [nav]Enter[/nav]                           select")
    console.print("  [nav]Esc / Ctrl-C[/nav]                    cancel / back")
    console.print()

    console.print("[nav]Path resolution for `new`[/nav]")
    console.print("  [soft]1.[/soft] explicit path argument")
    console.print("  [soft]2.[/soft] macOS clipboard (Finder: Shift+Right-click → Copy as Pathname)")
    console.print("  [soft]3.[/soft] scaffold under [nav]default_parent[/nav]/<name>/")
    console.print()

    console.print("[nav]Files[/nav]")
    console.print("  [soft]~/.config/a-team/agents.toml[/soft]   registry + settings")
    console.print()

    console.print("[soft]https://github.com/nigelglenday/a-team[/soft]")
    console.print()

    if interactive:
        console.print("[nav]Press Enter to return to the menu...[/nav]")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        console.clear()


def info(msg: str) -> None:
    console.print(f"[nav]{msg}[/nav]")


def warn(msg: str) -> None:
    console.print(f"[accent]{msg}[/accent]")


def error(msg: str) -> None:
    console.print(f"[bold red]error:[/bold red] {msg}")
