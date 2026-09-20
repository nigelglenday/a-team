"""Full-screen live dashboard for a-team (`a-team tui`).

A thin view over `status.py` (live sessions, inbox counts) and `config.py`
(the registry). Opening an agent delegates to `spawn.open_agent`, the same
path the questionary picker uses, so there is one launch code path.

Requires the optional `tui` extra: pip install "a-team[tui]"
"""

from __future__ import annotations

from functools import partial

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import config, spawn, status
from .ui import _short_path

PREVIEW_LINES = 5
PREVIEW_MESSAGES = 10
CLEAR_ACCOUNT = "__clear__"


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------


class ChoiceModal(ModalScreen[str | None]):
    """Pick one of several options. Dismisses with the option's value, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._title, classes="modal-title")
            yield OptionList(*[Option(label, id=value) for label, value in self._options])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class InputModal(ModalScreen[str | None]):
    """Single-line text entry. Dismisses with the text, or None on escape."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, initial: str = "") -> None:
        super().__init__()
        self._title = title
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._title, classes="modal-title")
            yield Input(value=self._initial)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Destructive-action confirmation. y = yes, anything else = no."""

    BINDINGS = [
        Binding("y", "yes", "Yes", show=False),
        Binding("n,escape", "no", "No", show=False),
    ]

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Label(self._title, classes="modal-title")
            yield Label("[b]y[/b] confirm    [b]n[/b] cancel", classes="modal-hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class InboxModal(ModalScreen[None]):
    """Read-only peek at an agent's unread inbox messages."""

    BINDINGS = [Binding("escape,q", "close", "Close", show=False)]

    def __init__(self, agent: dict) -> None:
        super().__init__()
        self._agent = agent

    def compose(self) -> ComposeResult:
        msgs = status.inbox_messages(self._agent)
        with Vertical(classes="modal-box modal-tall"):
            yield Label(
                f"Inbox: {self._agent['name']}  ({len(msgs)} unread)", classes="modal-title"
            )
            with VerticalScroll():
                if not msgs:
                    yield Static("[dim]No unread messages.[/dim]")
                for path in msgs[:PREVIEW_MESSAGES]:
                    yield Static(Text(path.name, style="bold cyan"))
                    yield Static(Text(self._preview(path), style="dim"), classes="preview")
                if len(msgs) > PREVIEW_MESSAGES:
                    yield Static(f"[dim]... and {len(msgs) - PREVIEW_MESSAGES} more[/dim]")
            yield Label(f"[dim]{status.inbox_dir(self._agent)}[/dim]", classes="modal-hint")

    @staticmethod
    def _preview(path) -> str:
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            return f"(unreadable: {exc})"
        lines = [ln for ln in text.splitlines() if ln.strip()][:PREVIEW_LINES]
        return "\n".join(lines) or "(empty)"

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


class FilterInput(Input):
    BINDINGS = [Binding("escape", "clear_filter", "Clear", show=False)]

    def action_clear_filter(self) -> None:
        self.value = ""
        self.display = False
        self.app.query_one(DataTable).focus()


class ATeamTUI(App):
    TITLE = "a-team"
    SUB_TITLE = "live agent dashboard"

    CSS = """
    ModalScreen { align: center middle; background: $background 70%; }
    .modal-box {
        width: 68; height: auto; max-height: 80%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    .modal-tall { height: 80%; }
    .modal-title { text-style: bold; margin-bottom: 1; }
    .modal-hint { margin-top: 1; }
    .preview { margin-bottom: 1; }
    #filter { display: none; }
    """

    BINDINGS = [
        Binding("slash", "filter", "Filter"),
        Binding("v", "inbox", "Inbox"),
        Binding("k", "kill", "Kill"),
        Binding("m", "manage", "Manage"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._agents: list[dict] = []
        self._sessions: dict[str, list[int]] = {}
        self._counts: dict[str, int] = {}
        self._states: dict[str, tuple[str, int]] = {}
        self._row_agents: list[dict | None] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield FilterInput(placeholder="filter agents...", id="filter")
        yield DataTable(id="agents", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("", "agent", "account", "inbox", "path")
        table.focus()
        self._agents = config.load_agents()
        self.refresh_data()
        self.set_interval(2.0, self.refresh_data)

    # -- data ---------------------------------------------------------------

    @work(thread=True, exclusive=True, group="refresh")
    def refresh_data(self) -> None:
        """Gather live state off the UI thread, then hand it to _render."""
        sessions = status.live_sessions()
        counts = {a["name"]: status.inbox_count(a) for a in self._agents}
        # agent_state covers remote hosts too (one cached SSH probe per host),
        # so an agent running on another machine no longer reads as stopped.
        states = {a["name"]: status.agent_state(a) for a in self._agents}
        self.call_from_thread(self._render, sessions, counts, states)

    def _visible(self) -> list[dict]:
        query = self.query_one(FilterInput).value.strip().lower()
        if not query:
            return self._agents
        return [
            a
            for a in self._agents
            if query in a["name"].lower()
            or query in a["path"].lower()
            or query in a.get("category", "").lower()
        ]

    def _render(
        self,
        sessions: dict[str, list[int]],
        counts: dict[str, int],
        states: dict[str, tuple[str, int]] | None = None,
    ) -> None:
        # states is optional so a re-render triggered by typing in the filter box
        # reuses the last probe instead of SSHing on every keystroke.
        if states is not None:
            self._states = states
        states = self._states
        self._sessions, self._counts = sessions, counts
        table = self.query_one(DataTable)
        cursor = table.cursor_row
        table.clear()
        self._row_agents = []

        grouped: dict[str, list[dict]] = {}
        for agent in self._visible():
            grouped.setdefault(agent.get("category", "Uncategorized"), []).append(agent)

        live_total = 0
        for category, agents in grouped.items():
            table.add_row(Text(""), Text(category.upper(), style="bold magenta"), "", "", "")
            self._row_agents.append(None)
            for agent in agents:
                state, n = states.get(agent["name"], ("stopped", 0))
                live_total += n
                unread = counts.get(agent["name"], 0)
                account = config.resolve_account(agent)
                if state == "running":
                    marker = Text(f"● {n}", style="bold green")
                elif state == "unknown":
                    # Host unreachable. Saying "stopped" here would be a lie.
                    marker = Text(" ?", style="yellow")
                else:
                    marker = Text(" ·", style="dim")
                table.add_row(
                    marker,
                    Text(f"  {agent['name']}"),
                    Text(f"⟨{account}⟩", style="yellow") if account != "personal" else Text(""),
                    Text(f"✉ {unread}", style="bold cyan") if unread else Text(""),
                    Text(_short_path(agent["path"]), style="dim"),
                )
                self._row_agents.append(agent)

        if cursor < len(self._row_agents):
            table.move_cursor(row=cursor)
        unread_total = sum(counts.values())
        self.sub_title = f"{live_total} live · {unread_total} unread · {len(self._agents)} agents"

    def _selected(self) -> dict | None:
        row = self.query_one(DataTable).cursor_row
        if 0 <= row < len(self._row_agents):
            return self._row_agents[row]
        return None

    # -- actions ------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        agent = self._selected()
        if agent:
            self._open_flow(agent)

    @work
    async def _open_flow(self, agent: dict) -> None:
        from . import harness as _harness

        chosen = config.resolve_harness(agent).key
        while True:
            label = config.resolve_harness(agent, override=chosen).label
            mode = await self.push_screen_wait(
                ChoiceModal(
                    f"Open {agent['name']} [{label}]",
                    [
                        ("Continue last session", "continue"),
                        ("New session", "new"),
                        ("Resume a past session", "resume"),
                        ("Switch harness…", "switch_harness"),
                    ],
                )
            )
            if not mode:
                return
            if mode == "switch_harness":
                picked = await self.push_screen_wait(
                    ChoiceModal(
                        f"Harness for {agent['name']}",
                        [(h.label, h.key) for h in _harness.HARNESSES.values()],
                    )
                )
                if picked:
                    chosen = picked
                continue
            break

        h = _harness.get(chosen)
        if not h.is_available():
            self.notify(
                f"{h.label} is not installed (need `{h.executable}`).", severity="error"
            )
            return
        self.notify(f"Opening {agent['name']} ({mode}, {h.label})")
        self.run_worker(
            partial(
                spawn.open_agent,
                agent["name"],
                agent["path"],
                session_mode=mode,
                harness=chosen,
                config_dir=config.resolve_config_dir(agent, harness=chosen),
            ),
            thread=True,
        )

    @work
    async def _kill_flow(self, agent: dict) -> None:
        pids = status.running_pids(agent, self._sessions)
        if not pids:
            self.notify(f"{agent['name']} has no live session", severity="warning")
            return
        if await self.push_screen_wait(
            ConfirmModal(f"Kill {len(pids)} live session(s) for {agent['name']}?")
        ):
            sent = status.kill_pids(pids)
            self.notify(f"SIGTERM sent to {sent} session(s)")
            self.refresh_data()

    @work
    async def _manage_flow(self, agent: dict) -> None:
        action = await self.push_screen_wait(
            ChoiceModal(
                f"Manage {agent['name']}",
                [
                    ("Rename", "rename"),
                    ("Change category", "category"),
                    ("Change account", "account"),
                    ("Remove from registry", "remove"),
                ],
            )
        )
        if not action:
            return
        try:
            if action == "rename":
                new = await self.push_screen_wait(InputModal("New name", agent["name"]))
                if new and new != agent["name"]:
                    config.update_agent(agent["name"], new_name=new)
            elif action == "category":
                new = await self.push_screen_wait(
                    InputModal("Category (blank to clear)", agent.get("category", ""))
                )
                if new is not None:
                    config.update_agent(agent["name"], new_category=new)
            elif action == "account":
                # Option ids must be non-empty, so the "clear it" choice uses a sentinel.
                options = [("(use category default)", CLEAR_ACCOUNT)]
                options += [(name, name) for name in config.load_accounts()]
                new = await self.push_screen_wait(ChoiceModal("Account", options))
                if new is not None:
                    config.update_agent(
                        agent["name"], new_account="" if new == CLEAR_ACCOUNT else new
                    )
            elif action == "remove":
                if await self.push_screen_wait(
                    ConfirmModal(f"Remove {agent['name']} from the registry? (folder is kept)")
                ):
                    config.remove_agent(agent["name"])
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self._agents = config.load_agents()
        self.refresh_data()

    def action_inbox(self) -> None:
        agent = self._selected()
        if agent:
            self.push_screen(InboxModal(agent))

    def action_kill(self) -> None:
        agent = self._selected()
        if agent:
            self._kill_flow(agent)

    def action_manage(self) -> None:
        agent = self._selected()
        if agent:
            self._manage_flow(agent)

    def action_refresh_now(self) -> None:
        self._agents = config.load_agents()
        self.refresh_data()

    def action_filter(self) -> None:
        field = self.query_one(FilterInput)
        field.display = True
        field.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if isinstance(event.input, FilterInput):
            self._render(self._sessions, self._counts)  # reuses cached states

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if isinstance(event.input, FilterInput):
            self.query_one(DataTable).focus()


def run() -> None:
    ATeamTUI().run()
