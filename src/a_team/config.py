"""Read and write the agents.toml registry."""

import os
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w

_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "a-team" / "agents.toml"

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
    _ensure_config_exists()
    with config_path().open("wb") as f:
        tomli_w.dump(data, f)


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


def resolve_config_dir(agent: dict) -> str | None:
    """CLAUDE_CONFIG_DIR for an agent's account, or None for personal/default."""
    raw = load_accounts().get(resolve_account(agent), "")
    return str(Path(raw).expanduser()) if raw else None


def find_agent(name: str) -> dict | None:
    """Return the agent dict with the given name, or None."""
    for a in load_agents():
        if a["name"] == name:
            return a
    return None


def add_agent(
    name: str,
    path: str,
    kind: AgentKind = "persistent",
    category: str | None = None,
    account: str | None = None,
) -> dict:
    """Append a new agent. Raises ValueError if name already exists or
    path doesn't exist. `account` is stored only as an explicit override; leave
    it None to let the category rule decide the Claude account."""
    if find_agent(name):
        raise ValueError(f"agent '{name}' already exists")
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"path is not a directory: {path}")

    agents = load_agents()
    agent: dict = {"name": name, "path": str(resolved), "kind": kind}
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
) -> dict:
    """Rename, change path, or change category of an existing agent.
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
