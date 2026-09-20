"""Read and write the agents.toml registry."""

import os
import re
import shutil
import time
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w

from . import harness as _harness
from . import hosts as _hosts

_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "a-team" / "agents.toml"


def slugify(label: str) -> str:
    """Folder-safe slug from a display name: 'Art Handler' -> 'art-handler'."""
    return re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower()

AgentKind = Literal["persistent", "ephemeral"]

# Throwaway "scratch" sessions (one-off chats) live in a hidden home dir
# rather than ~/Documents/ so they're not TCC-protected and stay separate
# from real project folders.
SCRATCH_DIR = Path.home() / ".a-team" / "scratch"
SCRATCH_CATEGORY = "Scratch"


def config_path() -> Path:
    """Return the active config path. Override via $A_TEAM_CONFIG for demos
    or alternate registries."""
    env = os.environ.get("A_TEAM_CONFIG")
    if env:
        return Path(env).expanduser()
    return _DEFAULT_CONFIG_PATH


# Backwards-compatible alias for callers reading the path directly.
CONFIG_PATH = _DEFAULT_CONFIG_PATH


def _ensure_config_exists() -> None:
    """Create the config dir + empty file if missing."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# a-team agent registry\n")


def _load_raw() -> dict:
    _ensure_config_exists()
    with config_path().open("rb") as f:
        return tomllib.load(f)


def _save_raw(data: dict) -> None:
    """Write the registry atomically: serialize to a temp file in the same
    directory, then os.replace() over the target. A crash mid-write leaves the
    old registry intact rather than a truncated file."""
    _ensure_config_exists()
    p = config_path()
    tmp = p.with_name(p.name + f".tmp.{os.getpid()}")
    try:
        with tmp.open("wb") as f:
            tomli_w.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def load_agents() -> list[dict]:
    """Return the list of agent dicts from agents.toml.

    Each dict has keys: name, path, kind, and optionally category.
    """
    return _load_raw().get("agent", [])


def save_agents(agents: list[dict]) -> None:
    """Write the agent list back, preserving any [settings] table."""
    data = _load_raw()
    data["agent"] = agents
    _save_raw(data)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def load_settings() -> dict:
    """Return the [settings] table (or empty dict if absent)."""
    return _load_raw().get("settings", {})


def get_setting(key: str) -> str | None:
    return load_settings().get(key)


def set_setting(key: str, value: str | None) -> None:
    """Set or clear a setting. Pass value=None to clear."""
    data = _load_raw()
    settings = data.setdefault("settings", {})
    if value is None:
        settings.pop(key, None)
        if not settings:
            data.pop("settings", None)
    else:
        settings[key] = value
    _save_raw(data)


def get_default_host() -> str:
    """Host key used by `a-team new` when --host isn't given.

    Set with `a-team config default-host <key>`. Falls back to local if the
    setting is missing or names a host that's no longer in [hosts].
    """
    from . import hosts as _hosts

    raw = get_setting("default_host")
    if not raw:
        return _hosts.DEFAULT_HOST
    try:
        return _hosts.normalize_key(raw)
    except ValueError:
        return _hosts.DEFAULT_HOST


def get_default_parent() -> Path | None:
    """Return the default parent directory for scaffolded agents, or None."""
    raw = get_setting("default_parent")
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    return p if p.is_dir() else None


# ---------------------------------------------------------------------------
# Accounts (which Claude login a session runs under)
# ---------------------------------------------------------------------------
#
# A session's Claude account is selected by CLAUDE_CONFIG_DIR: each config dir
# holds its own login (keychain credential keyed by a hash of the dir). The
# default ("" / personal) uses ~/.claude. Resolution order for an agent:
#   explicit per-agent `account` field  ->  category rule  ->  "personal".
# Define your own profiles + rules with [accounts] / [account_by_category]
# tables in agents.toml, e.g.:
#   [accounts]
#   work = "~/.claude-work"
#   [account_by_category]
#   Work = "work"

_DEFAULT_ACCOUNTS = {
    "personal": "",  # "" => default ~/.claude (no CLAUDE_CONFIG_DIR)
}
_DEFAULT_ACCOUNT_BY_CATEGORY: dict = {}


def load_hosts_table() -> dict:
    """The [hosts] table: host key -> ssh target. Empty if unset.

    Remote hosts are user configuration, never hardcoded in source:
        [hosts]
        server = "myserver"
    """
    return _load_raw().get("hosts", {})


def load_accounts() -> dict:
    """Account name -> CLAUDE_CONFIG_DIR. Defaults merged with agents.toml [accounts]."""
    return {**_DEFAULT_ACCOUNTS, **_load_raw().get("accounts", {})}


def load_account_by_category() -> dict:
    """Category -> account name. Defaults merged with agents.toml [account_by_category]."""
    return {**_DEFAULT_ACCOUNT_BY_CATEGORY, **_load_raw().get("account_by_category", {})}


def resolve_account(agent: dict) -> str:
    """Account name for an agent: explicit override -> category rule -> 'personal'."""
    explicit = agent.get("account")
    if explicit:
        return explicit
    cat = agent.get("category")
    if cat:
        mapped = load_account_by_category().get(cat)
        if mapped:
            return mapped
    return "personal"


def resolve_config_dir(agent: dict, harness: str | None = None) -> str | None:
    """Config dir for an agent's account, or None for personal/default.

    The account system is Claude-specific in v1 (it maps to CLAUDE_CONFIG_DIR),
    so this returns None for any non-Claude harness rather than handing a Claude
    config dir to Codex. `harness` overrides the agent's saved harness for a
    one-time open."""
    key = _harness.normalize_key(harness) if harness else _harness.normalize_key(agent.get("harness"))
    if key != _harness.DEFAULT_HARNESS:
        return None
    raw = load_accounts().get(resolve_account(agent), "")
    return str(Path(raw).expanduser()) if raw else None


# ---------------------------------------------------------------------------
# Identity: stable id + harness
# ---------------------------------------------------------------------------
#
# An agent's identity is its stable `id`, not its display `name`. Renaming an
# agent changes `name` but never `id`, so its inbox and history stay put. The
# `harness` field records the default runtime (claude | codex); it is a runtime
# choice, not part of identity. Legacy entries have neither field: we backfill
# them IN MEMORY (id from the name slug, harness = claude) so everything works,
# but never rewrite the live file except through the explicit migration path.


def _agent_aliases(agent: dict) -> list[str]:
    raw = agent.get("aliases", [])
    return [str(a) for a in raw] if isinstance(raw, list) else []


def _normalized(agents: list[dict]) -> list[dict]:
    """Return copies with `id` and `harness` guaranteed. Backfilled ids come
    from the name slug, de-duplicated across the set; explicit ids win."""
    used: set[str] = {a["id"] for a in agents if a.get("id")}
    out: list[dict] = []
    for a in agents:
        b = dict(a)
        if not b.get("id"):
            base = slugify(b.get("name", "")) or "agent"
            candidate, n = base, 2
            while candidate in used:
                candidate, n = f"{base}-{n}", n + 1
            b["id"] = candidate
            used.add(candidate)
        b["harness"] = _harness.normalize_key(b.get("harness"))
        b["host"] = _hosts.normalize_key(b.get("host"))
        out.append(b)
    return out


def load_agents_normalized() -> list[dict]:
    """Agents with id + harness filled in (does not modify the file)."""
    return _normalized(load_agents())


def resolve_agent(identifier: str) -> dict | None:
    """Resolve an identifier to exactly one agent, or None if no match.

    Match order: stable id, then exact name, then an explicit alias. Raises
    ValueError if the identifier is ambiguous (matches more than one agent),
    rather than silently returning the first — the ambiguity the issue warns
    against. Returns the normalized dict (id + harness present)."""
    agents = load_agents_normalized()
    by_id = [a for a in agents if a["id"] == identifier]
    if by_id:
        return by_id[0]  # ids are unique by construction
    by_name = [a for a in agents if a.get("name") == identifier]
    if len(by_name) > 1:
        raise ValueError(f"identifier {identifier!r} matches multiple agents by name; use the id")
    if by_name:
        return by_name[0]
    by_alias = [a for a in agents if identifier in _agent_aliases(a)]
    if len(by_alias) > 1:
        raise ValueError(f"alias {identifier!r} matches multiple agents; use the id")
    return by_alias[0] if by_alias else None


def find_agent(name: str) -> dict | None:
    """Back-compat resolver by name/id/alias. Returns None when unresolved.

    Kept for existing callers; new code should use `resolve_agent`. Ambiguity
    (a duplicate name) returns None here rather than raising, to preserve the
    old best-effort contract at call sites that don't expect an exception."""
    try:
        return resolve_agent(name)
    except ValueError:
        return None


def resolve_harness(agent: dict, override: str | None = None) -> _harness.Harness:
    """The harness to launch an agent under: one-time override, else the saved
    default, else Claude. An override never mutates the saved default."""
    key = override if override else agent.get("harness")
    return _harness.get(key)


def resolve_host(agent: dict, override: str | None = None) -> _hosts.Host:
    """Where this agent lives: one-time override, else the saved host, else local."""
    return _hosts.get(override if override else agent.get("host"))


def prepare_path(path: str, host: str | None = None, *, create: bool = False) -> str:
    """Validate (and optionally create) an agent folder on the right machine.

    Local paths are expanded and resolved here. Remote paths are checked over SSH
    on that host, never against this filesystem, and a leading `~` is expanded to
    the *remote* home. Returns the path to store in the registry."""
    h = _hosts.get(host)
    if not h.is_remote:
        resolved = Path(path).expanduser()
        if create:
            resolved.mkdir(parents=True, exist_ok=True)
        resolved = resolved.resolve()
        if not resolved.is_dir():
            raise ValueError(f"path is not a directory: {path}")
        return str(resolved)

    if not h.reachable():
        raise ValueError(f"host '{h.key}' is not reachable right now (check `ssh {h.ssh_alias}`)")
    remote = path
    if remote.startswith("~"):
        home = h.run("printf %s \"$HOME\"").stdout.strip()
        if not home:
            raise ValueError(f"could not determine home directory on host '{h.key}'")
        remote = home + remote[1:]
    if not h.dir_exists(remote):
        if not create:
            raise ValueError(f"path does not exist on host '{h.key}': {remote}")
        if not h.mkdir(remote):
            raise ValueError(f"could not create {remote} on host '{h.key}'")
    return remote


def migrate_registry(*, apply: bool) -> dict:
    """Backfill stable `id` + `harness` into the on-disk registry.

    Legacy entries carry neither field; this writes the same values that are
    otherwise backfilled in memory, making identity durable (rename-safe inboxes)
    and the saved harness explicit. Existing ids/harness are left untouched.

    Returns a report dict: {path, total, changes:[(name, id, harness)], backup}.
    With apply=False nothing is written (dry run). With apply=True and at least
    one change, the current registry is copied to `<name>.bak-<timestamp>` first,
    then the normalized agents are written atomically, preserving all other
    tables ([settings]/[accounts]/…) and every existing field."""
    raw = load_agents()
    norm = _normalized(raw)
    changes = [
        (n["name"], n["id"], n["harness"])
        for a, n in zip(raw, norm)
        if not a.get("id") or not a.get("harness")
    ]
    report: dict = {
        "path": str(config_path()),
        "total": len(raw),
        "changes": changes,
        "backup": None,
    }
    if apply and changes:
        p = config_path()
        bak = p.with_name(p.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(p, bak)
        report["backup"] = str(bak)
        save_agents(norm)  # preserves [settings]/[accounts] via _load_raw + atomic write
    return report


def _new_id(name: str, existing_ids: set[str], explicit: str | None = None) -> str:
    """A stable, unique id for a new agent: the explicit id if given and free,
    else the name slug de-duplicated with a numeric suffix."""
    if explicit:
        if explicit in existing_ids:
            raise ValueError(f"agent id '{explicit}' already exists")
        return explicit
    base = slugify(name) or "agent"
    candidate, n = base, 2
    while candidate in existing_ids:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def add_agent(
    name: str,
    path: str,
    kind: AgentKind = "persistent",
    category: str | None = None,
    account: str | None = None,
    harness: str | None = None,
    agent_id: str | None = None,
    host: str | None = None,
    create_dir: bool = False,
) -> dict:
    """Append a new agent with a stable id, saved harness, and host.

    `host` is where the agent's folder and session live: "local", or a key
    from the [hosts] table in agents.toml.
    For a remote host the folder is validated (and with create_dir=True, created)
    ON THAT MACHINE over SSH, never against this filesystem. `account` is an
    explicit override; leave None to let the category rule decide the Claude
    account. `harness` defaults to Claude Code."""
    if find_agent(name):
        raise ValueError(f"agent '{name}' already exists")
    host_key = _hosts.normalize_key(host)
    stored_path = prepare_path(path, host_key, create=create_dir)

    existing = {a["id"] for a in load_agents_normalized()}
    new_id = _new_id(name, existing, agent_id)
    harness_key = _harness.normalize_key(harness)

    agents = load_agents()
    agent: dict = {
        "id": new_id,
        "name": name,
        "path": stored_path,
        "kind": kind,
        "harness": harness_key,
        "host": host_key,
    }
    if category:
        agent["category"] = category
    if account:
        agent["account"] = account
    agents.append(agent)
    save_agents(agents)
    return agent


def remove_agent(name: str) -> bool:
    """Remove an agent by name. Returns True if removed, False if not found."""
    agents = load_agents()
    new_agents = [a for a in agents if a["name"] != name]
    if len(new_agents) == len(agents):
        return False
    save_agents(new_agents)
    return True


def update_agent(
    name: str,
    *,
    new_name: str | None = None,
    new_path: str | None = None,
    new_category: str | None = None,
    new_account: str | None = None,
) -> dict:
    """Rename, change path, category, or account of an existing agent.
    Pass new_account="" to clear the override and fall back to the category rule.
    Raises if not found or if new_name collides."""
    agents = load_agents()
    target = next((a for a in agents if a["name"] == name), None)
    if not target:
        raise ValueError(f"agent '{name}' not found")

    if new_name and new_name != name:
        if any(a["name"] == new_name for a in agents):
            raise ValueError(f"agent '{new_name}' already exists")
        target["name"] = new_name

    if new_path:
        resolved = Path(new_path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"path is not a directory: {new_path}")
        target["path"] = str(resolved)

    if new_category is not None:
        if new_category:
            target["category"] = new_category
        else:
            target.pop("category", None)

    if new_account is not None:
        if new_account:
            target["account"] = new_account
        else:
            target.pop("account", None)

    save_agents(agents)
    return target


def list_categories() -> list[str]:
    """Return all distinct category names currently in use, in insertion order."""
    seen: list[str] = []
    for a in load_agents():
        cat = a.get("category")
        if cat and cat not in seen:
            seen.append(cat)
    return seen


def is_path_registered(path: str) -> bool:
    """Check whether a folder path is already registered as an agent."""
    resolved = str(Path(path).expanduser().resolve())
    return any(a["path"] == resolved for a in load_agents())
