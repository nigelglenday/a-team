"""Session colors: `a-team color`, the color fields in records, and the cmux workspace color.

    ~/.local/pipx/venvs/a-team/bin/python -m unittest discover -s tests -v

a-team reads the toolkit's session-colors table rather than keeping its own copy. A temp
registry and a temp table under a temp HOME.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from a_team import cli, colors

REG = """[settings]
default_host = "local"

[[agent]]
id = "kratos-builder"
name = "Kratos-Builder"
path = "/tmp"
harness = "claude"

[[agent]]
id = "rmc-associate"
name = "RMC-Associate"
path = "/tmp"
harness = "claude"
color = "Magenta"

[[agent]]
id = "strategy"
name = "Strategy"
path = "/tmp"
harness = "claude"
"""

TABLE = "# match\ttint\taccent\nrmc\t#1a2d1f\t#6BBF7A\nkratos\t#2a2035\t#A78BDA\n*\t#262624\t#8A8F98\n"


class Colors(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name).resolve()
        self.reg = t / "agents.toml"
        self.reg.write_text(REG)
        self.table = t / "session-colors.tsv"
        self.table.write_text(TABLE)
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(t), "A_TEAM_CONFIG": str(self.reg), "SESSION_COLORS": str(self.table)})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self._tmp.cleanup()

    def a_team(self, *args):
        return CliRunner().invoke(cli.cli, list(args), catch_exceptions=False)

    def test_color_prints_tint_and_accent(self) -> None:
        r = self.a_team("color", "Kratos-Builder")
        self.assertEqual(r.exit_code, 0, r.output)
        self.assertEqual(r.output.strip(), "#2a2035 #A78BDA")

    def test_unmatched_agent_gets_the_catch_all(self) -> None:
        r = self.a_team("color", "strategy", "--json")
        self.assertEqual(json.loads(r.output)["accent"], "#8A8F98")

    def test_record_carries_the_colors(self) -> None:
        rec = json.loads(self.a_team("resolve", "rmc-associate", "--json").output)
        self.assertEqual((rec["tint"], rec["accent"]), ("#1a2d1f", "#6BBF7A"))

    def test_workspace_color_prefers_the_registry_override(self) -> None:
        self.assertEqual(colors.workspace_color({"id": "rmc-associate", "name": "RMC-Associate",
                                                 "color": "Magenta"}), "Magenta")
        self.assertEqual(colors.workspace_color({"id": "kratos-builder", "name": "Kratos-Builder"}),
                         "#A78BDA")

    def test_no_table_means_no_color(self) -> None:
        self.table.unlink()
        self.assertIsNone(colors.workspace_color({"id": "kratos-builder", "name": "Kratos-Builder"}))
        self.assertEqual(self.a_team("color", "Kratos-Builder").exit_code, 1)


if __name__ == "__main__":
    unittest.main()
