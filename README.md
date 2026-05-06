# a-team

![License](https://img.shields.io/badge/license-MIT-yellow) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Platform](https://img.shields.io/badge/platform-macOS-black) ![Ghostty](https://img.shields.io/badge/terminal-Ghostty-orange)

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
a-team rm <name>                unregister (folder is kept)
a-team ls                       plain list, pipe-friendly
```

`a-team new EA` with no path uses your macOS clipboard. In Finder, Shift+Right-click a folder → Copy as Pathname, then run the command.

The picker also surfaces `+ Create new agent` and `- Manage` so you rarely touch a config file.

## Config

`~/.config/a-team/agents.toml`. Hand-edit for bulk import.

```toml
[[agent]]
name = "EA"
path = "/Users/you/Documents/Tasks"
kind = "persistent"
category = "Personal"

[[agent]]
name = "Sidekick"
path = "/Users/you/code/atlas"
kind = "persistent"
category = "Atlas"

[[agent]]
name = "fii-research"
path = "/Users/you/research/fii"
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

## License

MIT
