"""Desks and `a-team signal`.

No real cmux, tmux or settings file is touched: subprocess calls are faked,
the registry is a throwaway file via A_TEAM_CONFIG, and state paths point at
a temporary folder.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from a_team import cli, config, desks, notify, terminals


def _cp(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class FakeCmux:
    """Stands in for subprocess.run against the cmux CLI and records argv."""

    def __init__(self, workspaces="", groups="[]"):
        self.calls: list[list[str]] = []
        self.workspaces = workspaces
        self.groups = groups
        self._n = 20

    def __call__(self, argv, **kw):
        self.calls.append(list(argv[1:]))
        sub = argv[1:]
        if sub[:2] == ["workspace", "list"]:
            return _cp(self.workspaces)
        if sub[:2] == ["workspace-group", "list"]:
            return _cp(self.groups)
        if sub[:2] == ["workspace-group", "create"]:
            return _cp("OK workspace_group:7\n")
        if sub[:1] == ["new-workspace"]:
            self._n += 1
            return _cp(f"OK workspace:{self._n}\n")
        if sub[:1] in (["new-split"], ["workspace-action"], ["notify"]) \
                or sub[:2] in (["workspace", "close"], ["workspace-group", "ungroup"]):
            return _cp("OK")
        raise AssertionError(f"unexpected cmux call {argv}")

    def sub(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


AGENTS = [
    {"id": "client-a-associate", "name": "Client-A Associate", "path": "/work/client-a",
     "host": "local", "session": "client-a-associate"},
    {"id": "researcher", "name": "Researcher", "path": "/work/research",
     "host": "local", "session": "researcher"},
    {"id": "builder", "name": "Builder", "path": "/work/client-a/build",
     "host": "local", "session": "builder"},
    {"id": "ops", "name": "Ops", "path": "/work/ops", "host": "local", "session": "ops"},
]

DESKS = desks.parse([
    {"name": "Client-A", "group": "Clients", "color": "Blue", "pin": True,
     "agents": ["Client-A Associate", "researcher", "Builder"]},
    {"name": "Ops", "group": "Back office", "agents": ["Ops"]},
])


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("A_TEAM_CONFIG")
        self.cfg = Path(self._tmp.name) / "agents.toml"
        os.environ["A_TEAM_CONFIG"] = str(self.cfg)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("A_TEAM_CONFIG", None)
        else:
            os.environ["A_TEAM_CONFIG"] = self._prev
        self._tmp.cleanup()


class DeskParsing(RegistryTest):
    def test_loads_from_registry(self):
        self.cfg.write_text(
            '[[agent]]\nname = "Ops"\npath = "/tmp"\n\n'
            '[[desk]]\nname = "Ops desk"\nagents = ["Ops"]\ncolor = "Teal"\n')
        (d,) = desks.load()
        self.assertEqual(d, {"name": "Ops desk", "agents": ["Ops"], "group": None,
                             "color": "Teal", "pin": False})

    def test_no_desks_is_empty(self):
        self.cfg.write_text('[[agent]]\nname = "Ops"\npath = "/tmp"\n')
        self.assertEqual(desks.load(), [])

    def test_rejects_bad_tables(self):
        for bad in ([{"agents": ["Ops"]}],
                    [{"name": "X", "agents": []}],
                    [{"name": "X", "agents": "Ops"}],
                    [{"name": "X", "agents": ["Ops"], "pin": "yes"}],
                    [{"name": "X", "agents": ["Ops"]}, {"name": "x", "agents": ["Ops"]}]):
            with self.assertRaises(ValueError):
                desks.parse(bad)

    def test_missing_agents_listed(self):
        d = desks.parse([{"name": "D", "agents": ["Ops", "Ghost", "Nobody"]}])
        self.assertEqual(desks.missing(d, AGENTS), ["Ghost", "Nobody"])

    def test_desk_for_matches_name_or_id(self):
        self.assertEqual(desks.desk_for(AGENTS[1], DESKS)["name"], "Client-A")
        self.assertEqual(desks.desk_for(AGENTS[3], DESKS)["name"], "Ops")


class DeskPlan(RegistryTest):
    def test_plan_lines(self):
        self.assertEqual(desks.plan_lines(DESKS), [
            "  Clients",
            "    Client-A: Client-A Associate | researcher | Builder [Blue] pinned",
            "  Back office",
            "    Ops: Ops",
        ])

    def _registry(self, desk_block):
        self.cfg.write_text(
            '[[agent]]\nid = "ops"\nname = "Ops"\npath = "/tmp"\ngroup = "backoffice"\n\n'
            '[[agent]]\nid = "builder"\nname = "Builder"\npath = "/tmp"\ngroup = "backoffice"\n\n'
            + desk_block)

    def test_layout_dry_run_prints_desks_for_cmux(self):
        self._registry('[[desk]]\nname = "Shop"\nagents = ["Ops"]\n')
        r = CliRunner().invoke(cli.cli, ["--no-splash", "layout", "--dry-run",
                                         "--terminal", "cmux"])
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("Shop: Ops", r.output)
        # Builder is not on a desk, so it still gets a workspace of its own.
        self.assertIn("backoffice: Builder", r.output)

    def test_layout_without_desks_is_unchanged(self):
        self._registry("")
        r = CliRunner().invoke(cli.cli, ["--no-splash", "layout", "--dry-run",
                                         "--terminal", "cmux"])
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertNotIn("Desks", r.output)
        self.assertIn("backoffice: Ops, Builder", r.output)

    def test_ghostty_ignores_desks(self):
        self._registry('[[desk]]\nname = "Shop"\nagents = ["Ops"]\n')
        r = CliRunner().invoke(cli.cli, ["--no-splash", "layout", "--dry-run",
                                         "--terminal", "ghostty"])
        self.assertNotIn("Shop", r.output)
        self.assertIn("backoffice: Ops, Builder", r.output)

    def test_missing_agent_is_an_error(self):
        self._registry('[[desk]]\nname = "Shop"\nagents = ["Ops", "Ghost"]\n')
        r = CliRunner().invoke(cli.cli, ["--no-splash", "layout", "--dry-run",
                                         "--terminal", "cmux"])
        self.assertEqual(r.exit_code, 1)
        self.assertIn("Ghost", r.output)


class DeskBuild(unittest.TestCase):
    def test_build_argv(self):
        fake = FakeCmux(
            workspaces=("  workspace:1  Client-A\n  workspace:2  Researcher\n"
                        "  workspace:3  Unrelated\n"),
            groups=json.dumps({"groups": [{"name": "Clients", "ref": "workspace_group:2"},
                                          {"name": "Other", "ref": "workspace_group:3"}]}))
        cm = terminals.Cmux(binary="/bin/cmux")
        with mock.patch.object(terminals.subprocess, "run", fake), \
                mock.patch.object(desks._hosts, "local_tmux", return_value="/usr/bin/tmux"):
            desks.build(cm, DESKS, AGENTS)
        closed = [c[2] for c in fake.sub("workspace", "close")]
        self.assertEqual(closed, ["workspace:2", "workspace:1"])
        self.assertEqual([c[2] for c in fake.sub("workspace-group", "ungroup")],
                         ["workspace_group:2"])
        self.assertEqual(len(fake.sub("workspace-group", "create")), 2)
        first = fake.sub("new-workspace")[0]
        self.assertEqual(first[:3], ["new-workspace", "--name", "Client-A"])
        cmd = first[first.index("--command") + 1]
        self.assertEqual(cmd, "/bin/bash -c 'exec /usr/bin/tmux attach -t client-a-associate'")
        splits = fake.sub("new-split")
        self.assertEqual([s[1] for s in splits], ["right", "down"])
        self.assertIn("attach -t researcher", splits[0][-1])
        actions = [c[-1] if c[-2] != "--color" else "color" for c in fake.sub("workspace-action")]
        self.assertEqual(actions, ["color", "pin"])

    def test_remote_pane_uses_reconnecting_attach(self):
        remote = {"id": "ops", "name": "Ops", "host": "server", "session": "ops"}
        server = desks._hosts.Host(key="server", label="server", ssh_alias="myserver")
        with mock.patch.object(desks._hosts, "get", return_value=server):
            cmd = desks.pane_command(remote)
        self.assertTrue(cmd.startswith("/bin/bash -c "))
        self.assertIn("mosh myserver", cmd)
        self.assertIn("attach -t ops", cmd)


class Detection(unittest.TestCase):
    def test_tmux_session(self):
        self.assertEqual(notify.detect(AGENTS, session="researcher")["name"], "Researcher")

    def test_parallel_session_suffix(self):
        self.assertEqual(notify.detect(AGENTS, session="builder-2")["name"], "Builder")

    def test_agent_flag_by_name_or_id(self):
        self.assertEqual(notify.detect(AGENTS, ref="ops")["name"], "Ops")
        self.assertEqual(notify.detect(AGENTS, ref="client-a associate")["id"],
                         "client-a-associate")

    def test_cwd_picks_deepest_path(self):
        with mock.patch.object(notify.os.path, "realpath", side_effect=lambda p: p):
            self.assertEqual(notify.detect(AGENTS, cwd="/work/client-a/build/src")["name"],
                             "Builder")
            self.assertEqual(notify.detect(AGENTS, cwd="/work/client-a")["name"],
                             "Client-A Associate")
            self.assertIsNone(notify.detect(AGENTS, cwd="/elsewhere"))

    def test_unknown_session_falls_back_to_cwd(self):
        with mock.patch.object(notify.os.path, "realpath", side_effect=lambda p: p):
            hit = notify.detect(AGENTS, session="something-else", cwd="/work/ops")
        self.assertEqual(hit["name"], "Ops")


class RateRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state" / "signal.json"

    def tearDown(self):
        self._tmp.cleanup()

    def ok(self, agent, event, kind="", now=0.0):
        return notify.rate_ok(agent, event, kind, now=now, path=self.path)[0]

    def test_one_done_per_minute_per_agent(self):
        self.assertTrue(self.ok("a", "done", now=1000))
        self.assertFalse(self.ok("a", "done", now=1030))
        self.assertTrue(self.ok("b", "done", now=1030))
        self.assertTrue(self.ok("a", "done", now=1061))

    def test_idle_prompt_after_done_is_skipped(self):
        self.ok("a", "done", now=1000)
        self.assertFalse(self.ok("a", "needs-input", "idle_prompt", now=1060))
        self.assertTrue(self.ok("a", "needs-input", "permission_prompt", now=1060))
        self.assertTrue(self.ok("a", "needs-input", "idle_prompt", now=1601))

    def test_needs_input_is_not_rate_limited(self):
        self.assertTrue(self.ok("a", "needs-input", now=1))
        self.assertTrue(self.ok("a", "needs-input", now=2))

    def test_bodies(self):
        import time
        t = time.mktime((2026, 1, 1, 16, 32, 0, 0, 0, -1))
        self.assertEqual(notify.body_for("done", now=t), "done at 4:32 PM")
        self.assertEqual(notify.body_for("needs-input", "  approve\n this "),
                         "needs you: approve this")
        self.assertEqual(notify.body_for("needs-input"), "needs you")


class Send(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.patches = [
            mock.patch.object(notify, "STATE_FILE", tmp / "signal.json"),
            mock.patch.object(notify, "LOG_FILE", tmp / "signal.log"),
            mock.patch.object(notify, "OFF_FILE", tmp / "signal-off"),
        ]
        for p in self.patches:
            p.start()
        self.off = tmp / "signal-off"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def send(self, fake, event="done", **kw):
        cm = terminals.Cmux(binary="/bin/cmux")
        with mock.patch.object(terminals.subprocess, "run", fake):
            return notify.send(event, agents=AGENTS, desks=DESKS, cmux=cm, **kw)

    def test_marks_the_desk(self):
        fake = FakeCmux(workspaces="  workspace:4  Client-A\n  workspace:5  Ops\n")
        ok, _ = self.send(fake, "needs-input", text="approve?", session="builder")
        self.assertTrue(ok)
        (n,) = fake.sub("notify")
        self.assertEqual(n, ["notify", "--workspace", "workspace:4", "--title", "Builder",
                             "--body", "needs you: approve?", "--desktop", "false"])

    def test_second_done_is_rate_limited(self):
        fake = FakeCmux(workspaces="  workspace:5  Ops\n")
        self.assertTrue(self.send(fake, ref="ops")[0])
        self.assertFalse(self.send(fake, ref="ops")[0])
        self.assertEqual(len(fake.sub("notify")), 1)

    def test_off_switch(self):
        self.off.touch()
        fake = FakeCmux()
        ok, why = self.send(fake, ref="ops")
        self.assertFalse(ok)
        self.assertIn("off", why)
        self.assertEqual(fake.calls, [])

    def test_unknown_agent_does_nothing(self):
        fake = FakeCmux()
        self.assertFalse(self.send(fake, ref="nobody")[0])
        self.assertEqual(fake.calls, [])

    def test_missing_workspace_is_reported(self):
        ok, why = self.send(FakeCmux(workspaces="  workspace:1  Other\n"), ref="ops")
        self.assertFalse(ok)
        self.assertIn("no cmux workspace", why)

    def test_password_file_used_and_kept_off_argv(self):
        pw = Path(self._tmp.name) / "socket-password"
        pw.write_text("s3cret\n")
        seen = []

        def run(argv, **kw):
            seen.append((argv, kw["env"]))
            return _cp("  workspace:5  Ops\n")

        env = {k: v for k, v in os.environ.items() if k != "CMUX_SOCKET_PASSWORD"}
        with mock.patch.object(terminals, "CMUX_PASSWORD_FILE", str(pw)), \
                mock.patch.dict(os.environ, env, clear=True):
            self.send(run, ref="ops")
        for argv, e in seen:
            self.assertEqual(e.get("CMUX_SOCKET_PASSWORD"), "s3cret")
            self.assertNotIn("s3cret", " ".join(argv))


class Install(unittest.TestCase):
    def test_merge_adds_once_and_keeps_others(self):
        settings = {"model": "x", "hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": "other-hook"}]}]}}
        hooks = notify.hook_config("a-team signal")
        merged, changed = notify.merge_hooks(settings, hooks)
        self.assertTrue(changed)
        self.assertEqual(merged["model"], "x")
        cmds = [h["command"] for e in merged["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(cmds, ["other-hook", "a-team signal done"])
        self.assertEqual(merged["hooks"]["Notification"][0]["hooks"][0]["command"],
                         "a-team signal needs-input")
        again, changed = notify.merge_hooks(merged, hooks)
        self.assertFalse(changed)
        self.assertEqual(again, merged)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)  # input untouched

    def test_install_prints_without_writing(self):
        with mock.patch.object(cli.Path, "home", side_effect=AssertionError("no writes")):
            r = CliRunner().invoke(cli.cli, ["--no-splash", "signal", "install"])
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertIn("signal done", r.output)
        self.assertIn("signal needs-input", r.output)

    def test_install_via_forwards_over_ssh(self):
        r = CliRunner().invoke(cli.cli, ["--no-splash", "signal", "install", "--via", "laptop"])
        self.assertIn("ssh -o ConnectTimeout=5 laptop a-team signal --agent", r.output)

    def test_hook_reads_payload_from_stdin(self):
        with mock.patch.object(notify, "send", return_value=(True, "notified")) as send:
            r = CliRunner().invoke(cli.cli, ["--no-splash", "signal", "needs-input"],
                                   input=json.dumps({"message": "Claude needs permission",
                                                     "notification_type": "permission_prompt"}))
        self.assertEqual(r.exit_code, 0, r.output)
        send.assert_called_once_with("needs-input", text="Claude needs permission",
                                     kind="permission_prompt", ref=None)


if __name__ == "__main__":
    unittest.main()
