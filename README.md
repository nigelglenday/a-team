# a-team

Parallel Claude Code session manager for Ghostty.

> *I love it when a plan comes together.*

`a-team` manages your parallel [Claude Code](https://claude.com/claude-code) sessions — each running in a [Ghostty](https://ghostty.org) window, in a different folder, with its own `CLAUDE.md`. After a Mac reboot, one command brings them all back.

## What it does

- **Pick an agent** to jump to — fuzzy-search arrow-key picker over your registered Claude Code workspaces
- **Restore everything** — `a-team all` opens a Ghostty window for every persistent agent, with `claude --continue` already running
- **Manage agents** — create, rename, remove, all from the picker (no TOML editing required)
- **Direct open** — `a-team EA` skips the picker and opens that one
- **A splash because plans deserve splashes**

An "agent" is just `(name, folder)`. The tool spawns a new Ghostty window, sets the title, `cd`s into the folder, and runs `claude --continue`.

## Install

Requires macOS, Ghostty, Claude Code, and Python 3.11+.

```bash
brew install pipx
pipx ensurepath
pipx install git+https://github.com/nigelglenday/a-team.git
```

Or for local development:

```bash
git clone https://github.com/nigelglenday/a-team.git
cd a-team
pipx install -e .
```

## Usage

```
a-team                          splash + arrow-key picker over all agents
a-team <name>                   open that agent directly (skip the picker)
a-team all                      restore every persistent agent (post-reboot)
a-team new <name> <path>        register an agent
a-team new <name> <path> --ephemeral   register a one-off agent (excluded from `all`)
a-team rm <name>                unregister (does NOT delete the folder)
a-team ls                       plain list, pipe-friendly
a-team --help
```

The picker also surfaces `+ Create new agent` and `- Manage` entries — most management can happen there without ever opening a config file.

## Config

Lives at `~/.config/a-team/agents.toml`. Hand-editable. Bulk import is faster than running `a-team new` ten times:

```toml
[[agent]]
name = "EA"
path = "/Users/you/Documents/Tasks"
kind = "persistent"

[[agent]]
name = "Sidekick"
path = "/Users/you/Documents/code/atlas"
kind = "persistent"

[[agent]]
name = "fii-research"
path = "/Users/you/Documents/Masterworks/mena"
kind = "ephemeral"
```

`kind = "persistent"` agents are restored by `a-team all`. `kind = "ephemeral"` ones are not.

## How it works

`a-team` uses macOS AppleScript to drive Ghostty (Ghostty's `+new-window` CLI is unsupported on macOS). Each spawn:

1. Activates Ghostty
2. Clicks the "New Window" menu item via System Events
3. Keystrokes `printf '\e]0;<name>\a' && cd <path> && claude --continue`
4. Presses Return

The `printf` sets the window title via the OSC-0 escape; the `cd` puts you in the right folder; `claude --continue` resumes the most recent session for that folder.

## Why "a-team"

You have a team of agents. Each has a name. They scatter to do their work. After the chaos, you want them all back. *I love it when a plan comes together.*

## License

MIT
