# Changelog

All notable changes to `a-team` are documented here.

This file roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-09-22

The registry becomes the thing agents ask, rather than a file they parse.

### Added
- **`a-team open <name>`**: attaches a window to the agent's running session, or starts it if nothing is up. Attaching is the default because an agent on the server is already alive with its context, and a second one beside it splits the work in two with neither half aware of the other. Replaces the separate `agent-window` script.
- **`a-team archive` / `unarchive`**: take an agent out of the picker while keeping it, and its id, in the registry. Archiving clears `boot`, so an archived agent cannot come back on the next reboot.
- **`a-team grants`**: audits need-to-know wiring. `--check-files` asks each host whether the config files actually exist, `--fix` backfills them from each agent's account. Distinguishes `full`, `HALF` (one of the two halves, which looks correct and is not), `NO FILES` and `NO TENANT`.
- **`a-team new --sibling <parent>`**: inherits the parent's host, category, account and harness, derives both halves of the grant from the account, and records `parent` so lineage lives in the registry rather than in whoever created it.
- **`ls --json`, `ls --boot`, `ls --host`**, and `resolve --json` now emits the full record instead of six hand-picked fields. Agents are the main callers here; a caller that has to shell out twice is a caller that will go parse `agents.toml` instead.

### Fixed
- **`sync` wrote only the MCP half of the guard.** Every advisor session restored after a reboot had tenant isolation, no path deny and no Bash guard. The boot list now carries both, and `session-boot` refuses to start a session whose named guard config is absent rather than starting it unguarded.
- **Archived agents still appeared in the picker and the TUI**: four call sites loaded the whole registry instead of the active set.

### Removed
- **The `kind` field (`persistent` / `ephemeral`).** `boot` decides what `a-team all` restores, and it is opt in; `kind` was a second field for the same job that nothing consulted any more, while the picker still sorted on it. `--ephemeral` is gone from `new` and `here`.

## [0.5.6] - 2026-09-20

- **`atx <agent> -w` opens the session in its own window.** Without it, `atx` takes over the terminal you ran it from, and opening several client sessions side by side meant driving a-team's `spawn.open_agent` by hand. It reuses that same code rather than reimplementing it: a window in the RUNNING Ghostty instance over AppleScript, since `open -na Ghostty --args -e` starts a second instance and fragments the windows, and the tmux session name is passed so `new-session -A` attaches to what is running instead of creating a duplicate.
- Falls back to attaching in the current terminal, with a reason, when a-team's source is not where it expects.

## [0.5.5] - 2026-09-20

- **`atx <agent> --label <name>`: named parallel sessions.** Numbered sessions ("Agent 2", "Agent 3") stop being useful once several are open for different clients or topics; on a phone they are indistinguishable. A label gives the session its own tmux name (`<id>-<slug>`) and Remote Control title (`<Name>: <Label>`). Re-running the same label **attaches** to that session rather than creating another, so it doubles as the way back into a given piece of work.
- Labels work for local agents too, where there is no tmux to attach to: the label titles the session and enables Remote Control under that name, so the same session can be picked up from a phone later.
- `-L` now prints the exact command to re-enter each session, including labelled ones.



- **Fix: `atx` reported a reachable host as unreachable once an agent had no sessions.** The session lookup piped `ssh` into `grep`, and under `set -o pipefail` a grep that matches nothing makes the whole pipeline non-zero, which the error handler read as an SSH failure. So stopping an agent's last session made the next `atx <agent>` claim "could not reach <host>" instead of starting it. The ssh call and the filtering are now separate steps.



- **[docs/faq.md](docs/faq.md).** Task-shaped answers to the questions people actually ask: opening a second session on the same project, seeing what is running, whether closing the window kills an agent, reaching one from a phone, and what `?` means in the dashboard. The existing docs were organised by concept and failure mode, which is the wrong shape for "how do I".
- **README overhaul.** It still described a Ghostty session picker. It now leads with what the tool grew into: parallel sessions, agents on a second machine, phone access, and a choice of harness. The command list had drifted badly — `tui`, `resolve`, `config` and `migrate` were missing entirely, and `atx` appeared without any of its flags, so the parallel-session support shipped in 0.5.2 was undiscoverable outside the script's own header. Adds a docs index.

## [0.5.2] - 2026-09-20

- **`examples/atx`: parallel sessions per agent.** An agent often has several chats open in the same folder (separate builds, separate investigations), which `status.py` already counted but the launcher could not create: the tmux session was named after the agent id, so there was only ever one. `atx <agent> -n` starts an additional session using the next free suffix (`<id>-2`, `<id>-3`, ...), named "`<Name> 2`", "`<Name> 3`" in Remote Control so they stay tellable apart on a phone. `-L` lists an agent's running sessions, `-s N` attaches to one of them.
- **Fix: `atx` claimed to be starting a session it was actually attaching to.** It now checks which sessions exist on the host first and says "attaching to" or "starting" accordingly.

## [0.5.1] - 2026-09-20

- **Fix: remote agents always showed as stopped.** 0.5.0 let agents live on another machine but left status detection local-only (`pgrep` + `lsof`), so every remote agent read as not running even while it was. `status.agent_state()` now probes the agent's host over SSH, cached for a few seconds so the TUI does not re-SSH on every repaint.
- **An unreachable host reports `unknown` (`?`), not `stopped`.** Saying "stopped" because SSH timed out is a lie, and "is it running?" is the question the tool exists to answer.
- **`running_pids()` returns `[]` for remote agents, deliberately.** Its result feeds `kill_pids()`, which calls `os.kill()` on the local machine: returning a remote pid would have signalled whatever unrelated local process happened to hold that number. Stopping a remote agent has to go over SSH and is not offered here.
- Remote registry paths keep a literal `~` and are expanded against the *remote* home when matching probed working directories.

## [0.5.0] - 2026-09-20

- **Agents can live on another machine.** A `[hosts]` table maps host keys to SSH targets, and an agent's `host` field says where its folder and session live. Remote agents run in `tmux new-session -A` on that host so they outlive the window, and attach over `mosh` with an `ssh -t` fallback. Hosts are configured, never hardcoded. `a-team new --host <key>` creates the folder on that machine; `a-team resolve --json` exposes `host` and `ssh` so shell helpers can route by host.
- **`a-team config default-host <key>`.** Sets where `a-team new` puts agents when `--host` is omitted, so a server-first setup needs no flags. A remote agent given no path now defaults to `~/agents/<slug>` on that machine, mirroring the local convention instead of erroring.
- **Remote sessions launch with Remote Control on, named after the agent.** Without it, a session on another machine is hard to identify (the runtime picks `hostname-ancient-wirth`) and unaddressable by other sessions, which can only reach it once Remote Control is active. The launch verbs are compound (`{ claude --continue || claude; }`), so the executable is now templated and extra args are spliced into every position: appending to the string would have put the flag on the first arm only, and a failed `--continue` would have fallen back to an unnamed, unreachable session. Codex gets no flag; local agents are untouched.
- **Harness adapter.** Claude Code and Codex are selected per agent via a `harness` field, isolating executable, launch verbs and config env var so `CLAUDE_CONFIG_DIR` can never leak into Codex.
- **Fix:** `a-team new` passed the raw `--host` value to the registry instead of the normalized key, so an alias like `this` was stored verbatim.
- **[docs/remote-agents.md](docs/remote-agents.md)** covers setup and the failure modes: macOS runs SSH logins in the `Background` security session, which cannot read the keychain, so Claude Code falls back to API-key mode and Remote Control goes silently unavailable. tmux panes inherit the tmux *server's* session, so starting it once from a GUI terminal fixes every SSH-created session; includes the `Aqua` LaunchAgent. Also per-folder workspace trust, and MCP servers / sync clients / credentials not following an agent across machines.
- **`examples/atx`**, a cold-start helper that skips the TUI: resolve an agent from the registry, start it on its own host under its own name, attach over mosh.

## [0.4.2] - 2026-07-08

- **Fix: new agents could be scaffolded in the wrong place.** A bare/relative folder entered in the picker resolved against the current working directory — so running `a-team` from an arbitrary session folder (e.g. a Google Drive directory) silently created the agent there. Relative paths now anchor to `default_parent`.
- **New agent folders are derived from the name, slugified.** The picker prefills `<default_parent>/<slug>` ("Art Handler" → `~/agents/art-handler`), and `a-team new <NAME>` scaffolds the same. Previously the raw display name was used, producing folders with spaces. Adds a shared `config.slugify()`.
- **The name-derived default now takes precedence over the clipboard**, so a stale Finder "Copy as Pathname" can no longer silently pick the folder for a new agent. The clipboard remains the fallback when no `default_parent` is set.

## [0.4.1] - 2026-06-24

- **Fix: new window opens but nothing runs.** Spawning waited a fixed 0.6s after opening the Ghostty window before pasting the launch command; when window-open latency exceeds that (newer macOS/Ghostty, system load), the paste lands in a window that isn't ready and nothing executes. Now polls for the new window to actually appear (up to ~4s) before pasting, with a short settle — robust to variable open latency instead of a magic delay.

## [0.4.0] - 2026-06-16

- **Per-agent Claude account.** An agent can run under a different Claude login, selected by `CLAUDE_CONFIG_DIR` (each config dir holds its own account). Account resolves as: explicit `account` on the agent → a category→account rule → `personal`. Only `personal` ships as a default; define other profiles and rules via `[accounts]` and `[account_by_category]` in `agents.toml`. The picker badges non-personal agents (e.g. `⟨work⟩`), `a-team new` / `a-team here` accept `--account`, and the interactive new-agent flow asks for it (defaulting to the category's account).
- **New / Continue / Resume session selection.** Opening an agent now offers, in Claude's standard language: **Continue last session** (`claude --continue`, default), **New session** (`claude`), or **Resume a past session…** which launches Claude Code's own session picker (`claude --resume`) in the new window. Lets you pick a specific earlier conversation from a-team instead of opening a window and typing `/resume`.
- **Reliable window spawn.** Replaced keystroking the whole launch command (System Events silently dropped characters — notably spaces — on long strings, leaving the new window at a mangled, unrun prompt) with opening the window via the File → New Window menu and delivering the command by clipboard paste (atomic, no length limit, no AppleScript escaping). The clipboard is saved and restored around the paste.

## [0.3.1] - 2026-06-10

- **Fix: clear restored Ghostty prompt buffer before keystroking the launcher command.** Ghostty sometimes restores the prior session's typed-but-unsubmitted characters at the new window's prompt (visible as e.g. `to %` on the prompt line after `Last login: ...`). When the launcher then typed the title-spinner bash command, the buffered text got prepended and zsh parsed `to { ( while ...` as command name `to` followed by an opening brace group, failing at `do` inside the while loop and leaving the new session unlaunched. Now sends Ctrl-U (delete-to-beginning-of-line in both zsh and bash) before typing the command.

## [0.3.0] - 2026-06-09

- **Multiple parallel chats per agent** — after picking an agent, choose "Resume latest chat" (Enter) or "Start a new chat" with an optional topic label. Lets you run different conversations on the same agent (e.g. `myproject: pricing` + `myproject: onboarding`) without them fighting over the same session UUID. New chats get a fresh `claude` session; the topic label is appended to the Ghostty window title so parallel windows are visually distinct.
- **Picker no longer crashes when `getcwd()` returns EPERM** — macOS can deny `os.getcwd()` mid-session when a parent directory is renamed, permissions change, or iCloud evicts the folder. The picker now falls back to `~` instead of stack-tracing. `a-team here` catches the same error and prints a friendly message ("Try `cd ~` first") instead of crashing.

## [0.2.0] - 2026-05-15

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

## [0.1.0] - 2026-04-29

Initial release. Picker, splash, categories, `new`/`rm`/`ls`/`all`, persistent vs. ephemeral kinds, AppleScript-driven Ghostty spawning.
