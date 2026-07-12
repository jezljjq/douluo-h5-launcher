import json
import tempfile
import unittest
from pathlib import Path

from tools.inspect_bookmarks import inspect_bookmarks, restore_bookmarks


class InspectBookmarksTests(unittest.TestCase):
    def test_preview_is_read_only_and_reports_duplicate_full_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Bookmarks"
            payload = {"roots": {"bookmark_bar": {"type": "folder", "name": "bar", "children": [
                {"type": "url", "name": "1", "guid": "a", "id": "1", "url": "https://a"},
                {"type": "url", "name": "1", "guid": "b", "id": "2", "url": "https://b"},
            ]}}}
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.read_bytes()
            report = inspect_bookmarks(path)
            self.assertEqual(report["duplicate_paths"], 1)
            self.assertEqual(path.read_bytes(), before)

    def test_restore_requires_confirmation_and_preserves_current_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current, backup = root / "Bookmarks", root / "selected.json"
            current.write_text('{"roots":{},"value":"current"}', encoding="utf-8")
            backup.write_text('{"roots":{},"value":"backup"}', encoding="utf-8")
            with self.assertRaises(PermissionError):
                restore_bookmarks(current, backup, confirmed=False)
            safety = restore_bookmarks(current, backup, confirmed=True)
            self.assertEqual(json.loads(current.read_text())["value"], "backup")
            self.assertEqual(json.loads(safety.read_text())["value"], "current")


if __name__ == "__main__":
    unittest.main()
