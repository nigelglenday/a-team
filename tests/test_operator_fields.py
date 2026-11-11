"""Operator's registry fields: `a-team set --alias --purpose --readback --voice` and the doctor checks.

    ~/.local/pipx/venvs/a-team/bin/python -m unittest discover -s tests -v

Toolkit spec docs/specs/2026-11-10-operator/spec.md, assertion 14. A plain-file registry under
a temp HOME (no git backing), so writes go straight to the file.
"""

import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from a_team import cli, config

REG = """[settings]
default_host = "local"

[[agent]]
id = "preload-atlas-associate"
name = "Preload-Builder"
path = "/tmp"
harness = "claude"

[[agent]]
id = "strategy"
name = "Strategy"
path = "/tmp"
harness = "claude"
aliases = ["the strategist"]
"""


class Fields(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name).resolve()
        self.reg = t / "agents.toml"
        self.reg.write_text(REG)
        self.env = mock.patch.dict(os.environ, {"HOME": str(t), "A_TEAM_CONFIG": str(self.reg)})
        self.env.start()
        self.run_ = CliRunner()

    def tearDown(self) -> None:
        self.env.stop()
        self._tmp.cleanup()

    def agent(self, aid: str) -> dict:
        data = tomllib.loads(self.reg.read_text())
        return next(a for a in data["agent"] if a["id"] == aid)

    def a_team(self, *args):
        return self.run_.invoke(cli.cli, list(args), catch_exceptions=False)

    def test_14_set_writes_the_four_fields(self) -> None:
        r = self.a_team("set", "Preload-Builder", "--alias", "Preload Builder", "--purpose",
                        "Builds Preload's atlas", "--readback", "full", "--voice", "voice-123")
        self.assertEqual(r.exit_code, 0, r.output)
        a = self.agent("preload-atlas-associate")
        self.assertEqual(a["aliases"], ["Preload Builder"])
        self.assertEqual(a["purpose"], "Builds Preload's atlas")
        self.assertEqual(a["readback"], "full")
        self.assertEqual(a["voice"], "voice-123")
        # the alias now resolves, as every a-team name does
        self.assertEqual(config.resolve_agent("Preload Builder")["id"], "preload-atlas-associate")

    def test_alias_adds_and_empty_clears(self) -> None:
        self.a_team("set", "strategy", "--alias", "Strat", "--alias", "the strategist")
        self.assertEqual(self.agent("strategy")["aliases"], ["the strategist", "Strat"])
        self.a_team("set", "strategy", "--alias", "")
        self.assertNotIn("aliases", self.agent("strategy"))

    def test_alias_that_names_another_agent_is_refused(self) -> None:
        r = self.a_team("set", "Preload-Builder", "--alias", "the strategist")
        self.assertEqual(r.exit_code, 1)
        self.assertNotIn("aliases", self.agent("preload-atlas-associate"))
        r = self.a_team("set", "Preload-Builder", "--alias", "Strategy")
        self.assertEqual(r.exit_code, 1)

    def test_readback_outside_the_five_is_refused_and_empty_clears(self) -> None:
        r = self.a_team("set", "strategy", "--readback", "loud")
        self.assertNotEqual(r.exit_code, 0)
        self.assertNotIn("readback", self.agent("strategy"))
        self.a_team("set", "strategy", "--readback", "changes", "--voice", "v1", "--purpose", "Runs strategy")
        self.a_team("set", "strategy", "--readback", "", "--voice", "", "--purpose", "")
        a = self.agent("strategy")
        for k in ("readback", "voice", "purpose"):
            self.assertNotIn(k, a)

    def test_14_doctor_reports_bad_readback_and_long_purpose(self) -> None:
        self.reg.write_text(REG.replace('id = "strategy"\n', 'id = "strategy"\nreadback = "loud"\n'
                            'purpose = "one two three four five six seven eight nine ten eleven twelve thirteen"\n'))
        rows = config.field_problems(config.load_agents())
        msgs = [m for lvl, m in rows if lvl == "warn"]
        self.assertTrue(any("readback 'loud'" in m and "summary, full, last, changes, nocode" in m for m in msgs), msgs)
        self.assertTrue(any("purpose has 13 words" in m for m in msgs), msgs)
        r = self.a_team("doctor")
        self.assertIn("readback 'loud'", r.output)
        self.assertIn("purpose has 13 words", r.output)

    def test_doctor_quiet_when_fields_are_valid(self) -> None:
        self.a_team("set", "strategy", "--readback", "nocode", "--purpose", "Runs the strategy binder")
        rows = config.field_problems(config.load_agents())
        self.assertEqual([lvl for lvl, _ in rows], ["ok"])


if __name__ == "__main__":
    unittest.main()
