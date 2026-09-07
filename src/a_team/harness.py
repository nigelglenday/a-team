"""Harness adapter boundary.

A *harness* is the CLI that actually runs an agent's turns — Claude Code
(``claude``) or Codex (``codex``). It is a runtime choice, not the agent's
identity: the same registered agent can be opened under either harness.

This module isolates every place the two differ — executable name, the launch
verbs for new/continue/resume, the per-account config environment variable, and
availability — so the rest of a-team stays harness-neutral and we don't scatter
``if harness == "claude"`` conditionals through the app.

Deliberately minimal for v1. It does NOT try to make Claude accounts configure
Codex: each harness exports only its *own* config variable, so a Claude config
dir can never leak into Codex as ``CLAUDE_CONFIG_DIR`` (a hazard called out in
the issue). Codex account/profile mapping is intentionally unsupported here
rather than faked.
"""

from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass

SessionMode = str  # "new" | "continue" | "resume"

DEFAULT_HARNESS = "claude"


@dataclass(frozen=True)
class Harness:
    key: str  # stable identifier stored in the registry: "claude" | "codex"
    label: str  # human label for CLI/UI: "Claude Code" | "Codex"
    executable: str  # command that must be on PATH
    config_env_var: str | None  # env var that selects this harness's config/account home
    # Launch verbs keyed by session_mode. Each value is a bash fragment run
    # after `cd`-ing into the agent directory. The continue/resume verbs fall
    # back to a fresh session so a first-ever open never dead-ends.
    _verbs: dict[str, str]

    def launch_command(self, session_mode: SessionMode) -> str:
        """Bash command that starts this harness in the requested mode.

        Unknown modes fall back to 'continue' (matching prior a-team behavior)."""
        return self._verbs.get(session_mode, self._verbs["continue"])

    def is_available(self) -> bool:
        """True if this harness's executable is on PATH."""
        return shutil.which(self.executable) is not None

    def env_prefix(self, config_dir: str | None) -> str:
        """`export VAR=dir; ` prefix, or '' when no dir applies.

        Always uses THIS harness's own config_env_var — never another's — so a
        config dir resolved for one harness can never be exported under the
        wrong variable name."""
        if not config_dir or not self.config_env_var:
            return ""
        return f"export {self.config_env_var}={shlex.quote(config_dir)}; "


CLAUDE = Harness(
    key="claude",
    label="Claude Code",
    executable="claude",
    config_env_var="CLAUDE_CONFIG_DIR",
    _verbs={
        "new": "claude",
        "continue": "{ claude --continue || claude; }",
        "resume": "{ claude --resume || claude; }",
    },
)

# Codex verbs verified against codex-cli 0.142.0:
#   codex                -> fresh interactive session
#   codex resume --last  -> continue most recent session in this cwd
#   codex resume         -> interactive picker (cwd-filtered by default)
# resume/continue fall back to a fresh `codex` if there is no prior session.
CODEX = Harness(
    key="codex",
    label="Codex",
    executable="codex",
    config_env_var="CODEX_HOME",
    _verbs={
        "new": "codex",
        "continue": "{ codex resume --last || codex; }",
        "resume": "{ codex resume || codex; }",
    },
)

HARNESSES: dict[str, Harness] = {CLAUDE.key: CLAUDE, CODEX.key: CODEX}


def normalize_key(value: str | None) -> str:
    """Map a raw registry/CLI value to a known harness key, defaulting to Claude.

    Accepts the key or the label, case-insensitively (e.g. 'Codex', 'codex')."""
    if not value:
        return DEFAULT_HARNESS
    v = value.strip().lower()
    if v in HARNESSES:
        return v
    for h in HARNESSES.values():
        if v == h.label.lower():
            return h.key
    raise ValueError(f"unknown harness: {value!r} (expected one of {', '.join(HARNESSES)})")


def get(key: str | None) -> Harness:
    """Return the Harness for a key/label, defaulting to Claude for empty."""
    return HARNESSES[normalize_key(key)]
