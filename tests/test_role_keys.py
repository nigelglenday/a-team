"""The instruction-layer manifest keys (role, customer, skills, model) and the inherits check.

    ~/.local/pipx/venvs/a-team/bin/python -m unittest discover -s tests -v

Toolkit instruction-layers plan, 2026-11-16: `a-team new` writes the four keys, every
registry rewrite keeps them, doctor warns on a missing role, and a start runs
`inherits --check <id>` first. A plain-file registry under a temp HOME, so writes go
straight to the file.
"""

import os
import stat
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from a_team import cli, config, spawn

KEYS = ("role", "customer", "skills", "model")

REG = """# header comment that must survive
[settings]
default_host = "local"

[[agent]]
name = "Preload-Builder"
path = "{work}"
id = "preload-builder"
harness = "claude"
category = "Atlas"
group = "deal/preload"
role = "associate"
customer = "preload"
skills = ["atlas-activity", "atlas-demo-video"]
model = "sonnet"

[[agent]]
name = "Legacy"
path = "{work}"
category = "Atlas"

[[agent]]
name = "Horse"
path = "{work}"
id = "horse"
harness = "claude"
category = "Personal"
role = "personal"
customer = ""
skills = []
model = "default"
"""


class _Registry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name).resolve()
        self.home = t
        self.work = t / "work"
        self.work.mkdir()
        self.reg = t / "agents.toml"
        self.reg.write_text(REG.format(work=self.work))
        # PATH without any real `inherits`, so only the fakes below are found.
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(t), "A_TEAM_CONFIG": str(self.reg),
            "PATH": "/usr/bin:/bin", "A_TEAM_LOCAL_TMUX": "0",
        })
        self.env.start()
        self.runner = CliRunner()

    def tearDown(self) -> None:
        self.env.stop()
        self._tmp.cleanup()

    def raw(self) -> list[dict]:
        return tomllib.loads(self.reg.read_text())["agent"]

    def entry(self, aid: str) -> dict:
        return next(a for a in self.raw() if a.get("id") == aid)

    def a_team(self, *args):
        return self.runner.invoke(cli.cli, list(args), catch_exceptions=False)


class New(_Registry):
    def test_role_is_required(self) -> None:
        r = self.a_team("new", "Fresh", str(self.work / "fresh"))
        self.assertEqual(r.exit_code, 2, r.output)
        self.assertIn("--role is required", r.output)
        self.assertNotIn("Fresh", [a["name"] for a in self.raw()])
        self.assertFalse((self.work / "fresh").exists())  # nothing scaffolded

    def test_role_outside_the_choices_is_refused(self) -> None:
        r = self.a_team("new", "Fresh", str(self.work), "--role", "intern")
        self.assertEqual(r.exit_code, 2)
        self.assertNotIn("Fresh", [a["name"] for a in self.raw()])

    def test_writes_the_four_keys_with_registry_defaults(self) -> None:
        r = self.a_team("new", "Fresh", str(self.work / "fresh"), "--role", "backoffice")
        self.assertEqual(r.exit_code, 0, r.output)
        a = self.entry("fresh")
        self.assertEqual({k: a[k] for k in KEYS},
                         {"role": "backoffice", "customer": "", "skills": [], "model": "default"})
        self.assertEqual(list(a)[-4:], list(KEYS))  # written after the rest, as the registry does

    def test_customer_and_model_flags(self) -> None:
        r = self.a_team("new", "Acme", str(self.work / "acme"), "--role", "associate",
                        "--customer", "acme-corp", "--model", "opus")
        self.assertEqual(r.exit_code, 0, r.output)
        a = self.entry("acme")
        self.assertEqual((a["customer"], a["model"], a["skills"]), ("acme-corp", "opus", []))

    def test_sibling_inherits_role_customer_and_model(self) -> None:
        r = self.a_team("new", "Preload-Redesign", str(self.work / "pr"), "--sibling", "Preload-Builder")
        self.assertEqual(r.exit_code, 0, r.output)
        a = self.entry("preload-redesign")
        self.assertEqual((a["role"], a["customer"], a["model"]), ("associate", "preload", "sonnet"))
        self.assertEqual(a["skills"], [])  # extra skills are per agent, not inherited
        self.assertEqual(a["parent"], "preload-builder")

    def test_sibling_flags_win_over_the_parent(self) -> None:
        r = self.a_team("new", "Preload-Side", str(self.work / "ps"), "--sibling", "Preload-Builder",
                        "--role", "sidekick", "--model", "default")
        self.assertEqual(r.exit_code, 0, r.output)
        a = self.entry("preload-side")
        self.assertEqual((a["role"], a["customer"], a["model"]), ("sidekick", "preload", "default"))

    def test_sibling_of_a_parent_without_a_role_still_needs_one(self) -> None:
        r = self.a_team("new", "Legacy-2", str(self.work / "l2"), "--sibling", "Legacy")
        self.assertEqual(r.exit_code, 2)
        self.assertIn("Legacy has none to inherit", r.output)


class RoundTrip(_Registry):
    """Every path that rewrites agents.toml keeps the four keys, values and order."""

    def assert_kept(self) -> None:
        a = self.entry("preload-builder")
        self.assertEqual(a["role"], "associate")
        self.assertEqual(a["customer"], "preload")
        self.assertEqual(a["skills"], ["atlas-activity", "atlas-demo-video"])
        self.assertEqual(a["model"], "sonnet")
        keys = [k for k in a if k in KEYS]
        self.assertEqual(keys, list(KEYS))
        h = self.entry("horse")
        self.assertEqual({k: h[k] for k in KEYS},
                         {"role": "personal", "customer": "", "skills": [], "model": "default"})
        self.assertTrue(self.reg.read_text().startswith("# header comment that must survive"))

    def test_set(self) -> None:
        r = self.a_team("set", "Preload-Builder", "--purpose", "Builds Preload's atlas",
                        "--group", "deal/preload-2", "--boot", "--account", "preload")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assert_kept()
        self.assertEqual(self.entry("preload-builder")["purpose"], "Builds Preload's atlas")

    def test_set_on_another_agent(self) -> None:
        self.assertEqual(self.a_team("set", "Horse", "--alias", "pony").exit_code, 0)
        self.assert_kept()

    def test_archive_and_unarchive(self) -> None:
        self.assertEqual(self.a_team("archive", "Preload-Builder").exit_code, 0)
        self.assert_kept()
        self.assertEqual(self.a_team("unarchive", "Preload-Builder").exit_code, 0)
        self.assert_kept()

    def test_update_agent(self) -> None:
        config.update_agent("Preload-Builder", new_name="Preload-Builder-2", new_category="Work")
        a = self.entry("preload-builder")
        self.assertEqual(a["name"], "Preload-Builder-2")
        config.update_agent("Preload-Builder-2", new_name="Preload-Builder")
        self.assert_kept()

    def test_add_and_remove_another_agent(self) -> None:
        self.assertEqual(self.a_team("here", "Other").exit_code, 0)
        self.assert_kept()
        self.assertEqual(self.a_team("rm", "Other").exit_code, 0)
        self.assert_kept()

    def test_settings_write(self) -> None:
        config.set_setting("default_parent", str(self.work))
        self.assert_kept()

    def test_migrate_apply(self) -> None:
        report = config.migrate_registry(apply=True)
        self.assertEqual([c[0] for c in report["changes"]], ["Legacy"])
        self.assert_kept()
        legacy = self.entry("legacy")
        self.assertEqual(legacy["harness"], "claude")
        self.assertNotIn("session", legacy)  # in-memory defaults stay unwritten

    def test_grants_fix(self) -> None:
        config.set_fields("Preload-Builder", account="preload")
        self.assertEqual(self.a_team("grants", "--fix").exit_code, 0)
        self.assert_kept()
        self.assertTrue(self.entry("preload-builder")["mcp"].endswith("/preload.json"))

    def test_render_for_the_git_backed_path(self) -> None:
        # registry_git.save writes through the same _render; check it directly.
        data = tomllib.loads(self.reg.read_text())
        data["agent"][0]["boot"] = True
        out = tomllib.loads(config._render(data, self.reg.read_text()).decode())
        a = out["agent"][0]
        self.assertEqual([k for k in a if k in KEYS], list(KEYS))
        self.assertEqual(a["skills"], ["atlas-activity", "atlas-demo-video"])

    def test_sync_reads_and_leaves_the_registry_alone(self) -> None:
        config.set_fields("Horse", boot=True)
        before = self.reg.read_text()
        r = self.a_team("sync")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertEqual(self.reg.read_text(), before)
        self.assertTrue((self.home / ".config/session-boot/sessions.tsv").exists())

    def test_ls_json_and_resolve_carry_the_keys(self) -> None:
        import json
        r = self.a_team("resolve", "Preload-Builder", "--json")
        rec = json.loads(r.output)
        self.assertEqual(rec["skills"], ["atlas-activity", "atlas-demo-video"])
        self.assertEqual(rec["role"], "associate")


class Doctor(_Registry):
    def test_missing_role_warns_but_does_not_fail(self) -> None:
        r = self.a_team("doctor")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("WARN  Legacy: no role", r.output)
        self.assertNotIn("Horse: no role", r.output)

    def test_unknown_role_warns(self) -> None:
        config.set_fields("Horse", role="pilot")
        rows = config.role_problems(config.load_agents())
        self.assertIn(("warn", "Horse: role 'pilot' is not one of sidekick, associate, backoffice, personal"), rows)

    def test_archived_entries_are_not_reported(self) -> None:
        config.set_status("Legacy", "archived")
        self.assertEqual(config.role_problems(config.load_agents()),
                         [("ok", "every active agent has a role")])


def _fake_inherits(folder: Path, code: int, text: str = "Horse: no role in the registry") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "inherits"
    p.write_text(f"#!/bin/sh\necho \"$@\" > \"{folder}/args\"\necho '{text}'\nexit {code}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


class InheritsCheck(_Registry):
    def on_path(self, code: int) -> Path:
        d = self.home / "bin"
        _fake_inherits(d, code)
        os.environ["PATH"] = f"{d}:/usr/bin:/bin"
        return d

    def test_exit_1_stops_with_its_output(self) -> None:
        d = self.on_path(1)
        with self.assertRaises(spawn.InheritsCheckFailed) as cm:
            spawn.inherits_check("horse")
        self.assertIn("Horse: no role in the registry", str(cm.exception))
        self.assertEqual((d / "args").read_text().strip(), "--check horse")

    def test_exit_0_and_2_let_it_start(self) -> None:
        self.on_path(0)
        spawn.inherits_check("horse")
        self.on_path(2)
        spawn.inherits_check("horse")

    def test_toolkit_fallback_path(self) -> None:
        _fake_inherits(self.home / "agents/toolkit/bin", 1)
        with self.assertRaises(spawn.InheritsCheckFailed):
            spawn.inherits_check("horse")

    def test_not_installed_is_skipped(self) -> None:
        spawn.inherits_check("horse")  # nothing on PATH, no toolkit under HOME

    def test_remote_runs_on_that_host(self) -> None:
        host = mock.Mock(is_remote=True, key="server")
        host.run.return_value = subprocess.CompletedProcess([], 1, "Bookkeeper: no role\n", "")
        with mock.patch.object(spawn._hosts, "get", return_value=host):
            with self.assertRaises(spawn.InheritsCheckFailed) as cm:
                spawn.inherits_check("bookkeeper", "server")
        script = host.run.call_args[0][0]
        self.assertIn("inherits --check bookkeeper", script)
        self.assertIn("$HOME/agents/toolkit/bin/inherits", script)
        self.assertIn("on server", str(cm.exception))

    def test_remote_unreachable_is_skipped(self) -> None:
        host = mock.Mock(is_remote=True, key="server")
        host.run.side_effect = subprocess.TimeoutExpired("ssh", 60)
        with mock.patch.object(spawn._hosts, "get", return_value=host):
            spawn.inherits_check("bookkeeper", "server")

    def test_scratch_is_not_checked(self) -> None:
        self.assertIsNone(config.inherits_id({"id": "2026-11-16_x", "category": "Scratch"}))
        self.assertEqual(config.inherits_id({"id": "horse", "category": "Personal"}), "horse")

    def _start(self, *args):
        term = mock.Mock()
        with mock.patch("a_team.terminals.resolve", return_value=term), \
             mock.patch("a_team.harness.Harness.is_available", return_value=True), \
             mock.patch.object(spawn, "tmux_sessions", return_value=[]), \
             mock.patch.object(spawn.time, "sleep"):
            r = self.a_team(*args)
        return r, term

    def test_open_stops_before_any_window(self) -> None:
        self.on_path(1)
        r, term = self._start("open", "Horse")
        self.assertEqual(r.exit_code, 1)
        self.assertIn("Horse: no role in the registry", r.output)
        term.open.assert_not_called()

    def test_open_starts_when_the_check_passes(self) -> None:
        self.on_path(0)
        r, term = self._start("open", "Horse")
        self.assertEqual(r.exit_code, 0, r.output)
        term.open.assert_called_once()

    def test_direct_shortcut_stops_too(self) -> None:
        self.on_path(1)
        r, term = self._start("Horse")
        self.assertEqual(r.exit_code, 1)
        term.open.assert_not_called()

    def test_all_starts_the_rest_and_exits_1(self) -> None:
        config.set_fields("Horse", boot=True)
        config.set_fields("Preload-Builder", boot=True)
        d = self.home / "bin"
        d.mkdir()
        # Fails for horse only.
        (d / "inherits").write_text('#!/bin/sh\n[ "$2" = horse ] && { echo "Horse: stale"; exit 1; }\nexit 0\n')
        (d / "inherits").chmod(0o755)
        os.environ["PATH"] = f"{d}:/usr/bin:/bin"
        r, term = self._start("--no-splash", "all")
        self.assertEqual(r.exit_code, 1, r.output)
        self.assertIn("Horse: stale", r.output)
        self.assertEqual(term.open.call_count, 1)  # Preload-Builder still started


if __name__ == "__main__":
    unittest.main()
