# Running agents on a second machine

a-team can register an agent whose folder and session live on **another** machine,
reached over SSH. The pattern: an always-on Mac acts as the server, your laptop is
the cockpit you reach it through, and your phone is a third window onto the same
sessions.

This document covers the setup and the two non-obvious things that break it.

## Configuring a host

Remote hosts are configured, never hardcoded. Add a `[hosts]` table to `agents.toml`:

```toml
[hosts]
server = "myserver"        # key -> ssh target (a ~/.ssh/config alias
build  = "user@10.0.0.5"   #        or user@host)
```

The ssh target must already work non-interactively (`ssh <target> true`).

Then register agents against it:

```bash
a-team new "Build Agent" --host server              # folder created on that machine
a-team new "Build Agent" '~/work/build' --host server
a-team config default-host server                   # make it the default for new agents
```

With a default host set, `a-team new "Build Agent"` needs no flags: the folder is
created on that machine at `~/agents/<slug>` and the registry records `host`.

A remote agent's session runs inside `tmux new-session -A -s <id>` on its host, so
it survives your window closing, and the local window attaches over `mosh` (falling
back to `ssh -t`). Mosh matters more than it looks: it does local echo and survives
roaming and packet loss, which is the difference between usable and unusable on
airport or hotel wifi.

## Remote Control: reaching those sessions from a phone

Claude Code's Remote Control makes a running session reachable from the phone app
and from `claude.ai/code`. a-team starts remote agents with
`--remote-control "<agent name>"` automatically.

Two reasons it passes the name rather than letting the runtime pick one:

1. **Discovery.** An unnamed session shows up as `hostname-ancient-wirth`. With
   several agents running you cannot tell them apart, least of all on a phone.
2. **Cross-session messaging.** A session is only addressable by other sessions
   once Remote Control is on. Without it, a session running perfectly well on the
   server is invisible to every other session.

Codex has no equivalent flag, so it is omitted for that harness. Local agents are
left alone: you are already sitting at that machine.

### Implementation note

The launch verbs are compound, e.g. `{ claude --continue || claude; }`. A flag
appended to that string would land on the first arm only, so a failed `--continue`
would silently fall back to an **unnamed, unreachable** session. The verbs
therefore template the executable:

```python
_verbs = {
    "new":      "{exe}",
    "continue": "{{ {exe} --continue || {exe}; }}",
}
```

so `extra_args` is spliced into every position. There is a test asserting the flag
appears twice in the continue verb.

## Gotcha 1: the keychain, or why `/rc` fails over SSH

**Symptom.** A session started on the remote machine reports `Not logged in`, and
`/remote-control` answers with an Enterprise/API-key message, even though that
machine is signed in and `~/.claude.json` contains an `oauthAccount`.

**Cause.** macOS runs SSH logins in the `Background` security session. Keychain
items are only reachable from the `Aqua` (GUI) session. Check it:

```bash
launchctl managername                     # SSH shell prints: Background
security find-generic-password -s "Claude Code-credentials" -w >/dev/null
echo $?                                   # 36 = interaction not allowed
```

With no readable credential, Claude Code falls back to API-key mode, where Remote
Control is unavailable. Nothing reports this clearly; sessions just quietly lack it.

**Fix.** tmux panes are children of the **tmux server** and inherit its security
session. Start the server once from a GUI terminal on that machine (screen sharing
is fine, the lid can be closed), and every session created over SSH afterwards
inherits `Aqua`:

```bash
# in a GUI terminal on the remote machine
tmux kill-server                 # drops any Background-context server
tmux new-session -d -s main
security find-generic-password -s "Claude Code-credentials" -w >/dev/null && echo OK
```

`OK` means it worked. Because a-team uses `tmux new-session -A`, its sessions join
that same server and inherit the access.

**Make it survive reboot** with a LaunchAgent restricted to `Aqua`:

```xml
<key>LimitLoadToSessionType</key><string>Aqua</string>
<key>ProgramArguments</key>
<array>
  <string>/bin/sh</string><string>-c</string>
  <string>tmux has-session -t main 2>/dev/null || tmux new-session -d -s main</string>
</array>
<key>RunAtLoad</key><true/>
```

Use the `has-session` guard, not `tmux new-session -A`: with `-A` tmux tries to
*attach* when the session already exists, which fails under launchd with
`open terminal failed: not a terminal`.

Caveat: the machine has to actually reach GUI login after a reboot. With FileVault
on it waits at the unlock screen, and no `Aqua` session exists until someone
types the password.

## Gotcha 2: workspace trust

Each folder shows a one-time trust prompt the first time Claude Code runs in it on
that machine. An unattended launch stalls there. Remote Control also requires the
folder to have been trusted. Open each new folder once interactively.

## Gotcha 3: the remote machine is a different computer

Obvious, and still the most common cause of a "working" remote agent that cannot do
anything:

- **MCP servers do not come along.** They are configured per machine. An agent moved
  to a server has its files and none of its tools until you install them there.
  OAuth-based servers need a browser step; a headless box makes that awkward.
- **Cloud-storage clients do not come along.** If your laptop uses a sync client and
  the server uses something else (rclone, say), the two see different trees and
  sync on different schedules. Anything stored in a provider-native format (Google
  Docs, Sheets) may not exist as a real file on the server at all.
- **Credentials do not come along**, and copying them widens what is exposed if the
  server is lost.

Decide hosting by **who drives the agent**, not by subject matter:

- **Server**: unattended, long-running, triggered work. Builds you kick off and
  come back to, monitors, scheduled jobs.
- **Laptop**: work you do interactively, especially away from the network. A session
  on the server is unreachable from a plane; local files are not.

## Cold start without the TUI

Once an agent is running on the server it is reachable from the phone and from
other sessions, so the terminal's only remaining job is the cold start. That can be
a one-liner over the registry:

```bash
a-team resolve <agent> --json     # id, name, path, host, ssh, harness
```

Resolve the agent, then `ssh <host>` and `tmux has-session -t <id> || tmux
new-session -d -s <id> -c <path> '<harness> --remote-control "<name>"'`, attaching
with mosh. `a-team resolve` is the single resolver: never guess a path or host
anywhere else.

See `examples/` for a working script.
