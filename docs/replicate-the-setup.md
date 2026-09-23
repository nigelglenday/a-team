# Replicating the setup: an always-on agent server, driven from a laptop

This document is written to be handed to a coding agent (Claude Code or similar)
along with the instruction "walk me through this". It says what the setup is
for, then gives the build as numbered phases. Every phase ends with a check.
**An agent following this should not move to the next phase until the check
passes**, because nearly every failure in this setup is silent: it reports
success and does nothing.

Two variants are covered throughout:

- **A spare Mac as the server.** What this was built on. macOS has two extra
  problems (the keychain and a stripped PATH for scheduled jobs), both solved
  below.
- **A cloud VM (for example EC2) as the server.** Linux. Simpler in a few places,
  and noted wherever it differs.

Terms used: the **server** is the always-on machine that runs the agents. The
**laptop** is the machine you carry and look through.

---

## The objective

**The server is the brain. The laptop is a cockpit you look at it through.**

Claude Code sessions run on the server, inside `tmux`, whether or not the laptop
is open, charged, or on a plane. Opening the laptop is not starting work; it is
looking in on work already under way. The same session can be reached from a
terminal on the laptop, from the Claude desktop app, or from the Claude phone
app, and all three are windows onto one process.

What that unlocks, concretely:

- **Work continues without you.** An agent can spend forty minutes on something
  while the laptop is shut.
- **Phone access to the real session.** Not a chatbot relaying messages to your
  setup: the actual conversation, with its context and tools, from your phone.
- **Parallel sessions per topic.** One session per client, project or workstream,
  each with its own context, each reachable by name.
- **Sessions that talk to each other.** One session can hand another a finding or
  a task and wake it up.
- **Scheduled work that runs.** A check at 04:00 happens at 04:00.
- **A real review loop.** You comment on a live web page the agent built, on the
  specific element, and the agent reads the element rather than your description
  of a screenshot.

What it costs: the server is a second computer to keep healthy, and a failure on
a machine you are not looking at is a failure nobody sees. Phase 11 exists for
that reason, and it is not optional.

### The one rule that prevents corruption

**Nothing is synced between the machines.** There is exactly one copy of each
thing, on one machine, and the other reaches it.

| Category | Lives | The other machine gets it by |
|---|---|---|
| Code | the git remote | `git clone` / `pull` |
| Agent state (session folders, inboxes, history) | **one host only** | reaching it remotely, never copying |
| Documents | a cloud drive | the drive's own app on the laptop; a one-way-ish mirror on the server |

Two live writers on the same agent state produces conflict copies and a broken
inbox. So does putting live agent files inside a consumer sync folder (iCloud,
Dropbox, Google Drive). On macOS, `~/Documents` and `~/Desktop` are iCloud-synced
by default, which is how agent state ends up there without anyone deciding to
put it there. **Keep agent state under a plain directory in `$HOME`.**

---

## Before you start

You need:

- A **Claude subscription account** (Pro or Max) logged in on both machines.
  Remote Control requires claude.ai account auth. **An API key will not do**:
  sessions start, but `/remote-control` reports it is unavailable.
- **Tailscale** (or another private network) on both machines. The server should
  accept no inbound connections from the public internet.
- On the server: `git`, `tmux`, Node (for `npx`-based MCP servers), Python 3,
  and headless Chrome if you want the screenshot tool.
- On the laptop: a terminal, and Chrome or another browser.

Sizing, for the VM variant: 8 GB of RAM is a floor, 16 GB is comfortable. The
reference server is a 16 GB laptop running six to seven sessions plus their MCP
servers. Each `npx`-launched MCP server is its own Node process, and they add up.

---

## Phase 1: the network and an SSH alias

1. Install Tailscale on both machines and join them to the same tailnet.
2. On the laptop, create an SSH key if there is none, and install it on the
   server's `~/.ssh/authorized_keys`.
3. Add an alias to the laptop's `~/.ssh/config`:

   ```
   Host server
     HostName <server's tailnet name or 100.x address>
     User <server username>
   ```

4. **Mac server:** enable Remote Login (System Settings > General > Sharing).
   **VM:** close every inbound port in the security group except what Tailscale
   needs, and SSH only over the tailnet.

**Check:** `ssh server 'echo ok'` prints `ok` with no password prompt.

The laptop does **not** need to accept connections. Nothing in this setup
requires the server to reach into the laptop, and that is deliberate (see
Phase 9).

---

## Phase 2: keep the server awake, and put Claude Code on it

1. **Mac server:** `sudo pmset -a disablesleep 1`, so it survives a closed lid.
   `caffeinate` does not survive a closed lid, so do not rely on it.
   **VM:** nothing to do.
2. Install Claude Code on the server and log in with the subscription account.
   On a headless box, the login prints a URL; open it on the laptop.
3. Install `tmux`.

**Check:** `ssh server 'claude --version'` prints a version, and a `claude`
session started in a server terminal shows your account, not an API key.

---

## Phase 3 (Mac only): the keychain problem

This is the one that costs a day if you do not know it.

On macOS, Claude Code keeps its credentials in the **keychain**, and the keychain
is only reachable from the **GUI security session** ("Aqua"). An SSH login runs
in a different, "Background", session. So a `claude` started over SSH cannot read
its own credentials. Sessions start and appear to work, but `/remote-control`
fails, and OAuth-based MCP servers report "needs authentication".

`tmux` makes this worse and then fixes it: every tmux pane is a child of the tmux
**server** process and inherits *its* security session. So if the tmux server was
first started over SSH, every session inside it is locked out of the keychain.
If it was started from the GUI, every session inside it can read the keychain,
**including sessions you later create over SSH.**

The fix is a login item that starts the tmux server from the GUI at boot, and
keeps one session in it alive so the server never exits.

`~/Library/LaunchAgents/local.tmux-bootstrap.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.tmux-bootstrap</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>-c</string>
    <string>/opt/homebrew/bin/tmux has-session -t main 2>/dev/null || /opt/homebrew/bin/tmux new-session -d -s main</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
```

Load it with `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/local.tmux-bootstrap.plist`,
or log out and in. The server needs to auto-login for this to happen after a
reboot.

Two details that matter:

- The `has-session ||` guard. `tmux new-session -A` tries to *attach*, and under
  launchd there is no terminal, so it fails with "open terminal failed".
- **Never kill the session named `main`.** It is what every other session
  inherits keychain access from. Write that down somewhere the agents will read.

**Check:** `ssh server 'launchctl managername'` prints `Background`. Then
`ssh server 'tmux new-window -d -t main "launchctl managername > /tmp/m.txt"'; sleep 2; ssh server cat /tmp/m.txt`
prints `Aqua`. Sessions created inside that tmux server can read the keychain.

**VM:** skip this phase. On Linux, Claude Code stores credentials in a file
(`~/.claude/.credentials.json`), so any process running as your user can read
them. Instead, make tmux survive logout and reboot: run it under a systemd user
service and enable lingering (`loginctl enable-linger $USER`).

---

## Phase 4: Remote Control, so the phone works

1. In the server's `~/.claude/settings.json`, set `"remoteControlAtStartup": true`.
   Every session started on the server then registers itself with Remote Control
   under its name.
2. Do **not** set this on the laptop unless you want laptop sessions on your
   phone too.

**Check:** start a session on the server (inside tmux), then open the Claude
phone app, go to Code, and find it in the session list. Send it a message from
the phone and watch it arrive in the terminal.

---

## Phase 5: configuration in git, shared correctly

Your global instructions (`~/.claude/CLAUDE.md`), slash commands and helper
scripts should be identical on both machines, and they drift the moment they are
copied. So put them in a git repo and **symlink** them into `~/.claude` on each
machine. An edit is then versioned the moment it is made, and reaches the other
machine with a `git pull`.

**`settings.json` is the exception. Do not share it.** The server needs
`remoteControlAtStartup`; the laptop has different hooks, permissions and
plugins. Symlinking one file onto both silently undoes one machine's settings.
Keep a per-host backup copy in the repo for recovery instead.

Two traps:

- **A symlink made on one machine points at that machine's paths.** If the two
  machines have different usernames, a symlink to `/Users/alice/...` created on
  the laptop is broken on the server. Create symlinks on each machine, from that
  machine, and use `$HOME` in every script.
- **A running session reads `CLAUDE.md` once, when it starts.** Changing the file
  does not change sessions that are already running. Tell them to re-read it, or
  restart them.

**Check:** on the server, `readlink ~/.claude/CLAUDE.md` points inside the
server's own clone of the repo, and the file contents match the laptop's.

---

## Phase 6: MCP servers, per machine

MCP servers are configured **per machine**. A server added on the laptop does not
exist on the server. Plan to install the set each agent needs on the server,
which is where the agents run.

Two kinds show up in `/mcp`:

- **User MCPs**, in `~/.claude.json`, which you add with `claude mcp add`. Per
  machine.
- **Account connectors**, which you link in the claude.ai web app (Gmail, Google
  Calendar, Notion and so on). These follow your account to every machine logged
  into it. You do not install them per machine.

### OAuth on a server you are not sitting at

An OAuth MCP server's login flow starts a callback listener on the **server's**
localhost, then gives you a URL to open. Your browser is on the laptop, so when
the provider redirects to `http://localhost:<port>/callback`, the laptop has
nothing listening and the login fails without an error.

The fix is to forward that one port before clicking:

```
ssh -f -N -L <port>:127.0.0.1:<port> server
```

Then open the URL on the laptop. **Close the tunnel afterwards.** Callback ports
get reused, and a leftover tunnel forwards the next login to a listener that no
longer exists.

### Checking OAuth status honestly

Three things report the wrong answer:

- **Mac server:** `ssh server 'claude mcp list'` shows every OAuth server as
  "Needs authentication" even when it is authed, because that SSH shell cannot
  read the keychain (Phase 3). Run the check from inside tmux instead.
- **A running session caches its MCP status from when it started.** After a login
  completes, `/mcp` in an older session can still say "needs authentication".
  Reconnect it there, or restart the session.
- **"Connected" means a token exists, not that it is the right one.** If you run
  several servers against the same URL for different accounts (three mailboxes,
  say), they are told apart only by which account you pick during login, and
  nothing confirms it afterwards. Name each server after its account
  (`mail-work`, `mail-personal`, never plain `mail`), and after logging in, ask a
  session which address each server actually reads.

**Check:** from inside tmux on the server, `claude mcp list` shows each server
Connected, and a session can make one real call against each.

---

## Phase 7: agents, sessions, and a-team

[a-team](../README.md) is the session manager: a registry of agents (a name, a
folder, a host, a harness) and a way to start or attach one. It is what makes
"start the session for this client on the server, in its own window, named for the client"
one command. **Read [`remote-agents.md`](remote-agents.md) for the host
configuration**; this section covers only what matters for replication.

What you need from it:

- **Host-aware registration.** An agent is registered with a host. Starting it
  from the laptop starts it inside tmux on the server, with Remote Control on.
- **`atx`**, the cold-start helper (`examples/atx`):

  ```
  atx                           list registered agents
  atx <agent>                   attach, starting it if needed
  atx <agent> -n --label Acme   a second, parallel session named for a topic
  atx <agent> -w                open it in its own terminal window
  atx <agent> -L                what is running
  ```

  `--label` matters more than it looks. The phone app lists sessions by name, and
  "Advisor: Acme" is findable where "Advisor 2" is not.

- **One folder per agent, on one host.** The folder holds the agent's
  instructions (`CONTEXT.md`, `.claude/CLAUDE.md`) and working files. Several
  parallel sessions can share a folder.

### Messaging between sessions

There are two mechanisms, and they are not interchangeable.

**Session to session, live:** Claude Code's built-in `SendMessage`, addressed by
the session's Remote Control name:

```
SendMessage({to: "Advisor: Acme", message: "The meeting moved to Thursday."})
```

It wakes an idle session and lands as a turn in its conversation. `ListAgents`
shows who is reachable. This works across machines, because the sessions are
registered with your account. **It only reaches sessions under the same claude.ai
account.** It cannot reach a colleague's agent.

**Agent to agent, durable:** a file-based inbox, one directory per agent, with a
hook that flags unread messages at session start and before tool calls. a-team
ships the pattern; the scripts are small (`send-message.sh` writes a markdown
file into `inbox/<agent>/`, `check-inbox.sh` lists unread ones). Use it for
handoffs that should survive a restart.

**The catch with the inbox:** it is keyed by *agent*, which is by folder. If you
run several labelled sessions in one folder, they share one inbox, and whichever
session's hook fires next picks up the message. For targeting a particular
session, use `SendMessage`.

### Working across people

Sessions are personal: they run as you, with your credentials and every MCP
server you have connected, which may include email and banking. **Do not share a
session with a colleague.** Share context instead: put the instructions, skills
and decision records in the project repo, and each person runs their own agent
against it. Hand work over through the repo's issues and pull requests, which are
durable, threaded and attached to the code. That is the whole pattern, and it
needs no chat bot.

**Check:** `atx` lists your agents; `atx <agent> -w` opens a window on the laptop
showing a session running on the server; that session appears on your phone; and
one session can `SendMessage` another and see it arrive.

---

## Phase 8: the review loop (see what the agent built, and comment on it)

An agent on the server has no screen. These tools close that gap. They are small
scripts; the specification below is enough for an agent to write them.

**`shot <url-or-file> [out.png]`** runs headless Chrome to screenshot a page, so
the agent can read the image and check its own rendering. Options for width and
height, full page, and a settle delay. *An agent that has only read the HTML it
wrote has checked nothing about layout, overflow or a font that did not load.*
Filter Chrome's harmless stderr noise (display link, keychain, allocator
warnings) so real errors are visible.

**`peek <port>`** runs on the laptop. It forwards `<port>` from the server over
SSH and opens `http://localhost:<port>` in a **new browser window** (not a tab: a
tab lands wherever the browser last was, and you go hunting for it). It should
refuse to open if nothing is listening on the server, and refuse if the local
port is already taken. `--path /file.html`, `-l` to list tunnels, `-x <port>` to
close one.

**`annotate <dir> --port N`** serves a directory and injects a comment overlay
into every HTML response. You select text and press a key, or drag a box, and
type a comment. Each comment is saved as JSON beside the served files:

```json
{"comment": "too long", "selected_text": "Job Startup",
 "selector": "#main-heading", "element_html": "<h1 id=\"main-heading\">Job Startup</h1>",
 "rect": {...}, "url": "...", "viewport": {...}}
```

That payload is the point. The agent edits the element you pointed at instead of
hunting for the one it thinks you meant. With `--proxy http://localhost:3000` it
sits in front of a running dev server instead of a directory.

Build notes that each cost an hour:

- **Serve with a threaded server.** A plain single-threaded HTTP server wedges the
  moment a browser connects, because the browser holds its connection open and
  every later request queues behind it. The symptom is misleading: the port still
  shows as listening, the tunnel is fine, and the server returns nothing even to
  a request from its own localhost.
- **The overlay must exclude its own elements** when working out what you
  selected, or a comment lands on the overlay instead of the page.
- **Bind to `127.0.0.1`**, never `0.0.0.0`. The SSH tunnel does not need a wider
  binding, and the material stays on the server.
- **Run it in its own tmux window**, not backgrounded from an SSH command, or it
  dies when the command returns.
- **Hand over the document's URL, not the server root.** Serving a directory
  means the root is an index listing, which returns HTTP 200. Checking "the
  server is up" passes while the link is still wrong. Fetch the actual document
  and confirm its title, and that the overlay was injected.

**Check:** the agent serves a page with `annotate`; you open it with `peek`; you
leave a comment; the agent reads the JSON and names the element you commented on.

---

## Phase 9: letting the server put a page on your screen

Without this, every preview ends with the agent printing a command for you to
run. The obvious fix, giving the server SSH access into the laptop, means
running an SSH server on a machine that goes to cafes and airports, so that
the server can do one trivial thing. Do it the other way round instead:
**the laptop holds a connection out to the server and watches for requests.**

- **`showme <url>`** (on the server) appends a URL to a request file, after
  checking the URL returns 200. It accepts only `http://localhost:<port>/...`.
- **`openwatch`** (on the laptop) runs as a login item with keep-alive. It holds
  `ssh server 'tail -n0 -F ~/.open-requests'` open, and for each line re-checks
  that it is a localhost URL, then calls `peek` with the port and path. It writes
  an acknowledgement back so `showme --wait` can confirm rather than hope.

The server never connects to the laptop, and nothing listens on the laptop. What
it can do is narrow on purpose: show you a page the server itself is serving.

On macOS, run `openwatch` from a LaunchAgent with `KeepAlive` and
`LimitLoadToSessionType: Aqua`; launchd restarts it after sleep or a network
change. On a Linux laptop, a systemd user service does the same.

**Check:** on the server, `showme http://localhost:<port>/page.html`; a browser
window opens on the laptop within a couple of seconds.

---

## Phase 10: getting files to the server

The failure this solves: paste a screenshot into a session running on the server,
and the terminal pastes a **path on the laptop**, which the agent cannot open.
The same happens with any file.

First, most files are already there by another route:

| What | Reaches the server by |
|---|---|
| Code | git |
| Cloud-drive documents | a mirror on the server (rclone, below) |
| Screenshots and screen recordings | `clipwatch`, automatically |
| Anything else | `send` |

Everything that arrives lands in `~/clip` on the server, and **`~/clip/.index`**
records `original filename <TAB> name on the server <TAB> original laptop path`.
When you paste a laptop path, the agent looks up its filename in the index and
reads the local copy. Your paste works unchanged on either machine: on the laptop
the path is real, on the server the index resolves it. Tell the agents this in
the shared `CLAUDE.md`, including "try the path first", or a laptop session will
go looking in `~/clip` for a file that is right there.

**`clipwatch`** (laptop): a login item that watches the screenshot tool's output
directory and copies each new capture to `~/clip` on the server within a second,
writing an index line. Build notes:

- **Leave the clipboard alone.** Replacing it with the server path on every
  capture breaks pasting a screenshot into email or chat, which is most of what
  screenshots are for.
- **Seed a manifest on install and ship nothing.** Otherwise the first run pushes
  your entire screenshot history.
- **Write the manifest atomically** (to a temp name, then move) and take an
  atomic lock (`mkdir`). The watcher fires in bursts, and a second run reading a
  half-written manifest ships files it should have skipped.
- **Ship video too, with a size cap.** A recorded screen share is where the
  spreadsheets and field names are, which a transcript never captures, and with
  `ffmpeg` on the server the agent can pull frames from it. Log anything over the
  cap with the exact copy command rather than pushing it unannounced.
- **Keep file extensions** when renaming.

**`send <path>...`** (laptop): copies any files or directories to `~/clip`,
verifies the remote size matches, writes index lines, and with `-o` puts the
server path(s) on the clipboard. Two refinements that matter:

- **Directories need no flag.** Wire `send -o` to a file-manager right-click
  action, where no flag can be passed.
- **A path inside the cloud-drive folder is not copied.** The mirror already has
  it; hand back the mirrored path instead, or you get two copies drifting apart.

On macOS, a Finder Quick Action is the right-click. **Clone a working Quick
Action and replace its shell script; do not hand-write one.** A hand-written
workflow can register with the services system and run correctly while never
appearing in the menu. The workflow file carries several keys beyond the obvious
ones, and its `Info.plist` needs both `NSRequiredContext` (Finder) and
`NSSendFileTypes` (`public.item`). Compare against a service that takes *files*,
not one that acts on a folder's window.

**The document mirror.** On the server, mirror the cloud drive into a plain
directory with rclone (a bisync every fifteen minutes works). Agents want plain
files, not a sync client. Exclude large media folders the agents do not need.

**Check:** take a screenshot on the laptop, paste it into a session on the server,
and ask what it shows. Then right-click a folder, send it, paste, and ask the
same.

---

## Phase 11: an alarm, because everything here fails silently

Moving work onto an unattended machine trades "I see everything" for "it runs
without me". The price is that failures happen where nobody is looking. In the
reference build, three were found in one day, each weeks or months old, and none
had produced a visible error.

**`pulse`**, runnable from either machine, checks and prints one line each:

- every scheduled job's last exit status is zero
- no scheduled job calls a bare binary that the scheduler's PATH cannot see
- the repos that matter are clean and pushed
- free disk on both machines
- the server is reachable
- **the `main` tmux session is alive** (Mac)
- the expected agent sessions are running

And **`pulse --test`**, which breaks things on purpose (a dirty temporary repo, an
unreachable host, a bare binary under a stripped PATH) and asserts each is
caught. A checker that only ever says "ok" cannot be told apart from a broken
one.

**Check:** `pulse --test` reports every detector working, and `pulse` is clean.

---

## Scheduled work

Use the harness's scheduler (for Claude Code, `CronCreate` inside a session, or a
cloud routine) or launchd/systemd for scripts. Before adding any scheduled job,
**decide where its output lands and who reads it.** Two nightly jobs in the
reference build ran broken for months because their output went to logs nobody
opened.

---

## Traps, collected

Every one of these reports success while doing nothing.

| Trap | Symptom | Fix |
|---|---|---|
| macOS keychain from SSH | Remote Control and OAuth fail over SSH | Phase 3 |
| launchd / Automator strip `PATH` to `/usr/bin:/bin:/usr/sbin:/sbin` | scheduled `claude` call finds nothing; with `2>/dev/null` the error vanishes | call tools by absolute path, or export `PATH` at the top of the script |
| `$?` after a command substitution | `echo "$(date) exit=$?"` logs `date`'s status | capture the status on its own line |
| `set -o pipefail` with a `grep` that may match nothing | pipeline "fails" when all is well | handle grep's exit 1 explicitly |
| `cmd \| grep -q` under `pipefail` | `grep -q` exits early, `cmd` takes SIGPIPE, the pipeline returns 141 | capture output first, then match |
| BSD `sed` and `\|` | matches nothing, changes nothing, exits 0 | `sed -E`, or Python |
| `tmux send-keys ... Enter` into Claude Code | text sits in the prompt unsent | send `C-m` |
| Injecting into a busy session | your text is appended to the running prompt and the first task is lost | check it is idle (`esc to interrupt` absent) first |
| Judging a session busy by the spinner glyph | the same glyph appears in the "done" line | match `esc to interrupt` |
| An MCP server removed from config | its process keeps running and holding its port | kill the process too |
| A stale description in an instruction file | agents reason from it and report findings built on it | verify the thing, not the description |

---

## Why not OpenClaw, Hermes Agent, or a chat bot relay

Self-hosted agent gateways such as **OpenClaw** and **Hermes Agent** solve a
similar-looking problem: an always-on agent you reach from your phone, usually
through Telegram, Discord, WhatsApp or similar. The reference build ran an
OpenClaw relay for a while and retired it. The reasons are about this
architecture, not a judgment of those projects:

- **One agent runtime, not two.** A gateway is its own agent loop with its own
  tools, memory, configuration and instruction files. Running it beside Claude
  Code meant two places to keep skills and instructions current, and they drifted.
- **Remote Control reaches the real session.** The phone app opens the same
  conversation, with the same context and tools, that the terminal is showing. A
  relay bot is a separate conversation that has to be told what the real one
  knows.
- **A chat app is a lossy interface for agent work.** Tool calls, diffs, file
  paths and long output are awkward in a chat thread and native in the Claude
  apps.
- **Less exposed.** A gateway is a network service holding tokens. In the
  reference build its gateway token was visible in the process table. Remote
  Control uses your existing account session and opens no port.
- **Messaging between sessions was already there.** `SendMessage` plus the inbox
  covers what the relay was being used for.

When a gateway is the better choice: you do not have a Claude subscription, or
you want a model-agnostic agent, or the chat app *is* the point (a family group
chat, a team channel people already live in).

---

## Order of work, for an agent following this

1. Phase 1 to 4 get a session running on the server that you can reach from the
   laptop and the phone. **Do not continue until the phone check passes.**
2. Phases 5 and 6 make the server's sessions as capable as the laptop's.
3. Phase 7 makes it manageable: named agents, parallel sessions, messaging.
4. Phases 8 to 10 are what make it pleasant to work with: seeing and commenting on
   what an agent built, and getting files to it.
5. Phase 11 before relying on any of it unattended.

Report each check's actual output, not a summary of it.
