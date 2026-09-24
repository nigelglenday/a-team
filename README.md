# a-team

![Version](https://img.shields.io/badge/version-0.6.0-orange) ![License](https://img.shields.io/badge/license-MIT-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Platform](https://img.shields.io/badge/platform-macOS-black) ![Ghostty](https://img.shields.io/badge/terminal-Ghostty-orange) ![Termpaper](https://img.shields.io/badge/set-termpaper-cyan)

> *I love it when a plan comes together.*

Keep your Claude Code sessions straight: name them, run as many as you like in parallel, put them on whichever machine suits, and reach them from your phone. One command brings them all back after a reboot, grouped into the windows you actually work in, each holding only the credentials it should have.

```
 █████╗       ████████╗███████╗ █████╗ ███╗   ███╗
██╔══██╗      ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║
███████║█████╗   ██║   █████╗  ███████║██╔████╔██║
██╔══██║╚════╝   ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║
██║  ██║         ██║   ███████╗██║  ██║██║ ╚═╝ ██║
╚═╝  ╚═╝         ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝
```

## What it is

An **agent** is a named folder. The registry remembers its name, where it lives, which machine it runs on, and which harness drives it. Everything else is built on that one mapping.

- **Parallel sessions.** Several chats in the same folder, each named and separately reachable.
- **More than one machine.** An agent's folder and session can live on another Mac over SSH, running in tmux so it outlives your window. Start something at your desk, pick it up in an airport.
- **Reachable from a phone.** Remote sessions start with Claude Code's Remote Control on, named after the agent, so they show up in the Claude app.
- **Claude Code or Codex**, chosen per agent.
- **Back after a reboot.** `a-team all` restores every persistent agent.

Requires macOS, Claude Code, and Python 3.11+. Ghostty is needed for the picker and TUI, which open windows for you; `atx` works in any terminal.

**New here?** The [FAQ](docs/faq.md) answers the common questions directly.

## Install

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/nigelglenday/a-team.git
```

For local dev:

```bash
git clone https://github.com/nigelglenday/a-team.git
cd a-team
pipx install -e .
```

## Use

```
a-team                          splash + arrow-key picker (type to filter)
a-team <name>                   open that agent directly
a-team tui                      live dashboard: running sessions + unread messages
a-team all                      restore every persistent agent

a-team new <name> [<path>]      register an agent (path falls back to clipboard)
a-team here [name]              register the current working directory
a-team scratch [label]          one-off chat in ~/.a-team/scratch/<timestamp>[_<label>]/
a-team rm <name>                unregister (folder is kept)
a-team ls                       plain list, pipe-friendly
a-team ls --json                full records, for scripts and agents
a-team open <name>              window on an agent: attach if up, else start
a-team archive <name>           out of the picker, kept in the registry
a-team grants --check-files     audit need-to-know wiring, both halves
a-team sync                     write each host's boot list from the registry
a-team layout                   rebuild the screen: every group, as tabs
a-team groups                   the group tree, and which window each lands in

a-team resolve <name> --json    where an agent lives (id, path, host, ssh, harness)
a-team config show              current settings
a-team migrate                  backfill stable ids on an older registry
```

`new` and `here` take `--host`, `--harness`, `--account` and `--category`.

In the TUI, `●` with a count means that many live sessions, `·` means stopped, and a yellow `?` means the agent's host could not be reached, which is not the same as stopped.

### Window groups

> Examples here use invented clients (Acme, Northwind). Everything
> installation-specific — the registry, the per-account grants, the org's own
> config — lives outside this repo by design, which is what keeps it generic.


An agent's `group` says which WINDOW it belongs in, which is a different axis
from `category` (who the work is for). Groups are slash-nested:

```
deal                     the client Associates and Strategy
backoffice               ops, sidekick, bookkeeper, concierge
backoffice/sidekick      nested, and still in the backoffice window
```

By default a group's top-level segment is its window, so everything under
`backoffice` shares one. To give a nested group its own window, declare a
split, and nothing gets re-tagged:

```
a-team config split-windows backoffice/sidekick
```

The tree is stable; the layout is not. Keeping them separate means fanning
sidekicks out into their own window is one command rather than an edit to
every sidekick.

`a-team layout` opens the lot, one window per group, tabs within.

### Agents are the main callers

Most of this is driven by other agents, not typed by a person, so the
machine-readable surfaces are the primary ones: `resolve --json` and
`ls --json` emit the full record (every field, plus the derived `ssh` alias)
so a caller never has to parse `agents.toml` itself. Commands are
non-interactive, exit non-zero on failure, and say what they did.

`a-team grants` audits need-to-know. It has two halves, and reporting one as
success is worse than reporting neither:

```
a-team grants                 # what the registry says
a-team grants --check-files   # what is actually on each host
a-team grants --fix           # backfill both halves from each agent's account
```

`full` means fenced to its own tenant and fenced off other customers' paths.
`HALF` means one of the two, which looks correct and is not. `NO TENANT` means
the fence exists but grants nothing: no Atlas account for that client yet.

### Without the picker

[`examples/atx`](examples/atx) does the same job from the registry alone, in any terminal:

```
atx                             list registered agents
atx <agent>                     attach to its session, starting it if needed
atx <agent> -n                  start an ADDITIONAL parallel session
atx <agent> --label Acme        a session named for a client or topic ("Name: Acme")
atx <agent> -L                  list that agent's running sessions
atx <agent> -s 3                attach to parallel session 3
atx <agent> -d                  start detached, do not attach
atx <agent> -w                  open it in its own window
atx -l <agent>                  show where it lives, start nothing
```

Parallel sessions are the normal way to run several builds or investigations at once: the first is `<id>`, the next `<id>-2`, each with its own name so they stay tellable apart on a phone.

`a-team new EA` with no path uses your macOS clipboard. In Finder, Shift+Right-click a folder → Copy as Pathname, then run the command.

The picker also surfaces `+ Create new agent` and `- Manage` so you rarely touch a config file.

When you open an agent, a-team asks how to start it:

- **Continue last session** (`claude --continue`) — resume the most recent conversation (default)
- **New session** (`claude`) — start fresh, with an optional topic label for parallel chats
- **Resume a past session…** (`claude --resume`) — opens Claude Code's own session picker in the new window, so you can pick a specific earlier conversation

Agents that run on a non-default Claude account are badged in the picker (e.g. `⟨work⟩`). `a-team new` / `a-team here` take `--account <name>` to set one explicitly; otherwise the account follows the category rule (see Config).

## Config

`~/.config/a-team/agents.toml`. Hand-edit for bulk import.

```toml
[[agent]]
name = "Tasks"
path = "/Users/you/Documents/tasks"
kind = "persistent"
category = "Personal"

[[agent]]
name = "Webapp"
path = "/Users/you/code/webapp"
category = "Work"
boot = true

[[agent]]
name = "scratch"
path = "/Users/you/Documents/scratch"
```

`boot = true` agents are restored by `a-team all`; it is opt in, so everything
else stays dormant until you open it. `status = "archived"` keeps an agent in
the registry but out of the picker, the TUI and `a-team ls` (`ls --all` shows it).

`category` groups agents in the picker. Order in the file = order in the picker.

### Remote hosts

An agent's folder and session can live on **another machine**, reached over SSH:
an always-on Mac as the server, your laptop as the cockpit. Hosts are configured,
never hardcoded:

```toml
[hosts]
server = "myserver"        # key -> ssh target (a ~/.ssh/config alias
build  = "user@10.0.0.5"   #        or user@host)

[[agent]]
name = "Build Agent"
path = "~/agents/build"    # path on THAT machine; ~ expands there
host = "server"
```

```bash
a-team new "Build Agent" --host server    # creates the folder on that machine
a-team config default-host server         # new agents default there
```

With a default host set, `a-team new "Build Agent"` needs no flags at all.

Remote agents run inside `tmux new-session -A` on their host, so they survive the
window closing, and attach over `mosh` (falling back to `ssh -t`). They also start
with Claude Code's Remote Control on, named after the agent, which makes them
reachable from the phone app and addressable by other sessions.

`examples/atx` is a cold-start helper that skips the picker entirely:
`atx build-agent` resolves the agent and opens it on whichever host it belongs to.

**Read [docs/remote-agents.md](docs/remote-agents.md) before setting this up.** It
covers the failure modes, chiefly that SSH logins on macOS cannot read the keychain,
which makes Claude Code fall back to API-key mode and silently disables Remote
Control until you start the tmux server from a GUI session.

### Accounts

Each agent can run under a different Claude login, selected by `CLAUDE_CONFIG_DIR` (each config dir holds its own account login). Define account profiles and an optional category→account rule:

```toml
[accounts]
personal = ""              # "" = the default ~/.claude
work = "~/.claude-work"

[account_by_category]
Work = "work"
```

An agent's account resolves as: an explicit `account = "work"` on the agent → the category rule → `personal`. So with the rule above, a `category = "Work"` agent runs on the `work` profile automatically; set `account` on an individual agent to override (e.g. force one back to `personal`). To set a profile up, run `CLAUDE_CONFIG_DIR=~/.claude-work claude` once and `/login`. Only `personal` ships as a built-in default; define any other profiles and rules in the tables above.

## How it spawns windows

Ghostty has no `+new-window` CLI on macOS, so `a-team` opens a window in the running Ghostty instance via the File → New Window menu (AppleScript), then delivers the launch command by **clipboard paste** rather than keystroking it — System Events drops characters on long strings, which mangles the command. The pasted command re-emits the title via OSC-0 on a loop, exports `CLAUDE_CONFIG_DIR` for the agent's account, `cd`s into the folder, and runs claude (`--continue`, `--resume`, or fresh, per your choice).

## Docs

- **[FAQ](docs/faq.md)** — how do I start a second session, why does my remote agent show `?`, I closed the window did I kill it, and the rest.
- **[Running agents on a second machine](docs/remote-agents.md)** — host setup, Remote Control, and the failure modes worth knowing before you rely on it (chiefly: SSH logins on macOS cannot read the keychain, which silently disables Remote Control).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Part of termpaper.dev

`a-team` is part of [termpaper.dev](https://termpaper.dev), a set of utilities for managing Claude Code state from the terminal:

- **[a-team](https://github.com/nigelglenday/a-team)** — parallel sessions (this repo)
- **[whispertty](https://github.com/nigelglenday/whispertty)** — record + transcribe + diarize audio
- **[skillbox](https://github.com/nigelglenday/skillbox)** — inventory and manage skills, slash commands, subagents
- **[eagent](https://github.com/nigelglenday/eagent)** — multi-session executive assistant pattern, file-based messaging

See [termpaper.dev](https://termpaper.dev) for the set.

## License

MIT
