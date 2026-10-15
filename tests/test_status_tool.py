"""The status tool must find projects, stay read-only, and render a report."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "hil_status.py"
_spec = importlib.util.spec_from_file_location("hil_status", TOOL_PATH)
assert _spec and _spec.loader
hil_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hil_status)


class StatusToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "demo"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "app.py").write_text(
            "def load_index(root):\n    return root\n", encoding="utf-8"
        )
        from harness_intelligence.indexer import index_project

        index_project(self.project)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_a_project_with_hil_is_found(self) -> None:
        # Temporary directories are skipped by default, so opt back in for the test.
        found = hil_status.find_projects([self.root], 3, exclude_temp=False)
        self.assertEqual(found, [self.project.resolve()])

    def test_inspect_reports_the_index_read_only(self) -> None:
        facts = hil_status.inspect(self.project)
        self.assertTrue(facts["indexed"])
        self.assertEqual(facts["files"], 1)
        self.assertGreaterEqual(facts["symbols"], 1)
        self.assertTrue(facts["fresh"])
        self.assertEqual(facts["issues"], [])

    def test_render_has_the_expected_sections(self) -> None:
        text = hil_status.render(hil_status.inspect(self.project))
        for marker in ("# HIL 运行状态报告", "## 索引", "## 工程记忆", "## 检索连通性自检", "## 结论"):
            self.assertIn(marker, text)

    def test_a_hil_dir_without_an_index_is_flagged(self) -> None:
        bare = self.root / "bare"
        (bare / ".hil").mkdir(parents=True)
        facts = hil_status.inspect(bare)
        self.assertFalse(facts["indexed"])
        self.assertTrue(any("尚未建立索引" in item for item in facts["issues"]))

    def test_inspect_does_not_write_the_index(self) -> None:
        index_path = self.project / ".hil" / "index.json"
        before = index_path.read_bytes()
        hil_status.inspect(self.project)
        self.assertEqual(index_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
