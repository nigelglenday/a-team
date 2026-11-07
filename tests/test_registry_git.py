"""A registry kept in git: writes go through a worktree and land, never through the link.

    ~/.local/pipx/venvs/a-team/bin/python -m unittest discover -s tests -v

Each test builds a throwaway bare remote and checkout under a temp HOME, points
A_TEAM_CONFIG at a symlink into the checkout, and hides any `land` on PATH so the
no-land path (push to the default branch, fast-forward the checkout) runs.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a_team import config, registry_git

REG = """[settings]
default_host = "local"

[[agent]]
id = "alpha"
name = "Alpha"
path = "/tmp"
harness = "claude"
"""


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class GitRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name).resolve()
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(t), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_GLOBAL": "/dev/null"})
        self.env.start()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(t / "remote.git")], check=True)
        subprocess.run(["git", "clone", "-q", str(t / "remote.git"), str(t / "repo")], check=True,
                       capture_output=True)
        self.repo = t / "repo"
        (self.repo / "config").mkdir()
        (self.repo / "config" / "agents.toml").write_text(REG)
        git("add", "-A", cwd=self.repo)
        git("commit", "-qm", "registry", cwd=self.repo)
        git("push", "-q", "-u", "origin", "main", cwd=self.repo)
        git("remote", "set-head", "origin", "main", cwd=self.repo)
        self.link = t / ".config" / "a-team" / "agents.toml"
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(self.repo / "config" / "agents.toml")
        os.environ["A_TEAM_CONFIG"] = str(self.link)
        self.which = mock.patch.object(registry_git.shutil, "which", return_value=None)
        self.which.start()
        self.workdir = t / "work"
        self.workdir.mkdir()

    def tearDown(self) -> None:
        self.which.stop()
        self.env.stop()
        self._tmp.cleanup()

    def remote_file(self) -> str:
        return git("show", "main:config/agents.toml", cwd=self.repo.parent / "remote.git")

    def test_write_lands_in_git_and_keeps_the_link(self) -> None:
        config.set_fields("Alpha", group="team")
        self.assertTrue(self.link.is_symlink())
        self.assertIn('group = "team"', self.remote_file())
        self.assertIn('group = "team"', self.link.read_text())
        subject = git("log", "-1", "--format=%s", "main", cwd=self.repo.parent / "remote.git")
        self.assertEqual(subject, "registry: update Alpha\n")
        self.assertEqual(git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual(git("worktree", "list", "--porcelain", cwd=self.repo).count("worktree "), 1)

    def test_add_agent_names_it_in_the_commit(self) -> None:
        config.add_agent("Beta", str(self.workdir))
        subject = git("log", "-1", "--format=%s", "main", cwd=self.repo.parent / "remote.git")
        self.assertEqual(subject, "registry: add Beta\n")

    def test_stale_copy_is_refused_and_brought_up_to_date(self) -> None:
        other = self.repo.parent / "other"
        subprocess.run(["git", "clone", "-q", str(self.repo.parent / "remote.git"), str(other)], check=True,
                       capture_output=True)
        f = other / "config" / "agents.toml"
        f.write_text(f.read_text().replace('name = "Alpha"', 'name = "Alpha"\nboot = true'))
        git("commit", "-qam", "elsewhere", cwd=other)
        git("push", "-q", cwd=other)
        with self.assertRaises(registry_git.RegistryError):
            config.set_fields("Alpha", group="team")
        self.assertIn("boot = true", self.link.read_text())       # pulled
        self.assertNotIn("group", self.remote_file())              # nothing written
        config.set_fields("Alpha", group="team")                   # the retry works
        self.assertIn("boot = true", self.remote_file())
        self.assertIn('group = "team"', self.remote_file())

    def test_plain_file_is_refused_when_a_source_is_configured(self) -> None:
        src = self.link.resolve()
        self.link.unlink()
        self.link.write_text(REG.replace('[settings]\n', f'[settings]\nregistry_source = "{src}"\n'))
        with self.assertRaises(registry_git.RegistryError):
            config.set_fields("Alpha", group="team")
        rows = registry_git.doctor(self.link, config.load_settings(), {})
        self.assertEqual(rows[0][0], "fail")

    def test_doctor_is_clean_on_a_current_link(self) -> None:
        rows = registry_git.doctor(self.link, {}, {})
        self.assertTrue(all(level == "ok" for level, _ in rows), rows)


if __name__ == "__main__":
    unittest.main()
