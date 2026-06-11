import json
import os
import tempfile
import unittest
from pathlib import Path

from douluo_launcher.config import (
    SINGLE_LEVEL_NAME,
    BookmarkCandidate,
    find_bookmark_file_candidates,
    find_bookmark_root_candidate_by_path,
    load_accounts_from_bookmark_root,
    load_settings,
    scan_bookmark_root_candidates,
    select_bookmark_candidate_for_startup,
)


def _url(index: int) -> str:
    return f"https://7tu7tu.com/dldl?gid=1002997&pid={index}&token=BASE64TOKEN"


def _write_bookmarks(path: Path, roots: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"roots": roots}, ensure_ascii=False), encoding="utf-8")


def _url_node(name: str, index: int) -> dict[str, object]:
    return {"type": "url", "name": name, "url": _url(index)}


def _folder(name: str, children: list[dict[str, object]]) -> dict[str, object]:
    return {"type": "folder", "name": name, "children": children}


class BookmarkDiscoveryTests(unittest.TestCase):
    def test_scans_edge_default_profile1_and_chrome_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)
            for path in (
                local / "Microsoft" / "Edge" / "User Data" / "Default" / "Bookmarks",
                local / "Microsoft" / "Edge" / "User Data" / "Profile 1" / "Bookmarks",
                local / "Google" / "Chrome" / "User Data" / "Default" / "Bookmarks",
            ):
                _write_bookmarks(path, {})
            old = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(local)
            try:
                candidates = find_bookmark_file_candidates()
            finally:
                if old is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old

        labels = [(candidate.browser, candidate.profile) for candidate in candidates]
        self.assertIn(("Edge", "Default"), labels)
        self.assertIn(("Edge", "Profile 1"), labels)
        self.assertIn(("Chrome", "Default"), labels)

    def test_multiple_bookmark_candidates_do_not_silently_override_saved_path(self) -> None:
        candidates = [
            BookmarkCandidate("Edge", "Default", "C:/Edge/Default/Bookmarks"),
            BookmarkCandidate("Chrome", "Default", "C:/Chrome/Default/Bookmarks"),
        ]

        selected = select_bookmark_candidate_for_startup("D:/User/Saved/Bookmarks", candidates)

        self.assertIsNone(selected.candidate)
        self.assertEqual(selected.reason, "keep_saved")

    def test_single_candidate_can_be_selected_when_saved_path_missing(self) -> None:
        candidate = BookmarkCandidate("Edge", "Default", "C:/Edge/Default/Bookmarks")

        selected = select_bookmark_candidate_for_startup("", [candidate])

        self.assertEqual(selected.candidate, candidate)
        self.assertEqual(selected.reason, "unique_candidate")

    def test_root_name_not_account_is_detected_and_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {
                    "bookmark_bar": _folder(
                        "收藏栏",
                        [
                            _folder(
                                "斗罗大陆",
                                [
                                    _folder("第一层", [_url_node("1", 1), _url_node("2", 2)]),
                                    _folder("存钻", [_url_node("z1", 3)]),
                                ],
                            )
                        ],
                    )
                },
            )

            candidates = scan_bookmark_root_candidates(path)
            root = next(candidate for candidate in candidates if candidate.display_name == "收藏栏 / 斗罗大陆")
            accounts = load_accounts_from_bookmark_root(path, root.root_path)

        self.assertEqual(root.link_count, 3)
        self.assertEqual(root.child_group_count, 2)
        self.assertEqual(root.display_label, "收藏栏 / 斗罗大陆 - 3个账号，包含2个分组")
        self.assertEqual([account.level for account in accounts], ["第一层", "第一层", "存钻"])

    def test_direct_links_on_bookmark_bar_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {"bookmark_bar": _folder("收藏栏", [_url_node("1", 1), _url_node("2", 2), _url_node("3", 3)])},
            )

            candidates = scan_bookmark_root_candidates(path)
            direct = next(candidate for candidate in candidates if candidate.display_name == "收藏栏（直接链接）")
            accounts = load_accounts_from_bookmark_root(path, direct.root_path)

        self.assertTrue(direct.direct_links)
        self.assertEqual(direct.link_count, 3)
        self.assertEqual([account.level for account in accounts], [SINGLE_LEVEL_NAME] * 3)

    def test_direct_links_on_other_bookmarks_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {"other": _folder("其它收藏夹", [_url_node("1", 1), _url_node("2", 2)])},
            )

            candidates = scan_bookmark_root_candidates(path)
            direct = next(candidate for candidate in candidates if candidate.display_name == "其它收藏夹（直接链接）")

        self.assertTrue(direct.direct_links)
        self.assertEqual(direct.link_count, 2)

    def test_multi_level_child_directory_candidate_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {
                    "bookmark_bar": _folder(
                        "收藏栏",
                        [_folder("斗罗大陆", [_folder("第一层", [_url_node("1", 1)])])],
                    )
                },
            )

            candidates = scan_bookmark_root_candidates(path)

        self.assertTrue(any(candidate.display_name == "收藏栏 / 斗罗大陆 / 第一层" for candidate in candidates))

    def test_selecting_parent_reads_child_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {
                    "bookmark_bar": _folder(
                        "收藏栏",
                        [
                            _folder(
                                "斗罗大陆",
                                [
                                    _folder("第一层", [_url_node("1", 1)]),
                                    _folder("第二层", [_url_node("1", 2)]),
                                ],
                            )
                        ],
                    )
                },
            )
            parent = next(
                candidate for candidate in scan_bookmark_root_candidates(path)
                if candidate.display_name == "收藏栏 / 斗罗大陆"
            )

            accounts = load_accounts_from_bookmark_root(path, parent.root_path)

        self.assertEqual([account.level for account in accounts], ["第一层", "第二层"])

    def test_selecting_child_reads_only_that_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {
                    "bookmark_bar": _folder(
                        "收藏栏",
                        [
                            _folder(
                                "斗罗大陆",
                                [
                                    _folder("第一层", [_url_node("1", 1)]),
                                    _folder("存钻", [_url_node("z1", 2), _url_node("z2", 3)]),
                                ],
                            )
                        ],
                    )
                },
            )
            child = next(
                candidate for candidate in scan_bookmark_root_candidates(path)
                if candidate.display_name == "收藏栏 / 斗罗大陆 / 存钻"
            )

            accounts = load_accounts_from_bookmark_root(path, child.root_path)

        self.assertEqual([account.level for account in accounts], ["存钻", "存钻"])
        self.assertEqual([account.bookmark_title for account in accounts], ["z1", "z2"])
        self.assertEqual([account.game_window_no for account in accounts], [1, 2])

    def test_same_named_directories_are_loaded_by_root_path_not_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(
                path,
                {
                    "bookmark_bar": _folder(
                        "收藏栏",
                        [
                            _folder("账号", [_folder("存钻", [_url_node("z1", 1)])]),
                            _folder("备用", [_folder("存钻", [_url_node("z9", 9)])]),
                        ],
                    )
                },
            )
            target = next(
                candidate for candidate in scan_bookmark_root_candidates(path)
                if candidate.display_name == "收藏栏 / 备用 / 存钻"
            )

            accounts = load_accounts_from_bookmark_root(path, target.root_path)

        self.assertEqual([account.level for account in accounts], ["存钻"])
        self.assertEqual([account.bookmark_title for account in accounts], ["z9"])
        self.assertEqual([account.url for account in accounts], [_url(9)])

    def test_saved_bookmark_root_path_missing_requires_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Bookmarks"
            _write_bookmarks(path, {"bookmark_bar": _folder("收藏栏", [_folder("斗罗大陆", [_url_node("1", 1)])])})

            found = find_bookmark_root_candidate_by_path(path, "roots/bookmark_bar/children/99")

        self.assertIsNone(found)

    def test_old_root_name_setting_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "automation_settings.json"
            settings_path.write_text('{"bookmark_root_name": "账号"}', encoding="utf-8")

            settings = load_settings(settings_path)

        self.assertEqual(settings.bookmark_root_name, "账号")
        self.assertEqual(settings.bookmark_root_path, "")


if __name__ == "__main__":
    unittest.main()
