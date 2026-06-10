# Changelog

All notable changes to `a-team` are documented here.

This file roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-06-10

- **Fix: clear restored Ghostty prompt buffer before keystroking the launcher command.** Ghostty sometimes restores the prior session's typed-but-unsubmitted characters at the new window's prompt (visible as e.g. `to %` on the prompt line after `Last login: ...`). When the launcher then typed the title-spinner bash command, the buffered text got prepended and zsh parsed `to { ( while ...` as command name `to` followed by an opening brace group, failing at `do` inside the while loop and leaving the new session unlaunched. Now sends Ctrl-U (delete-to-beginning-of-line in both zsh and bash) before typing the command.

## [0.3.0] - 2026-06-09

- **Multiple parallel chats per agent** — after picking an agent, choose "Resume latest chat" (Enter) or "Start a new chat" with an optional topic label. Lets you run different conversations on the same agent (e.g. Navigator: pricing + Navigator: onboarding) without them fighting over the same session UUID. New chats get a fresh `claude` session; the topic label is appended to the Ghostty window title so parallel windows are visually distinct.
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
