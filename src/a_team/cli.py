"""a-team — main CLI entry point.

Subcommand layout:
    a-team                  picker (splash + arrow-key + filter)
    a-team <name>           direct-open shortcut for any agent name
    a-team all              restore every persistent agent
    a-team new <name> [<path>]   path defaults to clipboard if omitted
    a-team rm <name>
    a-team ls
"""

import os
import subprocess
import sys
from pathlib import Path

import click
import questionary

from . import config, spawn, ui


def _clipboard_path() -> str | None:
    """Return clipboard contents if it looks like an existing directory.

    Designed for the Finder flow: Shift+Right-click → Copy "X" as Pathname,
    then `a-team new <name>` (no path arg) picks it up automatically.
    """
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=2, check=True
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    candidate = result.stdout.strip()
    if not candidate:
        return None
    expanded = Path(candidate).expanduser()
    if expanded.is_dir():
        return str(expanded)
    return None


class AteamGroup(click.Group):
    """Click Group that routes unknown command names to the direct-open
    shortcut handler. Lets `a-team EA` work without colliding with the
    real subcommands."""

    def get_command(self, ctx, cmd_name):
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv

        # Unknown name — treat as direct-open shortcut.
        @click.command(name=cmd_name, help=f"Open agent '{cmd_name}'.")
        def shortcut():
            agent = config.find_agent(cmd_name)
            if not agent:
                ui.error(f"agent not found: {cmd_name}")
                ui.console.print(
                    "[soft]Run `a-team ls` to see registered agents.[/soft]"
                )
                sys.exit(1)
            spawn.open_agent(agent["name"], agent["path"])

        return shortcut


@click.group(
    cls=AteamGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--no-splash", is_flag=True, help="Suppress the splash banner.")
@click.pass_context
def cli(ctx: click.Context, no_splash: bool) -> None:
    """Parallel Claude Code session manager. I love it when a plan comes together."""
    ctx.ensure_object(dict)
    ctx.obj["no_splash"] = no_splash

    if ctx.invoked_subcommand is None:
        run_picker(no_splash=no_splash)


@cli.command("all")
@click.pass_context
def all_cmd(ctx: click.Context) -> None:
    """Restore every persistent agent (post-reboot)."""
    no_splash = ctx.obj.get("no_splash", False)
    agents = config.load_agents()
    persistent = [a for a in agents if a["kind"] == "persistent"]

    if not persistent:
        ui.warn("No persistent agents registered. Run `a-team new` first.")
        return

    if not no_splash:
        ui.print_splash(len(agents))

    ui.info(f"Restoring {len(persistent)} agents…")
    spawn.open_all(persistent)
    ui.info("Done.")


@cli.command("here")
@click.argument("name", required=False, default=None)
@click.option("--ephemeral", is_flag=True, help="Mark as ephemeral (excluded from `a-team all`).")
@click.option("--category", "-c", default=None, help="Category for grouping in the picker.")
def here_cmd(name: str | None, ephemeral: bool, category: str | None) -> None:
    """Register the current working directory as an agent.

    Name defaults to the directory's basename if omitted. Useful for adding
    an existing project folder you're already working in without typing the
    full path.

    Examples:
        cd ~/Documents/some-project && a-team here
        cd ~/Documents/some-project && a-team here MyAgent -c Work
    """
    cwd = os.getcwd()
    if name is None:
        name = Path(cwd).name
    kind = "ephemeral" if ephemeral else "persistent"
    try:
        agent = config.add_agent(name, cwd, kind=kind, category=category)
    except ValueError as e:
        ui.error(str(e))
        sys.exit(1)
    cat_suffix = f", {agent['category']}" if agent.get("category") else ""
    ui.info(f"Added agent '{agent['name']}' ({agent['kind']}{cat_suffix}) → {agent['path']}")


@cli.command("new")
@click.argument("name")
@click.argument("path", required=False, default=None)
@click.option("--ephemeral", is_flag=True, help="Mark as ephemeral (excluded from `a-team all`).")
@click.option("--category", "-c", default=None, help="Category for grouping in the picker.")
def new_cmd(name: str, path: str | None, ephemeral: bool, category: str | None) -> None:
    """Register a new agent.

    PATH lookup order if omitted:
      1. macOS clipboard (Finder: Shift+Right-click → Copy as Pathname)
      2. Scaffold <default_parent>/<name>/ if `default_parent` is set
         (see `a-team config default-parent <path>`)
    """
    resolved = _resolve_new_path(name, path)
    if resolved is None:
        sys.exit(1)

    kind = "ephemeral" if ephemeral else "persistent"
    try:
        agent = config.add_agent(name, resolved, kind=kind, category=category)
    except ValueError as e:
        ui.error(str(e))
        sys.exit(1)
    cat_suffix = f", {agent['category']}" if agent.get("category") else ""
    ui.info(f"Added agent '{agent['name']}' ({agent['kind']}{cat_suffix}) → {agent['path']}")


def _resolve_new_path(name: str, path: str | None) -> str | None:
    """Decide the path for a new agent, given (possibly None) input.

    Behavior:
      - If `path` exists: register it as-is.
      - If `path` doesn't exist but its parent does: scaffold the folder
        and register it.
      - If `path` is missing entirely: try clipboard, then default_parent.
    Returns the resolved path string, or None if it couldn't be determined
    (in which case an error has already been printed).
    """
    if path:
        p = Path(path).expanduser()
        if p.is_dir():
            return str(p)
        if p.parent.is_dir():
            try:
                p.mkdir(parents=False, exist_ok=False)
            except OSError as e:
                ui.error(f"could not create {p}: {e}")
                return None
            ui.info(f"Created folder: {p}")
            return str(p)
        ui.error(f"path does not exist and parent is missing: {path}")
        return None

    clip = _clipboard_path()
    if clip:
        ui.info(f"Using path from clipboard: {clip}")
        return clip

    parent = config.get_default_parent()
    if parent:
        scaffolded = parent / name
        try:
            scaffolded.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            if not scaffolded.is_dir():
                ui.error(f"{scaffolded} exists but is not a directory")
                return None
            ui.info(f"Using existing folder: {scaffolded}")
        else:
            ui.info(f"Created folder: {scaffolded}")
        return str(scaffolded)

    ui.error("No path argument, no valid clipboard path, and no default_parent set.")
    ui.console.print(
        "[soft]Set one with: a-team config default-parent ~/Documents/other-projects[/soft]"
    )
    return None


@cli.group("config")
def config_cmd() -> None:
    """Show or set a-team settings (stored in agents.toml)."""


@config_cmd.command("show")
def config_show() -> None:
    """Print all current settings."""
    settings = config.load_settings()
    if not settings:
        ui.console.print("[soft]No settings set.[/soft]")
        return
    for k, v in settings.items():
        print(f"{k}\t{v}")


@config_cmd.command("default-parent")
@click.argument("path", required=False, default=None)
@click.option("--unset", is_flag=True, help="Clear the default_parent setting.")
def config_default_parent(path: str | None, unset: bool) -> None:
    """Set the default parent directory for new agents.

    When `a-team new <name>` is called without a path and the clipboard
    has no valid path, a folder is created under <default_parent>/<name>/.
    """
    if unset:
        config.set_setting("default_parent", None)
        ui.info("Cleared default_parent.")
        return
    if not path:
        current = config.get_setting("default_parent")
        if current:
            print(current)
        else:
            ui.console.print("[soft]default_parent is not set.[/soft]")
        return

    expanded = Path(path).expanduser().resolve()
    if not expanded.is_dir():
        ui.error(f"path is not a directory: {expanded}")
        sys.exit(1)
    config.set_setting("default_parent", str(expanded))
    ui.info(f"Set default_parent → {expanded}")


@cli.command("rm")
@click.argument("name")
def rm_cmd(name: str) -> None:
    """Unregister an agent. Does NOT delete the folder."""
    if config.remove_agent(name):
        ui.info(f"Removed agent '{name}' (folder kept).")
    else:
        ui.error(f"agent not found: {name}")
        sys.exit(1)


@cli.command("help")
def help_cmd() -> None:
    """Show the styled help panel (same as the picker's `? Help` entry)."""
    ui.show_help(interactive=False)


@cli.command("ls")
def ls_cmd() -> None:
    """List registered agents in plain text (pipe-friendly).

    Output: name <TAB> category <TAB> kind <TAB> path
    """
    agents = config.load_agents()
    if not agents:
        return
    name_width = max(len(a["name"]) for a in agents)
    cat_width = max((len(a.get("category", "")) for a in agents), default=0)
    for a in agents:
        cat = a.get("category", "")
        print(f"{a['name']:<{name_width}}\t{cat:<{cat_width}}\t{a['kind']:<10}\t{a['path']}")


# ---------------------------------------------------------------------------
# Picker mode (default when no subcommand given)
# ---------------------------------------------------------------------------


def run_picker(no_splash: bool = False) -> None:
    """Show the splash + main picker; loop until the user cancels.

    Acts as a home menu: every sub-flow (create / manage / open) returns
    here, so the user can pick multiple agents in one session.
    """
    splash_shown = False
    last_action: str | None = None

    while True:
        agents = config.load_agents()
        cwd = os.getcwd()
        is_home = cwd == str(Path.home())
        cwd_unregistered = (
            bool(agents) and not config.is_path_registered(cwd) and not is_home
        )

        if not no_splash and not splash_shown:
            ui.print_splash(len(agents))
            splash_shown = True

        if last_action:
            ui.console.print(f"  [accent]✓[/accent] [nav]{last_action}[/nav]\n")
            last_action = None

        if not agents:
            ui.info("No agents yet. Let's create your first one.")
            msg = _create_agent_flow(default_path=cwd)
            if not config.load_agents():
                return
            ui.console.clear()
            splash_shown = False
            last_action = msg
            continue

        selection = ui.pick_agent(agents, cwd_unregistered=cwd_unregistered)

        if selection is None or selection == ui.ACTION_CANCEL:
            return

        if selection == ui.ACTION_CREATE:
            msg = _create_agent_flow()
            ui.console.clear()
            splash_shown = False
            last_action = msg
            continue

        if selection == ui.ACTION_REGISTER_CWD:
            msg = _create_agent_flow(default_path=cwd)
            ui.console.clear()
            splash_shown = False
            last_action = msg
            continue

        if selection == ui.ACTION_MANAGE:
            msg = _manage_flow(agents)
            ui.console.clear()
            splash_shown = False
            last_action = msg
            continue

        if selection == ui.ACTION_HELP:
            ui.show_help()
            splash_shown = False  # screen was cleared; re-show splash
            continue

        # User picked an actual agent — open it, then return to the picker.
        spawn.open_agent(selection["name"], selection["path"])
        last_action = f"Opened {selection['name']}"


def _create_agent_flow(default_path: str | None = None) -> str | None:
    parent = config.get_default_parent()
    new = ui.prompt_new_agent(
        default_path=default_path,
        existing_categories=config.list_categories(),
        default_parent=str(parent) if parent else None,
    )
    if not new:
        return None

    # Scaffold the folder if it doesn't exist but the parent does.
    p = Path(new["path"]).expanduser()
    if not p.exists():
        if p.parent.is_dir():
            try:
                p.mkdir(parents=False, exist_ok=False)
            except OSError as e:
                ui.error(f"could not create {p}: {e}")
                return None
        else:
            ui.error(f"path does not exist and parent is missing: {p}")
            return None

    try:
        agent = config.add_agent(
            new["name"],
            str(p),
            kind=new["kind"],
            category=new.get("category"),
        )
    except ValueError as e:
        ui.error(str(e))
        return None

    cat = f" ({agent['category']})" if agent.get("category") else ""
    return f"Added '{agent['name']}'{cat}"

    # Offer to open it right away.
    open_now = questionary.confirm(
        f"Open '{agent['name']}' now?",
        default=True,
        style=questionary.Style([("question", "bold"), ("pointer", "fg:#ff8800")]),
    ).ask()
    if open_now:
        spawn.open_agent(agent["name"], agent["path"])


def _manage_flow(agents: list[dict]) -> str | None:
    target = ui.pick_agent_for_management(agents)
    if not target or not isinstance(target, dict):
        return None

    result = ui.prompt_manage_agent(
        target, existing_categories=config.list_categories()
    )
    if not result:
        return None

    try:
        if result["action"] == "rename":
            config.update_agent(target["name"], new_name=result["new_name"])
            return f"Renamed '{target['name']}' to '{result['new_name']}'"
        if result["action"] == "edit_path":
            config.update_agent(target["name"], new_path=result["new_path"])
            return f"Updated path for '{target['name']}'"
        if result["action"] == "edit_category":
            config.update_agent(target["name"], new_category=result["new_category"])
            label = result["new_category"] or "(none)"
            return f"Set category of '{target['name']}' to {label}"
        if result["action"] == "remove":
            config.remove_agent(target["name"])
            return f"Removed '{target['name']}' (folder kept)"
    except ValueError as e:
        ui.error(str(e))
        return None
    return None


def main() -> None:
    """Entry point declared in pyproject.toml."""
    cli()


if __name__ == "__main__":
    main()
