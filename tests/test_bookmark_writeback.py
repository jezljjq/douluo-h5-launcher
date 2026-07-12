from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from douluo_launcher.direct_link_refresh import (
    BookmarkBatchItem,
    BookmarkUrlUpdater,
    BookmarkWriteContext,
    calculate_chromium_bookmarks_checksum,
)


class BookmarkWritebackTests(unittest.TestCase):
    def test_preview_reports_unique_missing_and_conflicting_paths_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bookmark_file, _payload = self._write_fixture(root, conflict=True)
            updater = self._updater(bookmark_file, root / "backups", dry_run=True)
            original = bookmark_file.read_bytes()

            unique = updater.preview("账号/存钻/beta")
            missing = updater.preview("账号/存钻/missing")
            conflict = updater.preview("账号/存钻/alpha")

            self.assertEqual(unique.status, "bookmark_match_unique")
            self.assertEqual(missing.status, "bookmark_not_found")
            self.assertEqual(conflict.status, "bookmark_conflict")
            self.assertEqual(bookmark_file.read_bytes(), original)

    def _payload(self, *, conflict: bool = False) -> dict[str, object]:
        target_nodes = [
            {
                "date_added": "1",
                "guid": "guid-alpha",
                "id": "30",
                "name": "alpha",
                "type": "url",
                "url": "https://old.example/alpha",
                "unknown": {"keep": True},
            }
        ]
        if conflict:
            target_nodes.append(
                {
                    "date_added": "2",
                    "guid": "guid-alpha-2",
                    "id": "31",
                    "name": "alpha",
                    "type": "url",
                    "url": "https://old.example/alpha-2",
                }
            )
        return {
            "checksum": "old-checksum",
            "roots": {
                "bookmark_bar": {
                    "children": [
                        {
                            "children": [
                                {
                                    "children": [
                                        *target_nodes,
                                        {
                                            "date_added": "3",
                                            "guid": "guid-beta",
                                            "id": "32",
                                            "name": "beta",
                                            "type": "url",
                                            "url": "https://old.example/beta",
                                        },
                                    ],
                                    "date_added": "4",
                                    "id": "20",
                                    "name": "存钻",
                                    "type": "folder",
                                },
                                {
                                    "children": [
                                        {
                                            "date_added": "5",
                                            "id": "40",
                                            "name": "alpha",
                                            "type": "url",
                                            "url": "https://old.example/other-alpha",
                                        }
                                    ],
                                    "date_added": "6",
                                    "id": "21",
                                    "name": "其它",
                                    "type": "folder",
                                },
                            ],
                            "date_added": "7",
                            "guid": "guid-account-root",
                            "id": "10",
                            "name": "账号",
                            "type": "folder",
                        }
                    ],
                    "date_added": "8",
                    "id": "1",
                    "name": "收藏栏",
                    "type": "folder",
                },
                "other": {
                    "children": [],
                    "date_added": "9",
                    "id": "2",
                    "name": "其它收藏夹",
                    "type": "folder",
                },
            },
            "version": 1,
            "unknown_top": "keep-me",
        }

    def _write_fixture(self, base: Path, *, conflict: bool = False) -> tuple[Path, dict[str, object]]:
        payload = self._payload(conflict=conflict)
        path = base / "Bookmarks"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path, payload

    def _updater(
        self,
        bookmark_file: Path,
        backup_dir: Path,
        *,
        dry_run: bool = False,
        browser_running: bool = False,
        validator=None,
        logs: list[str] | None = None,
    ) -> BookmarkUrlUpdater:
        context = BookmarkWriteContext(
            bookmark_file=bookmark_file,
            browser="Edge",
            profile="Default",
            root_path="roots/bookmark_bar/children/0",
            root_name="账号",
            root_guid="guid-account-root",
            root_parent_path="roots/bookmark_bar",
            allow_create_root=True,
        )
        return BookmarkUrlUpdater(
            context=context,
            backups_dir=backup_dir,
            dry_run=dry_run,
            browser_running_checker=lambda _browser: browser_running,
            temp_json_validator=validator,
            log=(logs.append if logs is not None else None),
        )

    def _read(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _target(self, payload: dict[str, object], folder: str = "存钻", name: str = "alpha") -> dict[str, object]:
        root = payload["roots"]["bookmark_bar"]["children"][0]
        folder_node = next(node for node in root["children"] if node["name"] == folder)
        return next(node for node in folder_node["children"] if node["name"] == name)

    def test_full_path_uniquely_updates_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _payload = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            result = updater.update("账号/存钻/alpha", "https://new.example/login?token=fake")

            self.assertEqual(result.status, "bookmark_success")
            self.assertEqual(self._target(self._read(path))["url"], "https://new.example/login?token=fake")

    def test_omitted_root_path_uniquely_updates_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _payload = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            result = updater.update("存钻/alpha", "https://new.example/alpha")

            self.assertEqual(result.status, "bookmark_success")
            self.assertEqual(self._target(self._read(path))["url"], "https://new.example/alpha")

    def test_windows_separator_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _payload = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            result = updater.update(r"账号\存钻\alpha", "https://new.example/alpha")

            self.assertEqual(result.status, "bookmark_success")

    def test_missing_path_creates_final_bookmark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            result = updater.update("存钻/missing", "https://new.example/missing")

            self.assertEqual(result.status, "bookmark_success")
            self.assertEqual(self._target(self._read(path), "存钻", "missing")["url"], "https://new.example/missing")
            self.assertNotEqual(self._read(path)["checksum"], original["checksum"])

    def test_missing_nested_folders_and_chinese_account_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _original = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            result = updater.update("账号/新区/子组/测试A9", "https://new.example/chinese")

            self.assertEqual(result.status, "bookmark_success")
            root = self._read(path)["roots"]["bookmark_bar"]["children"][0]
            new_area = next(node for node in root["children"] if node["name"] == "新区")
            subgroup = next(node for node in new_area["children"] if node["name"] == "子组")
            target = next(node for node in subgroup["children"] if node["name"] == "测试A9")
            self.assertEqual(target["url"], "https://new.example/chinese")

    def test_duplicate_full_path_is_conflict_and_does_not_modify_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base, conflict=True)
            updater = self._updater(path, base / "backups")

            result = updater.update("存钻/alpha", "https://new.example/alpha")

            self.assertEqual(result.status, "bookmark_conflict")
            self.assertEqual(self._read(path), original)

    def test_same_name_in_other_folder_is_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _payload = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            updater.update("存钻/alpha", "https://new.example/alpha")
            updated = self._read(path)

            self.assertEqual(self._target(updated, "其它", "alpha")["url"], "https://old.example/other-alpha")

    def test_only_target_url_and_checksum_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)
            expected = copy.deepcopy(original)
            self._target(expected)["url"] = "https://new.example/alpha"
            updater = self._updater(path, base / "backups")

            updater.update("存钻/alpha", "https://new.example/alpha")
            updated = self._read(path)
            expected["checksum"] = calculate_chromium_bookmarks_checksum(expected)

            self.assertEqual(updated, expected)
            self.assertNotEqual(updated["checksum"], "old-checksum")

    def test_same_batch_creates_only_one_original_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)
            updater = self._updater(path, base / "backups")

            first = updater.update("存钻/alpha", "https://new.example/alpha")
            second = updater.update("存钻/beta", "https://new.example/beta")

            backups = list((base / "backups").glob("Bookmarks_*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(first.backup_path, second.backup_path)
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), original)

    def test_temp_json_validation_failure_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)

            def fail_validation(_path: Path) -> None:
                raise ValueError("fixture validation failed")

            updater = self._updater(path, base / "backups", validator=fail_validation)
            result = updater.update("存钻/alpha", "https://new.example/alpha")

            self.assertEqual(result.status, "bookmark_write_failed")
            self.assertEqual(self._read(path), original)
            self.assertEqual(list(base.glob("*.tmp")), [])

    def test_browser_running_blocks_real_write_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)
            updater = self._updater(path, base / "backups", browser_running=True)

            result = updater.update("存钻/alpha", "https://new.example/alpha")

            self.assertEqual(result.status, "bookmark_browser_running")
            self.assertEqual(self._read(path), original)
            self.assertFalse((base / "backups").exists())

    def test_dry_run_does_not_modify_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)
            updater = self._updater(path, base / "backups", dry_run=True)

            result = updater.update("存钻/alpha", "https://new.example/alpha")

            self.assertEqual(result.status, "bookmark_update_skipped")
            self.assertEqual(self._read(path), original)

    def test_logs_do_not_contain_direct_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _payload = self._write_fixture(base)
            logs: list[str] = []
            updater = self._updater(path, base / "backups", logs=logs)
            direct_url = "https://new.example/login?token=fake-secret&sign=fake-sign"

            updater.update("存钻/alpha", direct_url)

            joined = "\n".join(logs)
            self.assertNotIn(direct_url, joined)
            self.assertNotIn("fake-secret", joined)
            self.assertNotIn("fake-sign", joined)

    def test_batch_updates_and_creates_once_with_same_leaf_in_different_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, original = self._write_fixture(base)
            updater = self._updater(path, base / "backups")
            result = updater.apply_batch([
                BookmarkBatchItem("key-beta", "账号/存钻/beta", "https://new.example/beta"),
                BookmarkBatchItem("key-one", "账号/第一层/1", "https://new.example/one"),
                BookmarkBatchItem("key-two", "账号/第二层/1", "https://new.example/two"),
            ])
            self.assertEqual(result.status, "bookmark_success")
            self.assertEqual((result.updated, result.created, result.conflicts), (1, 2, 0))
            backups = list((base / "backups").glob("Bookmarks_*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), original)

    def test_mapping_guid_missing_blocks_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _original = self._write_fixture(base)
            first = self._updater(path, base / "backups")
            self.assertEqual(first.apply_batch([
                BookmarkBatchItem("key-missing", "账号/存钻/missing", "https://new.example/one")
            ]).status, "bookmark_success")
            payload = self._read(path)
            folder = payload["roots"]["bookmark_bar"]["children"][0]["children"][0]
            folder["children"] = [node for node in folder["children"] if node["name"] != "missing"]
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            second = self._updater(path, base / "backups-2")
            second.backups_dir = base / "backups"
            result = second.apply_batch([
                BookmarkBatchItem("key-missing", "账号/存钻/missing", "https://new.example/two")
            ])
            self.assertEqual(result.status, "bookmark_conflict")
            self.assertFalse(any(node["name"] == "missing" for node in self._read(path)["roots"]["bookmark_bar"]["children"][0]["children"][0]["children"]))

    def test_external_hash_change_aborts_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, _original = self._write_fixture(base)
            def external_change(_temp: Path) -> None:
                path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            updater = self._updater(path, base / "backups", validator=external_change)
            result = updater.apply_batch([
                BookmarkBatchItem("key-beta", "账号/存钻/beta", "https://new.example/beta")
            ])
            self.assertEqual(result.status, "bookmark_write_failed")
            self.assertIn("外部修改", result.message)
            self.assertEqual(self._target(self._read(path), name="beta")["url"], "https://old.example/beta")

    def test_saved_guid_recovers_after_structural_index_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, payload = self._write_fixture(base)
            payload["roots"]["bookmark_bar"]["children"].insert(0, {"type": "folder", "name": "其它", "guid": "other", "id": "99", "children": []})
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = self._updater(path, base / "backups").apply_batch([BookmarkBatchItem("beta", "账号/存钻/beta", "https://new.example/beta")])
            self.assertEqual((result.status, result.root_guid, result.root_path), ("bookmark_success", "guid-account-root", "roots/bookmark_bar/children/1"))

    def test_no_guid_recovers_unique_name_after_index_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, payload = self._write_fixture(base)
            payload["roots"]["bookmark_bar"]["children"].insert(0, {"type": "folder", "name": "其它", "guid": "other", "id": "99", "children": []})
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            updater = self._updater(path, base / "backups")
            updater.context = replace(updater.context, root_guid="", root_path="roots/bookmark_bar/children/0")
            result = updater.apply_batch([BookmarkBatchItem("beta", "账号/存钻/beta", "https://new.example/beta")])
            self.assertEqual((result.status, result.root_guid, result.root_path), ("bookmark_success", "guid-account-root", "roots/bookmark_bar/children/1"))

    def test_missing_root_requires_confirmation_and_creates_under_explicit_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, payload = self._write_fixture(base)
            payload["roots"]["bookmark_bar"]["children"] = []
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            updater = self._updater(path, base / "backups")
            updater.context = replace(updater.context, root_guid="")
            original = path.read_bytes()
            cancelled = updater.apply_batch([BookmarkBatchItem("one", "账号/第一层/1", "https://one")], root_create_confirm=lambda _name: False)
            self.assertEqual(cancelled.status, "bookmark_update_skipped")
            self.assertEqual(path.read_bytes(), original)
            created = updater.apply_batch([BookmarkBatchItem("one", "账号/第一层/1", "https://one")], root_create_confirm=lambda _name: True)
            self.assertEqual((created.status, created.updated, created.created, created.conflicts), ("bookmark_success", 0, 1, 0))

    def test_duplicate_named_roots_are_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, payload = self._write_fixture(base)
            duplicate = copy.deepcopy(payload["roots"]["bookmark_bar"]["children"][0])
            duplicate["guid"] = "duplicate-root"
            payload["roots"]["other"]["children"].append(duplicate)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            updater = self._updater(path, base / "backups")
            updater.context = replace(updater.context, root_guid="missing-guid")
            original = path.read_bytes()
            result = updater.apply_batch([BookmarkBatchItem("beta", "账号/存钻/beta", "https://new")])
            self.assertEqual(result.status, "bookmark_conflict")
            self.assertEqual(path.read_bytes(), original)

    def test_fifty_new_then_second_sync_updates_same_guids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            path, payload = self._write_fixture(base)
            payload["roots"]["bookmark_bar"]["children"][0]["children"] = []
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            items = [BookmarkBatchItem(f"key-{i}", f"账号/第{i % 4 + 1}层/{i}", f"https://first/{i}") for i in range(50)]
            first = self._updater(path, base / "backups")
            first_result = first.apply_batch(items)
            self.assertEqual((first_result.updated, first_result.created, first_result.conflicts), (0, 50, 0))
            mappings = json.loads((base / "bookmark_mappings.json").read_text(encoding="utf-8"))["accounts"]
            second = self._updater(path, base / "backups")
            second_result = second.apply_batch([replace(item, direct_url=item.direct_url.replace("first", "second")) for item in items])
            self.assertEqual((second_result.updated, second_result.created, second_result.conflicts), (50, 0, 0))
            self.assertEqual(json.loads((base / "bookmark_mappings.json").read_text(encoding="utf-8"))["accounts"], mappings)


if __name__ == "__main__":
    unittest.main()
