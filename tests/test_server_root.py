"""The default project root must never silently point at the wrong tree."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from harness_intelligence.server import _default_root


class DefaultRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_cwd = Path.cwd()
        self.previous_env = os.environ.get("HIL_PROJECT_ROOT")
        os.environ.pop("HIL_PROJECT_ROOT", None)

    def tearDown(self) -> None:
        os.chdir(self.previous_cwd)
        if self.previous_env is None:
            os.environ.pop("HIL_PROJECT_ROOT", None)
        else:
            os.environ["HIL_PROJECT_ROOT"] = self.previous_env
        self.temp.cleanup()

    def test_the_env_var_wins(self) -> None:
        os.environ["HIL_PROJECT_ROOT"] = str(self.root / "pinned")
        self.assertEqual(_default_root(), str(self.root / "pinned"))

    def test_a_project_cwd_is_used_as_the_fallback(self) -> None:
        project = self.root / "project"
        project.mkdir()
        (project / ".git").mkdir()
        os.chdir(project)
        self.assertEqual(_default_root(), str(project.resolve()))

    def test_a_non_project_cwd_is_refused_instead_of_guessed(self) -> None:
        # This is the case that used to make every project silently read whatever
        # directory the harness happened to start in.
        plain = self.root / "plain"
        plain.mkdir()
        os.chdir(plain)
        with self.assertRaises(ValueError) as caught:
            _default_root()
        self.assertIn("pass project_root explicitly", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
