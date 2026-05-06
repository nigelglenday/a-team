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


@cli.command("new")
@click.argument("name")
@click.argument("path", required=False, default=None)
@click.option("--ephemeral", is_flag=True, help="Mark as ephemeral (excluded from `a-team all`).")
@click.option("--category", "-c", default=None, help="Category for grouping in the picker.")
def new_cmd(name: str, path: str | None, ephemeral: bool, category: str | None) -> None:
    """Register a new agent.

    PATH must be an existing directory. If omitted, falls back to the macOS
    clipboard — copy a folder's path in Finder (Shift+Right-click →
    "Copy 'X' as Pathname"), then run `a-team new <name>`.
    """
    if path is None:
        path = _clipboard_path()
        if not path:
            ui.error("No path argument given and clipboard does not contain a valid directory path.")
            ui.console.print(
                "[soft]Tip: in Finder, Shift+Right-click the folder → Copy as Pathname, then re-run.[/soft]"
            )
            sys.exit(1)
        ui.info(f"Using path from clipboard: {path}")

    if not Path(path).expanduser().is_dir():
        ui.error(f"path is not a directory: {path}")
        sys.exit(1)

    kind = "ephemeral" if ephemeral else "persistent"
    try:
        agent = config.add_agent(name, path, kind=kind, category=category)
    except ValueError as e:
        ui.error(str(e))
        sys.exit(1)
    cat_suffix = f", {agent['category']}" if agent.get("category") else ""
    ui.info(f"Added agent '{agent['name']}' ({agent['kind']}{cat_suffix}) → {agent['path']}")


@cli.command("rm")
@click.argument("name")
def rm_cmd(name: str) -> None:
    """Unregister an agent. Does NOT delete the folder."""
    if config.remove_agent(name):
        ui.info(f"Removed agent '{name}' (folder kept).")
    else:
        ui.error(f"agent not found: {name}")
        sys.exit(1)


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
    """Show the splash + main picker; route based on the user's selection."""
    agents = config.load_agents()
    cwd = os.getcwd()
    cwd_unregistered = bool(agents) and not config.is_path_registered(cwd)

    if not no_splash:
        ui.print_splash(len(agents))

    if not agents:
        ui.info("No agents yet. Let's create your first one.")
        _create_agent_flow(default_path=cwd)
        return

    selection = ui.pick_agent(agents, cwd_unregistered=cwd_unregistered)

    if selection is None or selection == ui.ACTION_CANCEL:
        return

    if selection == ui.ACTION_CREATE:
        _create_agent_flow()
        return

    if selection == ui.ACTION_REGISTER_CWD:
        _create_agent_flow(default_path=cwd)
        return

    if selection == ui.ACTION_MANAGE:
        _manage_flow(agents)
        return

    # User picked an actual agent — open it.
    spawn.open_agent(selection["name"], selection["path"])


def _create_agent_flow(default_path: str | None = None) -> None:
    new = ui.prompt_new_agent(
        default_path=default_path,
        existing_categories=config.list_categories(),
    )
    if not new:
        return
    try:
        agent = config.add_agent(
            new["name"],
            new["path"],
            kind=new["kind"],
            category=new.get("category"),
        )
    except ValueError as e:
        ui.error(str(e))
        return

    cat = f", {agent['category']}" if agent.get("category") else ""
    ui.info(f"Added agent '{agent['name']}' ({agent['kind']}{cat}).")

    # Offer to open it right away.
    open_now = questionary.confirm(
        f"Open '{agent['name']}' now?",
        default=True,
        style=questionary.Style([("question", "bold"), ("pointer", "fg:#ff8800")]),
    ).ask()
    if open_now:
        spawn.open_agent(agent["name"], agent["path"])


def _manage_flow(agents: list[dict]) -> None:
    target = ui.pick_agent_for_management(agents)
    if not target:
        return

    result = ui.prompt_manage_agent(
        target, existing_categories=config.list_categories()
    )
    if not result:
        return

    try:
        if result["action"] == "rename":
            config.update_agent(target["name"], new_name=result["new_name"])
            ui.info(f"Renamed '{target['name']}' → '{result['new_name']}'.")
        elif result["action"] == "edit_path":
            config.update_agent(target["name"], new_path=result["new_path"])
            ui.info(f"Updated path for '{target['name']}'.")
        elif result["action"] == "edit_category":
            config.update_agent(target["name"], new_category=result["new_category"])
            label = result["new_category"] or "(none)"
            ui.info(f"Set category of '{target['name']}' to {label}.")
        elif result["action"] == "remove":
            config.remove_agent(target["name"])
            ui.info(f"Removed agent '{target['name']}' (folder kept).")
    except ValueError as e:
        ui.error(str(e))


def main() -> None:
    """Entry point declared in pyproject.toml."""
    cli()


if __name__ == "__main__":
    main()
