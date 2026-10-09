"""The denylist gate is what keeps a global HIL from indexing abandoned trees."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness_intelligence.policy import (
    DENYLIST_ENV,
    DENYLIST_FILE_ENV,
    denied_paths,
    deny_reason,
    ensure_allowed,
)


class DenylistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.allowed = self.root / "allowed"
        self.denied = self.root / "denied"
        self.allowed.mkdir()
        self.denied.mkdir()
        self.file = self.root / "denied_projects.txt"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _env(self, **values):
        # Isolate every test from the machine's real config and environment.
        base = {DENYLIST_ENV: "", DENYLIST_FILE_ENV: str(self.file)}
        base.update(values)
        return mock.patch.dict(os.environ, base, clear=False)

    def test_an_allowed_project_passes(self) -> None:
        with self._env():
            self.assertIsNone(deny_reason(self.allowed))
            ensure_allowed(self.allowed)  # must not raise

    def test_a_denied_project_is_refused(self) -> None:
        self.file.write_text(str(self.denied) + "\n", encoding="utf-8")
        with self._env():
            self.assertEqual(deny_reason(self.denied), str(self.denied))
            with self.assertRaises(ValueError) as caught:
                ensure_allowed(self.denied)
            self.assertIn("denylist", str(caught.exception))

    def test_a_subdirectory_of_a_denied_project_is_refused(self) -> None:
        self.file.write_text(str(self.denied) + "\n", encoding="utf-8")
        (self.denied / "pkg").mkdir()
        with self._env():
            self.assertIsNotNone(deny_reason(self.denied / "pkg"))

    def test_a_sibling_sharing_a_prefix_is_not_refused(self) -> None:
        # "denied-extra" starts with "denied" as a string but is not under it.
        sibling = self.root / "denied-extra"
        sibling.mkdir()
        self.file.write_text(str(self.denied) + "\n", encoding="utf-8")
        with self._env():
            self.assertIsNone(deny_reason(sibling))

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        self.file.write_text(
            f"# abandoned projects\n\n{self.denied}\n", encoding="utf-8"
        )
        with self._env():
            self.assertEqual(denied_paths(), [self.denied])

    def test_the_environment_variable_also_denies(self) -> None:
        with self._env(**{DENYLIST_ENV: str(self.denied)}):
            self.assertIsNotNone(deny_reason(self.denied))

    def test_environment_paths_can_be_separated_by_the_platform_separator(self) -> None:
        other = self.root / "other"
        other.mkdir()
        with self._env(**{DENYLIST_ENV: os.pathsep.join([str(self.denied), str(other)])}):
            self.assertEqual({path for path in denied_paths()}, {self.denied, other})

    def test_a_missing_denylist_file_denies_nothing(self) -> None:
        with self._env():
            self.assertIsNone(deny_reason(self.denied))

    def test_the_reason_names_the_offending_entry(self) -> None:
        self.file.write_text(str(self.denied) + "\n", encoding="utf-8")
        with self._env():
            self.assertEqual(deny_reason(self.denied), str(self.denied))


if __name__ == "__main__":
    unittest.main()
