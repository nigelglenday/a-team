"""Delivery 1 acceptance tests: harness adapter, stable identity, launch routing.

Runs on stdlib unittest (no pytest dependency):

    ~/.local/pipx/venvs/a-team/bin/python -m unittest discover -s tests -v

Every test points A_TEAM_CONFIG at a throwaway temp file, so the live registry
at ~/.config/a-team/agents.toml is never read or written. All agent data here is
synthetic.
"""

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from a_team import config, harness, spawn


class _TempRegistry(unittest.TestCase):
    """Base: each test gets an isolated agents.toml via A_TEAM_CONFIG."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reg = Path(self._tmp.name) / "agents.toml"
        self._prev = os.environ.get("A_TEAM_CONFIG")
        os.environ["A_TEAM_CONFIG"] = str(self.reg)
        # a real directory so add_agent's path check passes
        self.workdir = Path(self._tmp.name) / "work"
        self.workdir.mkdir()

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("A_TEAM_CONFIG", None)
        else:
            os.environ["A_TEAM_CONFIG"] = self._prev
        self._tmp.cleanup()

    def write(self, toml: str) -> None:
        self.reg.write_text(textwrap.dedent(toml))


class HarnessAdapter(unittest.TestCase):
    def test_known_harnesses(self):
        self.assertEqual(set(harness.HARNESSES), {"claude", "codex"})

    def test_default_is_claude(self):
        self.assertEqual(harness.normalize_key(None), "claude")
        self.assertEqual(harness.normalize_key(""), "claude")
        self.assertEqual(harness.get(None).key, "claude")

    def test_normalize_accepts_label_and_case(self):
        self.assertEqual(harness.normalize_key("Codex"), "codex")
        self.assertEqual(harness.normalize_key("Claude Code"), "claude")

    def test_unknown_harness_rejected(self):
        with self.assertRaises(ValueError):
            harness.normalize_key("gpt5")

    def test_launch_verbs(self):
        self.assertEqual(harness.CLAUDE.launch_command("new"), "claude")
        self.assertIn("claude --continue", harness.CLAUDE.launch_command("continue"))
        self.assertIn("claude --resume", harness.CLAUDE.launch_command("resume"))
        self.assertEqual(harness.CODEX.launch_command("new"), "codex")
        self.assertIn("codex resume --last", harness.CODEX.launch_command("continue"))
        self.assertIn("codex resume", harness.CODEX.launch_command("resume"))

    def test_config_env_vars_are_harness_specific(self):
        self.assertEqual(harness.CLAUDE.config_env_var, "CLAUDE_CONFIG_DIR")
        self.assertEqual(harness.CODEX.config_env_var, "CODEX_HOME")

    def test_env_prefix_uses_own_var_only(self):
        # A dir passed to Codex is exported as CODEX_HOME, never CLAUDE_CONFIG_DIR.
        pref = harness.CODEX.env_prefix("/some/dir")
        self.assertIn("export CODEX_HOME=", pref)
        self.assertNotIn("CLAUDE_CONFIG_DIR", pref)
        self.assertEqual(harness.CLAUDE.env_prefix(None), "")


class Identity(_TempRegistry):
    def test_legacy_entry_backfills_id_and_claude(self):
        # A pre-existing Claude-only entry has neither id nor harness.
        self.write(
            """
            [[agent]]
            name = "Legacy One"
            path = "%s"
            kind = "persistent"
            """
            % self.workdir
        )
        agents = config.load_agents_normalized()
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["id"], "legacy-one")
        self.assertEqual(agents[0]["harness"], "claude")
        # and the raw file is untouched (no implicit migration on read)
        self.assertNotIn("id =", self.reg.read_text())

    def test_add_codex_agent_persists_id_and_harness(self):
        agent = config.add_agent("Proj Dev", str(self.workdir), harness="codex")
        self.assertEqual(agent["harness"], "codex")
        self.assertEqual(agent["id"], "proj-dev")
        raw = self.reg.read_text()
        self.assertIn('harness = "codex"', raw)
        self.assertIn('id = "proj-dev"', raw)

    def test_add_defaults_to_claude(self):
        agent = config.add_agent("Plain", str(self.workdir))
        self.assertEqual(agent["harness"], "claude")

    def test_rename_preserves_id(self):
        config.add_agent("Before", str(self.workdir), harness="codex")
        before = config.resolve_agent("Before")
        config.update_agent("Before", new_name="After")
        after = config.resolve_agent("After")
        self.assertIsNotNone(after)
        self.assertEqual(after["id"], before["id"])  # inbox-stable id survives rename
        self.assertEqual(after["harness"], "codex")

    def test_duplicate_id_rejected(self):
        config.add_agent("Alpha", str(self.workdir))  # id "alpha"
        with self.assertRaises(ValueError):
            config.add_agent("Beta", str(self.workdir), agent_id="alpha")

    def test_ambiguous_name_raises(self):
        # Two legacy entries with the same name -> resolve must refuse to guess.
        self.write(
            """
            [[agent]]
            name = "Dup"
            path = "%s"
            [[agent]]
            name = "Dup"
            path = "%s"
            """
            % (self.workdir, self.workdir)
        )
        with self.assertRaises(ValueError):
            config.resolve_agent("Dup")

    def test_resolve_by_alias(self):
        self.write(
            """
            [[agent]]
            id = "the-agent"
            name = "The Agent"
            path = "%s"
            harness = "claude"
            aliases = ["ta", "agent-1"]
            """
            % self.workdir
        )
        self.assertEqual(config.resolve_agent("ta")["id"], "the-agent")
        self.assertEqual(config.resolve_agent("the-agent")["name"], "The Agent")

    def test_custom_config_path_respected(self):
        # A_TEAM_CONFIG (set in setUp) is where writes land.
        config.add_agent("Here", str(self.workdir))
        self.assertTrue(self.reg.exists())
        self.assertIn("Here", self.reg.read_text())


class ConfigDirIsolation(_TempRegistry):
    def test_no_claude_dir_leaks_to_codex(self):
        # An account rule that would resolve to a Claude dir must NOT apply to a
        # codex agent: resolve_config_dir returns None for codex.
        self.write(
            """
            [accounts]
            work = "~/.claude-work"
            [account_by_category]
            Work = "work"

            [[agent]]
            id = "c"
            name = "Codexer"
            path = "%s"
            kind = "persistent"
            harness = "codex"
            category = "Work"
            """
            % self.workdir
        )
        agent = config.resolve_agent("c")
        self.assertIsNone(config.resolve_config_dir(agent))

    def test_claude_dir_still_resolves(self):
        self.write(
            """
            [accounts]
            work = "~/.claude-work"
            [account_by_category]
            Work = "work"

            [[agent]]
            id = "cl"
            name = "Clauder"
            path = "%s"
            harness = "claude"
            category = "Work"
            """
            % self.workdir
        )
        agent = config.resolve_agent("cl")
        self.assertEqual(config.resolve_config_dir(agent), str(Path("~/.claude-work").expanduser()))


class LaunchCommand(unittest.TestCase):
    """The bash command a-team pastes into Ghostty carries the right harness."""

    def test_codex_command_never_exports_claude_var(self):
        cmd = spawn._build_command(
            "Agent", "/tmp/work", harness.CODEX, "continue", config_dir="/some/dir"
        )
        self.assertIn("codex resume --last", cmd)
        self.assertIn("CODEX_HOME=", cmd)
        self.assertNotIn("CLAUDE_CONFIG_DIR", cmd)
        self.assertIn("cd /tmp/work", cmd)

    def test_claude_command_exports_config_dir(self):
        cmd = spawn._build_command(
            "Agent", "/tmp/work", harness.CLAUDE, "new", config_dir="/acct/dir"
        )
        self.assertIn("export CLAUDE_CONFIG_DIR=/acct/dir", cmd)
        self.assertTrue(cmd.strip().endswith("claude; }"))

    def test_missing_harness_reports_setup(self):
        # Force an unavailable executable and assert an actionable error.
        fake = harness.Harness("x", "X-CLI", "definitely-not-a-real-binary-xyz",
                               None, {"new": "x", "continue": "x", "resume": "x"})
        orig = harness.HARNESSES.get("x")
        harness.HARNESSES["x"] = fake
        try:
            with self.assertRaises(RuntimeError) as cm:
                spawn.open_agent("A", "/tmp", harness="x")
            self.assertIn("not installed", str(cm.exception).lower())
        finally:
            if orig is None:
                harness.HARNESSES.pop("x", None)
            else:
                harness.HARNESSES["x"] = orig


class StatusAttribution(unittest.TestCase):
    """running_pids attributes live sessions by folder AND harness."""

    def test_same_folder_two_harnesses_not_conflated(self):
        from a_team import status

        path = "/tmp/shared"
        sessions = {path: [(101, "claude"), (202, "codex"), (103, "claude")]}
        claude_agent = {"path": path, "harness": "claude"}
        codex_agent = {"path": path, "harness": "codex"}
        self.assertEqual(sorted(status.running_pids(claude_agent, sessions)), [101, 103])
        self.assertEqual(status.running_pids(codex_agent, sessions), [202])

    def test_legacy_agent_attributes_as_claude(self):
        from a_team import status

        path = "/tmp/legacy"
        sessions = {path: [(1, "claude"), (2, "codex")]}
        legacy = {"path": path}  # no harness field
        self.assertEqual(status.running_pids(legacy, sessions), [1])

    def test_no_sessions_in_folder(self):
        from a_team import status

        self.assertEqual(status.running_pids({"path": "/nope", "harness": "codex"}, {}), [])

    def test_codex_service_subcommands_recognized(self):
        from a_team import status

        # These must be recognized as services so they are never killed as sessions.
        for sub in ("app-server", "mcp-server", "remote-control", "exec"):
            self.assertIn(sub, status._CODEX_SERVICE_SUBCMDS)


class MigrateRegistry(_TempRegistry):
    def test_dry_run_writes_nothing(self):
        self.write(
            """
            [[agent]]
            name = "Legacy"
            path = "%s"
            kind = "persistent"
            """
            % self.workdir
        )
        before = self.reg.read_text()
        report = config.migrate_registry(apply=False)
        self.assertEqual(len(report["changes"]), 1)
        self.assertIsNone(report["backup"])
        self.assertEqual(self.reg.read_text(), before)  # untouched

    def test_apply_backfills_and_preserves(self):
        self.write(
            """
            [settings]
            default_parent = "/somewhere"

            [accounts]
            work = "~/.claude-work"

            [[agent]]
            name = "Legacy One"
            path = "%s"
            kind = "persistent"
            category = "Work"
            """
            % self.workdir
        )
        report = config.migrate_registry(apply=True)
        self.assertEqual(report["changes"], [("Legacy One", "legacy-one", "claude")])
        self.assertIsNotNone(report["backup"])
        self.assertTrue(Path(report["backup"]).exists())  # backup made

        agents = config.load_agents()  # raw, post-write
        a = agents[0]
        self.assertEqual(a["id"], "legacy-one")
        self.assertEqual(a["harness"], "claude")
        self.assertEqual(a["category"], "Work")  # preserved
        self.assertEqual(a["kind"], "persistent")  # preserved
        # other tables preserved
        self.assertEqual(config.get_setting("default_parent"), "/somewhere")
        self.assertEqual(config.load_accounts().get("work"), "~/.claude-work")

    def test_apply_is_idempotent(self):
        config.add_agent("Already", str(self.workdir), harness="codex")  # has id+harness
        report = config.migrate_registry(apply=True)
        self.assertEqual(report["changes"], [])  # nothing to change
        self.assertIsNone(report["backup"])  # no backup when no changes


if __name__ == "__main__":
    unittest.main()


class HostRouting(unittest.TestCase):
    """Where an agent lives, and how that changes the launch command.

    Remote hosts are user config, so these build a Host directly rather than
    assuming any particular machine exists."""

    REMOTE = None  # set in setUp

    def setUp(self):
        from a_team import hosts
        self.REMOTE = hosts.Host(key="server", label="server (remote)", ssh_alias="myserver")

    def test_local_is_default_and_not_remote(self):
        from a_team import hosts
        self.assertEqual(hosts.normalize_key(None), "local")
        self.assertEqual(hosts.normalize_key("here"), "local")
        self.assertFalse(hosts.LOCAL.is_remote)
        self.assertTrue(hosts.LOCAL.reachable())
        self.assertTrue(self.REMOTE.is_remote)

    def test_unknown_host_rejected(self):
        from a_team import hosts
        with self.assertRaises(ValueError):
            hosts.normalize_key("definitely-not-configured")

    def test_local_launch_command_is_plain_cd(self):
        from a_team import hosts
        cmd = hosts.LOCAL.launch_command("/tmp/proj", "claude", "myid")
        self.assertEqual(cmd, "cd /tmp/proj && claude")
        self.assertNotIn("tmux", cmd)

    def test_remote_launch_uses_tmux_and_attaches(self):
        cmd = self.REMOTE.launch_command("/remote/agents/x", "claude", "myid")
        self.assertIn("tmux new-session -A -s", cmd)  # attach-or-create survives disconnect
        self.assertIn("mosh myserver", cmd)
        self.assertIn("ssh -t myserver", cmd)  # fallback present
        self.assertIn("myid", cmd)

    def test_build_command_remote_has_no_local_account_export(self):
        from a_team import harness, spawn
        cmd = spawn._build_command(
            "Agent", "/remote/path", harness.CLAUDE, "continue",
            config_dir="/local/acct", host=self.REMOTE, session="sid",
        )
        self.assertNotIn("CLAUDE_CONFIG_DIR", cmd)  # must not cross the ssh hop
        self.assertIn("tmux new-session -A -s", cmd)

    def test_build_command_local_still_exports_account(self):
        from a_team import harness, hosts, spawn
        cmd = spawn._build_command(
            "Agent", "/local/path", harness.CLAUDE, "continue",
            config_dir="/local/acct", host=hosts.LOCAL, session="sid",
        )
        self.assertIn("export CLAUDE_CONFIG_DIR=/local/acct", cmd)


class HostInRegistry(_TempRegistry):
    def test_legacy_entry_defaults_to_local(self):
        self.write('''
            [[agent]]
            name = "Old"
            path = "%s"
        ''' % self.workdir)
        self.assertEqual(config.load_agents_normalized()[0]["host"], "local")

    def test_add_local_agent_records_host(self):
        a = config.add_agent("Loc", str(self.workdir))
        self.assertEqual(a["host"], "local")
        self.assertIn('host = "local"', self.reg.read_text())

    def test_prepare_path_local_creates_when_asked(self):
        target = str(self.workdir / "made")
        out = config.prepare_path(target, "local", create=True)
        self.assertTrue(Path(out).is_dir())

    def test_hosts_table_defines_remote_hosts(self):
        from a_team import hosts
        self.write("""
            [hosts]
            server = "myserver"
        """)
        known = hosts.all_hosts()
        self.assertIn("local", known)
        self.assertIn("server", known)
        self.assertEqual(known["server"].ssh_alias, "myserver")
        self.assertTrue(known["server"].is_remote)

    def test_prepare_path_local_rejects_missing(self):
        with self.assertRaises(ValueError):
            config.prepare_path(str(self.workdir / "nope"), "local", create=False)
