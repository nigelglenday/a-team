# a-team

![Version](https://img.shields.io/badge/version-0.2.0-orange) ![License](https://img.shields.io/badge/license-MIT-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Platform](https://img.shields.io/badge/platform-macOS-black) ![Ghostty](https://img.shields.io/badge/terminal-Ghostty-orange) ![Termpaper](https://img.shields.io/badge/suite-termpaper-cyan)

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

## How it spawns windows

Ghostty has no `+new-window` CLI on macOS, so `a-team` drives the GUI via AppleScript. Each spawn activates Ghostty, clicks New Window, then keystrokes:

```
printf '\e]0;<name>\a' && cd <path> && claude --continue
```

Title via OSC-0, then `cd`, then resume.

## Changelog

### 0.2.0 (2026-05-15)

- **Scratch sessions** — `a-team scratch [label]` and `+ New scratch session` in the picker create one-off Claude Code sessions under `~/.a-team/scratch/<timestamp>_<label>/`. They show up in a pinned-to-bottom "Scratch" section in the picker, capped at the 10 most recent with a "Show all scratch (N)" expansion. Skipped by `a-team all`.
- **`a-team here [name]`** — register the current working directory as an agent. Name defaults to the folder's basename.
- **`a-team config default-parent <path>`** — set where `a-team new <name>` (with no path) scaffolds new folders.
- **Picker overhaul** — clears the screen between iterations; confirmation banners replace stacking output; `+ Add agent (existing folder or new)` renamed from `+ Create new agent` to make it obvious the same flow handles existing folders.
- **`? Help` entry** in the picker and `a-team help` command (styled panel).
- **`Cancel` → `Quit`** in the home menu.
- **`$A_TEAM_CONFIG`** env var to point at a demo or alternate registry.
- **Manage flow** — rename / change path / change category / remove, all with confirmations and clean returns to the home menu.
- **Window-title resilience** — emit OSC-0, OSC-1, and OSC-2 escapes and re-emit on a 1-second loop so Ghostty tab/window titles stick.
- **Fall back to fresh `claude`** when `claude --continue` finds no conversation in a folder.
- **Dropped `[ephemeral]` badge** from picker rows; section context (Scratch) is enough.
- Various smaller fixes: cancel-from-manage no longer crashes; the `[ephemeral]` badge is gone; picker stays open across selections.

### 0.1.0 (2026-04-29)

Initial release. Picker, splash, categories, `new`/`rm`/`ls`/`all`, persistent vs. ephemeral kinds, AppleScript-driven Ghostty spawning.

## Part of termpaper

`a-team` is one of three TUI tools for managing Claude Code state from the terminal:

- **[a-team](https://github.com/nigelglenday/a-team)** — parallel sessions (this repo)
- **[whispertty](https://github.com/nigelglenday/whispertty)** — record + transcribe + diarize audio
- **[skillbox](https://github.com/nigelglenday/skillbox)** — inventory and manage skills, slash commands, subagents

See [termpaper.dev](https://termpaper.dev) for the suite.

## License

MIT
