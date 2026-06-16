# a-team

![Version](https://img.shields.io/badge/version-0.3.0-orange) ![License](https://img.shields.io/badge/license-MIT-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Platform](https://img.shields.io/badge/platform-macOS-black) ![Ghostty](https://img.shields.io/badge/terminal-Ghostty-orange) ![Termpaper](https://img.shields.io/badge/set-termpaper-cyan)

> *I love it when a plan comes together.*

Manage parallel Claude Code sessions in Ghostty. One command brings them all back after a reboot.

```
 █████╗       ████████╗███████╗ █████╗ ███╗   ███╗
██╔══██╗      ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║
███████║█████╗   ██║   █████╗  ███████║██╔████╔██║
██╔══██║╚════╝   ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║
██║  ██║         ██║   ███████╗██║  ██║██║ ╚═╝ ██║
╚═╝  ╚═╝         ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝
```

## What it is

An "agent" is a Claude Code session in a folder with a name. `a-team` keeps a registry, lets you pick one to open, and restores all of them at once.

Requires macOS, Ghostty, Claude Code, and Python 3.11+.

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
a-team all                      restore every persistent agent
a-team new <name> [<path>]      register an agent (path falls back to clipboard)
a-team here [name]              register the current working directory
a-team scratch [label]          one-off chat in ~/.a-team/scratch/<timestamp>[_<label>]/
a-team rm <name>                unregister (folder is kept)
a-team ls                       plain list, pipe-friendly
```

`a-team new EA` with no path uses your macOS clipboard. In Finder, Shift+Right-click a folder → Copy as Pathname, then run the command.

The picker also surfaces `+ Create new agent` and `- Manage` so you rarely touch a config file.

When you open an agent, a-team asks how to start it:

- **Continue last session** (`claude --continue`) — resume the most recent conversation (default)
- **New session** (`claude`) — start fresh, with an optional topic label for parallel chats
- **Resume a past session…** (`claude --resume`) — opens Claude Code's own session picker in the new window, so you can pick a specific earlier conversation

Agents that run on a non-default Claude account are badged in the picker (e.g. `⟨mw⟩`). `a-team new` / `a-team here` take `--account <name>` to set one explicitly; otherwise the account follows the category rule (see Config).

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
kind = "persistent"
category = "Work"

[[agent]]
name = "scratch"
path = "/Users/you/Documents/scratch"
kind = "ephemeral"
```

`kind = "persistent"` agents are restored by `a-team all`. `kind = "ephemeral"` are not.

`category` groups agents in the picker. Order in the file = order in the picker.

### Accounts

Each agent can run under a different Claude login, selected by `CLAUDE_CONFIG_DIR` (each config dir holds its own account login). Define account profiles and an optional category→account rule:

```toml
[accounts]
personal = ""            # "" = the default ~/.claude
mw = "~/.claude-mw"

[account_by_category]
Masterworks = "mw"
```

An agent's account resolves as: an explicit `account = "mw"` on the agent → the category rule → `personal`. So a `category = "Masterworks"` agent runs on the `mw` profile automatically; set `account` on an individual agent to override (e.g. force one back to `personal`). To set a profile up, run `CLAUDE_CONFIG_DIR=~/.claude-mw claude` once and `/login`. (`personal` and `Masterworks → mw` ship as built-in defaults; the tables above only override them.)

## How it spawns windows

Ghostty has no `+new-window` CLI on macOS, so `a-team` opens a window in the running Ghostty instance via the File → New Window menu (AppleScript), then delivers the launch command by **clipboard paste** rather than keystroking it — System Events drops characters on long strings, which mangles the command. The pasted command re-emits the title via OSC-0 on a loop, exports `CLAUDE_CONFIG_DIR` for the agent's account, `cd`s into the folder, and runs claude (`--continue`, `--resume`, or fresh, per your choice).

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
