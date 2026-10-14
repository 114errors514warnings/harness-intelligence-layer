"""Git recency must be a hint that can never break retrieval (roadmap §4).

The signal is optional by contract: a non-git tree, a missing ``git``, or any error
must yield an empty set so the caller behaves exactly as before.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from harness_intelligence import history


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )


class GitRecencyTests(unittest.TestCase):
    def setUp(self) -> None:
        history.reset_cache()

    def tearDown(self) -> None:
        history.reset_cache()

    def test_non_git_tree_yields_no_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "auth.py").write_text("x = 1\n", encoding="utf-8")
            self.assertEqual(history.recent_paths(tmp), frozenset())

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_recent_commit_paths_are_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            _git(root, "config", "user.email", "t@example.com")
            _git(root, "config", "user.name", "Test")
            (root / "auth.py").write_text("def validate():\n    return 1\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "initial")
            history.reset_cache()
            paths = history.recent_paths(root)
            self.assertIn("auth.py", paths)
            self.assertIn("docs/notes.md", paths)

    def test_the_result_is_cached_and_resettable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(history.recent_paths(tmp), frozenset())
            self.assertIn(str(Path(tmp).resolve()), history._cache)
            history.reset_cache()
            self.assertNotIn(str(Path(tmp).resolve()), history._cache)


if __name__ == "__main__":
    unittest.main()
