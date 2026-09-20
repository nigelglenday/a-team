# FAQ

Short answers to the questions people actually ask. For the design and the
failure modes, see [remote-agents.md](remote-agents.md).

## Getting going

### What is an "agent" here?

A registered folder. The registry (`~/.config/a-team/agents.toml`) remembers its
name, its folder, which machine it lives on, and which harness runs it. Everything
else is built on that one mapping.

### How do I register one?

```bash
a-team here                     # register the folder you are standing in
a-team new "Build Agent"        # scaffold a new folder and register it
a-team ls                       # list what is registered
```

### How do I open one?

```bash
a-team                          # the picker: choose from a list, opens a new window
atx build-agent                 # no picker: open it directly
```

Both do the same thing. Use the picker when you want to browse, `atx` when you know
which agent you want.

### Where does a new agent's folder get created?

`<default_parent>/<slug>`, so "Build Agent" becomes `~/agents/build-agent` if you
have `a-team config default-parent ~/agents`. Pass an explicit path to override.
With a default host set, the folder is created **on that machine**.

## Running more than one

### How do I open a second session on the same project?

```bash
atx build-agent -n              # start another one
```

An agent can have as many parallel sessions as you like in the same folder, which
is the normal way to run several builds or investigations at once. The first is
`build-agent`, the next `build-agent-2`, and so on. They get distinct names
("Build Agent 2") so you can tell them apart, which matters most on a phone.

### How do I see which ones are running, and get back to one?

```bash
atx build-agent -L              # list this agent's sessions
atx build-agent -s 3            # attach to session 3
atx build-agent                 # attach to the first
```

### How do I see everything that is running, everywhere?

```bash
a-team tui                      # live dashboard: running count + unread messages
```

A green `●` with a number means that many live sessions. A dim `·` means stopped.
A yellow `?` means the agent is on a host that could not be reached just now, which
is **not** the same as stopped.

From inside a Claude session, `ListAgents` shows every live session, including ones
on other machines (see below).

## Sessions and windows

### I closed the window. Did I kill my agent?

**A local agent: yes.** **A remote agent: no.** Remote agents run inside tmux on
their host, so the window is only a viewport. Closing it, losing wifi, or putting
your laptop to sleep leaves the session running. Reattach with `atx <agent>`.

### How do I detach without killing it?

`Ctrl-B` then `D`. Closing the window does the same. Do **not** type `exit` or
press `Ctrl-C`: those end the session.

### How do I stop an agent?

In the TUI, select it and stop it. That works for local agents. Stopping a *remote*
agent is not offered, on purpose: the pids belong to another machine, and acting on
them locally would signal an unrelated process that happens to share the number. To
stop a remote session, `ssh <host> 'tmux kill-session -t <id>'`.

### `atx` says "starting" but I expected it to attach

It says "attaching to" when the session already exists and "starting" when it does
not. It is idempotent either way: running it twice never gives you a duplicate. Use
`-n` when you actually want an additional session.

## Remote machines

### Can an agent live on another computer?

Yes. Add a `[hosts]` table to `agents.toml` and give the agent a `host`:

```toml
[hosts]
server = "myserver"             # an ~/.ssh/config alias, or user@host

[[agent]]
name = "Build Agent"
path = "~/agents/build"         # path on THAT machine
host = "server"
```

```bash
a-team config default-host server    # make it the default for new agents
```

The ssh target must already work non-interactively (`ssh <target> true`).

### How do I reach a remote agent from my phone?

Remote agents start with Claude Code's Remote Control on, named after the agent.
Open the Claude app, go to **Code > Session list**, and pick it. A green dot means
online. You can be attached in a terminal and on your phone at the same time: both
are views of the same process.

### My remote agent shows `?` instead of running or stopped

The host could not be reached. Check `ssh <target> true`. The `?` is deliberate:
reporting "stopped" because SSH timed out would be a lie.

### `/remote-control` says it needs Enterprise, and the session says "Not logged in"

The machine cannot read its keychain, so Claude Code fell back to API-key mode.
This happens when the session was started over SSH, because macOS puts SSH logins
in the `Background` security session and keychain items are only reachable from the
GUI (`Aqua`) one.

Fix: start the tmux **server** once from a GUI terminal on that machine. Every
session created over SSH afterwards inherits the access. Full instructions,
including the LaunchAgent that makes it survive a reboot, are in
[remote-agents.md](remote-agents.md#gotcha-1-the-keychain-or-why-rc-fails-over-ssh).

### My remote agent works but has none of its tools

MCP servers are configured per machine and do not travel with the agent. Neither do
cloud-storage clients or credentials. Install what that agent needs on the machine
it now runs on. See
[remote-agents.md](remote-agents.md#gotcha-3-the-remote-machine-is-a-different-computer).

### It asked me to trust the folder

Once per folder per machine. An unattended launch stalls there, and Remote Control
needs the folder trusted, so open each new folder once interactively.

### Which machine should host an agent?

Decide by **who drives it**, not by subject:

- **Server**: unattended and long-running. Builds you kick off and come back to,
  monitors, scheduled jobs.
- **Laptop**: work you do interactively, especially offline. A session on the server
  is unreachable from a plane; local files are not.

## Odds and ends

### Do I need the TUI?

No. The registry is the load-bearing part; `atx` covers starting and attaching, and
the phone app covers everything after that. The TUI is the nicest way to see
everything at once, but nothing depends on it.

### Can one agent message another?

Yes, from inside a Claude session: `ListAgents` to see who is live, `SendMessage` to
reach one. It wakes an idle session, and it works across machines, provided the
target has Remote Control on. Note there is no delivery receipt over that route, so
silence means nothing either way.

### Can I use Codex instead of Claude Code?

Per agent, via the `harness` field or `--harness codex`. Each harness exports only
its own config variable, so a Claude config directory can never leak into Codex.
Codex has no Remote Control equivalent, so remote Codex sessions are not reachable
from a phone.

### Where is the config?

`~/.config/a-team/agents.toml`. Hand-edit it for bulk changes; it is a plain TOML
file. `a-team migrate` backfills stable ids on an older registry.
