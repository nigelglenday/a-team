"""Terminal backends: selection, fallback, and the cmux command line.

No terminal is ever opened: every subprocess call is mocked, and the registry
is a throwaway file via A_TEAM_CONFIG.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a_team import config, spawn, terminals


def _cp(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class FakeCmux:
    """Stands in for subprocess.run against the cmux CLI and records argv."""

    def __init__(self, workspaces="", ping=_cp("PONG")):
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self.workspaces = workspaces
        self.ping = ping

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.envs.append(kw.get("env") or {})
        sub = argv[1:]
        if sub[:1] == ["ping"]:
            return self.ping
        if sub[:2] == ["workspace", "list"]:
            return _cp(self.workspaces)
        if sub[:2] == ["workspace", "select"]:
            return _cp("OK")
        if sub[:2] == ["workspace-group", "create"]:
            return _cp("OK workspace_group:7\n")
        if sub[:1] == ["new-workspace"]:
            return _cp("OK workspace:12\n")
        if sub[:1] == ["workspace-action"]:
            return _cp("OK")
        raise AssertionError(f"unexpected cmux call {argv}")

    def sub(self, name):
        return [c[1:] for c in self.calls if c[1] == name]


class Selection(unittest.TestCase):
    def setUp(self):
        self.warnings: list[str] = []

    def resolve(self, override=None, settings=None):
        return terminals.resolve(override, settings=settings or {},
                                 warn=self.warnings.append)

    def test_default_is_ghostty(self):
        self.assertIsInstance(self.resolve(), terminals.Ghostty)
        self.assertEqual(self.warnings, [])

    def test_setting_picks_cmux(self):
        with mock.patch.object(terminals.Cmux, "available", return_value=(True, "")):
            t = self.resolve(settings={"terminal": "cmux"})
        self.assertIsInstance(t, terminals.Cmux)
        self.assertEqual(self.warnings, [])

    def test_flag_overrides_setting(self):
        t = self.resolve("ghostty", settings={"terminal": "cmux"})
        self.assertIsInstance(t, terminals.Ghostty)

    def test_unavailable_falls_back_with_one_line(self):
        with mock.patch.object(terminals.Cmux, "available",
                               return_value=(False, "cmux refused the connection")):
            t = self.resolve("cmux")
        self.assertIsInstance(t, terminals.Ghostty)
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("refused", self.warnings[0])

    def test_unknown_name_falls_back(self):
        t = self.resolve(settings={"terminal": "nope"})
        self.assertIsInstance(t, terminals.Ghostty)
        self.assertEqual(len(self.warnings), 1)

    def test_every_backend_has_the_interface(self):
        for name, cls in terminals.TERMINALS.items():
            self.assertEqual(cls.name, name)
            for attr in ("available", "open"):
                self.assertTrue(callable(getattr(cls, attr)))


class CmuxAvailability(unittest.TestCase):
    def setUp(self):
        self.t = terminals.Cmux(binary=__file__)  # any existing path

    def test_access_denied_is_reported_with_the_fix(self):
        fake = FakeCmux(ping=_cp("", "Error: Access denied: caller not started by cmux", 1))
        with mock.patch.object(terminals.subprocess, "run", fake):
            ok, why = self.t.available()
        self.assertFalse(ok)
        self.assertIn("CMUX_SOCKET_PASSWORD", why)
        self.assertIn("inside cmux", why)

    def test_missing_binary(self):
        ok, why = terminals.Cmux(binary="/nonexistent/cmux").available()
        self.assertFalse(ok)
        self.assertIn("not found", why)

    def test_ping_ok_and_quiet(self):
        fake = FakeCmux()
        with mock.patch.object(terminals.subprocess, "run", fake):
            ok, _ = self.t.available()
        self.assertTrue(ok)
        self.assertEqual(fake.envs[0].get("CMUX_QUIET"), "1")

    def test_password_env_setting_is_passed_in_env_not_argv(self):
        fake = FakeCmux()
        t = terminals.Cmux(binary=__file__, password_env="MY_CMUX_PW")
        with mock.patch.dict(os.environ, {"MY_CMUX_PW": "s3cret"}), \
                mock.patch.object(terminals.subprocess, "run", fake):
            t.available()
        self.assertEqual(fake.envs[0].get("CMUX_SOCKET_PASSWORD"), "s3cret")
        self.assertNotIn("s3cret", " ".join(fake.calls[0]))


class CmuxOpen(unittest.TestCase):
    def open(self, fake, title="Agent One", command="echo hi", **kw):
        t = terminals.Cmux(binary="/bin/cmux")
        with mock.patch.object(terminals.subprocess, "run", fake):
            t.open(title, command, **kw)

    def test_new_workspace_argv(self):
        fake = FakeCmux(workspaces="  workspace:1  Other\n")
        self.open(fake)
        (args,) = fake.sub("new-workspace")
        self.assertEqual(args[:3], ["new-workspace", "--name", "Agent One"])
        i = args.index("--command")
        self.assertEqual(args[i + 1], "/bin/bash -c 'echo hi'")
        self.assertIn("--focus", args)
        self.assertNotIn("--group", args)
        self.assertEqual(fake.sub("workspace-action"), [])
        self.assertEqual(fake.calls[0][0], "/bin/cmux")

    def test_group_is_created_with_idempotency_key(self):
        fake = FakeCmux()
        self.open(fake, group="Back Office")
        (g,) = fake.sub("workspace-group")
        self.assertEqual(g, ["workspace-group", "create", "--name", "Back Office",
                             "--idempotency-key", "a-team-back-office"])
        (args,) = fake.sub("new-workspace")
        i = args.index("--group")
        self.assertEqual(args[i:i + 4],
                         ["--group", "workspace_group:7", "--group-placement", "end"])

    def test_color_only_when_set(self):
        fake = FakeCmux()
        self.open(fake, color="Teal")
        (a,) = fake.sub("workspace-action")
        self.assertEqual(a, ["workspace-action", "--workspace", "workspace:12",
                             "--action", "set-color", "--color", "Teal"])

    def test_existing_workspace_is_selected_not_duplicated(self):
        fake = FakeCmux(workspaces=(
            "  workspace:3  Agent One [claude] (selected)\n"
            "* workspace:4  Agent Two *\n"))
        self.open(fake, group="deal", color="Red")
        self.assertEqual(fake.sub("new-workspace"), [])
        self.assertEqual(fake.sub("workspace-group"), [])
        self.assertEqual(fake.sub("workspace"),
                         [["workspace", "list"], ["workspace", "select", "workspace:3"]])

    def test_list_parsing_strips_decorations(self):
        got = terminals.parse_workspace_list(
            "workspace:1  Plain\n"
            "  workspace:2  With Space [x] (selected)\n"
            "* workspace:3  Starred *\n"
            "noise line\n")
        self.assertEqual(got, {"Plain": "workspace:1", "With Space": "workspace:2",
                               "Starred": "workspace:3"})

    def test_access_denied_during_open_raises(self):
        fake = FakeCmux()
        fake.workspaces = ""
        with mock.patch.object(terminals.subprocess, "run",
                               return_value=_cp("", "Access denied", 1)):
            with self.assertRaises(RuntimeError):
                terminals.Cmux(binary="/bin/cmux").open("x", "true")


class ShellTraps(unittest.TestCase):
    def test_leading_equals_is_quoted(self):
        self.assertEqual(terminals.zsh_safe_quote("=name"), "'=name'")
        self.assertEqual(terminals.zsh_safe_quote("plain"), "plain")
        self.assertEqual(terminals.zsh_safe_quote("two words"), "'two words'")

    def test_wrapped_command_survives_bash(self):
        # zsh would turn the bare =x into a command path; through the wrapper
        # bash sees it as a plain word.
        shell = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/sh"
        cmd = "printf '%s|' \"two words\" =x"
        out = subprocess.run([shell, "-c", terminals.bash_wrapped(cmd)],
                             capture_output=True, text=True).stdout
        self.assertEqual(out, "two words|=x|")

    def test_session_starting_with_equals_is_quoted_in_attach(self):
        seen = {}

        class Rec(terminals.Terminal):
            name = "rec"

            def available(self):
                return True, ""

            def open(self, title, command, **kw):
                seen.update(title=title, command=command, **kw)

        spawn.attach_window("=odd", "local", title="Odd One", group="deal",
                            color="Blue", terminal=Rec())
        self.assertIn("-s '=odd'", seen["command"])
        self.assertEqual(seen["title"], "Odd One")
        self.assertEqual((seen["group"], seen["color"]), ("deal", "Blue"))


class SpawnUsesBackend(unittest.TestCase):
    """open_agent hands the built command to whichever backend it is given."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("A_TEAM_CONFIG")
        os.environ["A_TEAM_CONFIG"] = str(Path(self._tmp.name) / "agents.toml")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("A_TEAM_CONFIG", None)
        else:
            os.environ["A_TEAM_CONFIG"] = self._prev
        self._tmp.cleanup()

    def test_open_agent_routes_to_backend(self):
        got = {}

        class Rec(terminals.Terminal):
            name = "rec"

            def available(self):
                return True, ""

            def open(self, title, command, **kw):
                got.update(title=title, command=command, **kw)

        with mock.patch.object(spawn._harness.Harness, "is_available", return_value=True):
            spawn.open_agent("Agent One", self._tmp.name, session="agent-one",
                             group="deal", color="Teal", terminal=Rec())
        self.assertEqual(got["title"], "Agent One")
        self.assertEqual((got["group"], got["color"], got["tab"]), ("deal", "Teal", False))
        self.assertIn("agent-one", got["command"])

    def test_no_terminal_uses_setting_default_ghostty(self):
        config.set_setting("terminal", None)
        self.assertIsInstance(terminals.resolve(warn=lambda m: None), terminals.Ghostty)


if __name__ == "__main__":
    unittest.main()
