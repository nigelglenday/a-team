"""A registry kept in git.

Two machines that each keep their own `agents.toml` drift: one gets a new agent,
the other never hears of it, and every tool that reads the stale copy is quietly
wrong. So the registry can live in a git repo instead, with
`~/.config/a-team/agents.toml` on every machine a symlink to the file in that
repo's checkout.

That checkout is only ever pulled. When the registry is a symlink into a git
checkout, a-team never writes through the link: it adds a throwaway worktree on a
new branch, writes the file there, commits, pushes, and lands the branch on the
default branch, either with a `land` command on PATH (which merges into the
checkout under a lock) or, with no `land`, by pushing to the default branch and
fast-forwarding the checkout. Then it pulls the checkout on every host in the
[hosts] table (only without `land`: a `land` is expected to do its own
follow-up). A write based on a stale copy is refused, never merged.

Set `registry_source = "<path to the file in the checkout>"` under [settings] and
a-team refuses to write when agents.toml is not a symlink to it, and `a-team
doctor` says so, on this machine and on every host.
"""

import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


class RegistryError(RuntimeError):
    """A git-backed write that could not be made. Nothing was changed."""


def _git(*args: str, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _say(msg: str) -> None:
    print(f"a-team: {msg}", file=sys.stderr)


def backing(p: Path) -> tuple[Path, Path] | None:
    """(checkout top level, file path inside it) when `p` is a symlink into a git
    checkout; None for a plain file."""
    if not p.is_symlink():
        return None
    target = p.resolve()
    if not target.parent.is_dir():
        return None
    r = _git("rev-parse", "--show-toplevel", cwd=target.parent, timeout=15)
    if r.returncode != 0:
        return None
    top = Path(r.stdout.strip()).resolve()
    return top, target.relative_to(top)


def _default_branch(top: Path) -> str:
    r = _git("rev-parse", "--abbrev-ref", "origin/HEAD", cwd=top, timeout=15)
    ref = r.stdout.strip() if r.returncode == 0 else ""
    return ref.split("/", 1)[1] if ref.startswith("origin/") else "main"


def _summary(old: dict, new: dict) -> str:
    """One line naming what changed, for the commit subject."""
    def by_id(d: dict) -> dict:
        return {(a.get("id") or a.get("name")): a for a in d.get("agent", [])}
    o, n = by_id(old), by_id(new)
    name = lambda a: a.get("name") or a.get("id") or "?"
    parts = []
    added = [name(n[k]) for k in n if k not in o]
    removed = [name(o[k]) for k in o if k not in n]
    changed = [name(n[k]) for k in n if k in o and n[k] != o[k]]
    if added:
        parts.append("add " + ", ".join(added))
    if removed:
        parts.append("remove " + ", ".join(removed))
    if changed:
        parts.append("update " + ", ".join(changed))
    other = sorted(k for k in set(old) | set(new) if k != "agent" and old.get(k) != new.get(k))
    if other:
        parts.append("change [" + "], [".join(other) + "]")
    return "registry: " + ("; ".join(parts) or "rewrite")


def check_source(p: Path, settings: dict) -> str | None:
    """Why this machine's registry is not the configured source, or None."""
    src = settings.get("registry_source")
    if not src:
        return None
    want = Path(os.path.expanduser(src)).resolve()
    if not p.is_symlink():
        return f"{p} is a plain file, not a symlink to {want}"
    if p.resolve() != want:
        return f"{p} points at {p.resolve()}, not {want}"
    return None


def save(p: Path, old: dict, new: dict, render, hosts: dict) -> None:
    """Write `new` through git. `render(data, existing_text)` serializes it.

    Raises RegistryError, having changed nothing, when the local copy is behind
    the remote (it is fast-forwarded first, so running the command again works),
    or when any git step fails."""
    top, rel = backing(p)
    if _git("fetch", "-q", "origin", cwd=top, timeout=60).returncode != 0:
        raise RegistryError(f"could not fetch {top}; the registry is unchanged")
    base = _default_branch(top)
    shown = _git("show", f"origin/{base}:{rel}", cwd=top)
    upstream = shown.stdout if shown.returncode == 0 else ""
    if upstream != p.read_text():
        ff = _git("merge", "-q", "--ff-only", f"origin/{base}", cwd=top)
        how = ("it has been brought up to date" if ff.returncode == 0
               else f"and it could not be fast-forwarded ({ff.stderr.strip()[:200]})")
        raise RegistryError(f"{top / rel} differs from origin/{base}; {how}. "
                            "Nothing was written. Run the command again.")

    payload = render(new, upstream)
    branch = f"a-team/registry-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    wt = Path.home() / ".a-team" / "worktrees" / branch.replace("/", "-")
    wt.parent.mkdir(parents=True, exist_ok=True)
    r = _git("worktree", "add", "-q", "-b", branch, str(wt), f"origin/{base}", cwd=top)
    if r.returncode != 0:
        raise RegistryError(f"git worktree add failed: {r.stderr.strip()[:300]}")
    landed = False
    try:
        (wt / rel).write_bytes(payload)
        _git("add", str(rel), cwd=wt)
        if _git("diff", "--cached", "--quiet", cwd=wt).returncode == 0:
            return  # nothing changed
        cmd = " ".join(shlex.quote(a) for a in ["a-team", *sys.argv[1:]])
        msg = f"{_summary(old, new)}\n\nWritten by `{cmd}` on {socket.gethostname()}.\n"
        for step in (("commit", "-q", "-m", msg), ("push", "-q", "-u", "origin", branch)):
            r = _git(*step, cwd=wt)
            if r.returncode != 0:
                raise RegistryError(f"git {step[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
        if shutil.which("land"):
            r = subprocess.run(["land"], cwd=wt, capture_output=True, text=True, timeout=400)
            out = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                raise RegistryError(f"land failed, the change is on branch {branch}: {out[-400:]}")
            for line in out.splitlines():
                _say(line)
        else:
            r = _git("push", "-q", "origin", f"HEAD:{base}", cwd=wt)
            if r.returncode != 0:
                raise RegistryError(f"push to {base} failed, the change is on branch {branch}: "
                                    f"{r.stderr.strip()[:300]}")
        landed = True
        _git("merge", "-q", "--ff-only", f"origin/{base}", cwd=top)
        _git("fetch", "-q", "origin", cwd=top)
        _git("merge", "-q", "--ff-only", f"origin/{base}", cwd=top)
        _git("push", "-q", "origin", "--delete", branch, cwd=wt)
        _say(f"{_summary(old, new)}: committed and landed on {base}")
        if not shutil.which("land"):
            pull_hosts(top, hosts)
    finally:
        _git("worktree", "remove", "--force", str(wt), cwd=top)
        if landed:
            _git("branch", "-D", branch, cwd=top)


def _home_relative(top: Path) -> str | None:
    try:
        return "~/" + str(top.relative_to(Path.home()))
    except ValueError:
        return None


def pull_hosts(top: Path, hosts: dict) -> None:
    """Fast-forward the same checkout (same path under $HOME) on every host.
    A host that is asleep or unreachable is reported and skipped."""
    rel = _home_relative(top)
    if not rel:
        return
    for key, alias in sorted(hosts.items()):
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", str(alias),
                            f"git -C {rel} pull -q --ff-only"],
                           capture_output=True, text=True, timeout=60)
        _say(f"{key}: pulled {rel}" if r.returncode == 0
             else f"{key}: could not pull {rel} ({(r.stderr or r.stdout).strip()[:160]})")


def doctor(p: Path, settings: dict, hosts: dict) -> list[tuple[str, str]]:
    """(level, message) rows: level is ok, warn or fail."""
    rows: list[tuple[str, str]] = []
    bad = check_source(p, settings)
    if bad:
        rows.append(("fail", bad))
    b = backing(p)
    if not b:
        if not bad:
            rows.append(("ok", f"{p} is a plain file (no git backing configured)"))
        return rows
    top, rel = b
    rows.append(("ok", f"{p} -> {top / rel}"))
    if _git("fetch", "-q", "origin", cwd=top, timeout=30).returncode != 0:
        rows.append(("warn", f"could not fetch {top}; freshness unknown"))
        return rows
    base = _default_branch(top)
    head = _git("rev-parse", "HEAD", cwd=top).stdout.strip()
    origin = _git("rev-parse", f"origin/{base}", cwd=top).stdout.strip()
    behind = _git("rev-list", "--count", f"HEAD..origin/{base}", cwd=top).stdout.strip()
    rows.append(("ok", f"{top} is at origin/{base}") if behind == "0"
                else ("warn", f"{top} is {behind} commit(s) behind origin/{base}: "
                              f"git -C {top} pull --ff-only"))
    if _git("status", "--porcelain", "--", str(rel), cwd=top).stdout.strip():
        rows.append(("fail", f"{top / rel} has uncommitted edits; make them in a worktree instead"))
    rel_top = _home_relative(top)
    for key, alias in sorted(hosts.items()):
        if not rel_top:
            break
        script = (f"readlink ~/.config/a-team/agents.toml || echo NOT-A-LINK; "
                  f"git -C {rel_top} rev-parse HEAD")
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", str(alias), script],
                           capture_output=True, text=True, timeout=30)
        lines = r.stdout.split()
        if r.returncode != 0 or len(lines) < 2:
            rows.append(("warn", f"{key}: unreachable or no checkout at {rel_top}"))
            continue
        link, rhead = lines[0], lines[1]
        if link == "NOT-A-LINK":
            rows.append(("fail", f"{key}: ~/.config/a-team/agents.toml is not a symlink"))
        elif not link.endswith(rel_top[1:] + "/" + str(rel)):
            rows.append(("fail", f"{key}: ~/.config/a-team/agents.toml points at {link}"))
        else:
            rows.append(("ok", f"{key}: links to {link}"))
        rows.append(("ok", f"{key}: {rel_top} is at origin/{base}") if rhead == origin
                    else ("warn", f"{key}: {rel_top} is not at origin/{base} "
                                  f"({rhead[:7]} vs {origin[:7]})"))
    if head != origin and behind == "0":
        rows.append(("warn", f"{top} has commits not on origin/{base}"))
    return rows
