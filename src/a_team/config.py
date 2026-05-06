"""Read and write the agents.toml registry."""

import tomllib
from pathlib import Path
from typing import Literal

import tomli_w

CONFIG_PATH = Path.home() / ".config" / "a-team" / "agents.toml"

AgentKind = Literal["persistent", "ephemeral"]


def _ensure_config_exists() -> None:
    """Create the config dir + empty file if missing."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("# a-team agent registry\n")


def _load_raw() -> dict:
    _ensure_config_exists()
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def _save_raw(data: dict) -> None:
    _ensure_config_exists()
    with CONFIG_PATH.open("wb") as f:
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
) -> dict:
    """Append a new agent. Raises ValueError if name already exists or
    path doesn't exist."""
    if find_agent(name):
        raise ValueError(f"agent '{name}' already exists")
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"path is not a directory: {path}")

    agents = load_agents()
    agent: dict = {"name": name, "path": str(resolved), "kind": kind}
    if category:
        agent["category"] = category
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
