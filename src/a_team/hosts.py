"""Where an agent lives: this machine, or a remote box reached over SSH.

a-team itself runs on your main machine. An agent's `host` says where its
*folder* and its *session* live:

  local      -> this machine. Ghostty window runs `cd <path> && <engine>`.
  <name>     -> a remote host. The folder lives there and the session runs
                there inside tmux; the Ghostty window is just a viewport
                attached over mosh (falling back to ssh).

Remote hosts are **configured, not hardcoded**. Define them in agents.toml:

    [hosts]
    server = "myserver"       # host key -> ssh target (a ~/.ssh/config alias
    build  = "user@10.0.0.5"  #             or user@host)

The ssh target must already work non-interactively (`ssh <target> true`).
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

DEFAULT_HOST = "local"


@dataclass(frozen=True)
class Host:
    key: str  # stored in the registry
    label: str  # shown in CLI/UI
    ssh_alias: str | None  # None => this machine

    @property
    def is_remote(self) -> bool:
        return self.ssh_alias is not None

    def run(self, command: str, timeout: int = 20) -> subprocess.CompletedProcess:
        """Run a shell command on this host (locally, or over SSH)."""
        if not self.is_remote:
            argv = ["bash", "-lc", command]
        else:
            argv = ["ssh", "-o", "ConnectTimeout=8", self.ssh_alias, command]
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    def dir_exists(self, path: str) -> bool:
        try:
            return self.run(f"test -d {shlex.quote(path)}").returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def mkdir(self, path: str) -> bool:
        """Create the directory (parents included). True on success."""
        try:
            return self.run(f"mkdir -p {shlex.quote(path)}").returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def home(self) -> str:
        """This host's home directory (used to expand a leading `~`)."""
        try:
            return self.run('printf %s "$HOME"').stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return ""

    def reachable(self) -> bool:
        """For a remote host: can we actually get there right now?"""
        if not self.is_remote:
            return True
        try:
            return self.run("true", timeout=12).returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def launch_command(self, path: str, engine_cmd: str, session: str) -> str:
        """The command the Ghostty window runs.

        local: cd into the folder and start the engine.
        remote: attach-or-create a named tmux session on that host, so the agent
        survives this window closing, and attach over mosh (ssh fallback)."""
        if not self.is_remote:
            return f"cd {shlex.quote(path)} && {engine_cmd}"
        inner = f"cd {shlex.quote(path)} && {engine_cmd}"
        tmux = f"tmux new-session -A -s {shlex.quote(session)} {shlex.quote(inner)}"
        return (
            f"mosh {self.ssh_alias} -- {tmux} "
            f"|| ssh -t {self.ssh_alias} {shlex.quote(tmux)}"
        )


LOCAL = Host(key=DEFAULT_HOST, label="This Mac", ssh_alias=None)


def all_hosts() -> dict[str, Host]:
    """`local` plus every host defined in the registry's [hosts] table."""
    from . import config  # local import: config imports us

    out: dict[str, Host] = {LOCAL.key: LOCAL}
    try:
        table = config.load_hosts_table()
    except Exception:
        table = {}
    for key, target in table.items():
        k = str(key).strip().lower()
        if k == LOCAL.key or not target:
            continue
        out[k] = Host(key=k, label=f"{key} (remote)", ssh_alias=str(target))
    return out


# Backwards/ergonomic alias so callers can write `hosts.HOSTS` like a dict.
class _HostsView(dict):
    def __getitem__(self, k):
        return all_hosts()[k]

    def __iter__(self):
        return iter(all_hosts())

    def __len__(self):
        return len(all_hosts())

    def values(self):
        return all_hosts().values()

    def keys(self):
        return all_hosts().keys()

    def items(self):
        return all_hosts().items()

    def __contains__(self, k):
        return k in all_hosts()


HOSTS = _HostsView()


def normalize_key(value: str | None) -> str:
    """Map a raw registry/CLI value to a configured host key, default local."""
    if not value:
        return DEFAULT_HOST
    v = value.strip().lower()
    known = all_hosts()
    if v in known:
        return v
    if v in ("this", "here"):
        return DEFAULT_HOST
    raise ValueError(
        f"unknown host: {value!r} (configured: {', '.join(known)}). "
        f"Add remote hosts to the [hosts] table in agents.toml."
    )


def get(key: str | None) -> Host:
    return all_hosts()[normalize_key(key)]
