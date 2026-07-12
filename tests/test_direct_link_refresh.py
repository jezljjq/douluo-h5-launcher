from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from douluo_launcher.config import AccountConfig
from douluo_launcher.direct_link_refresh import (
    AccountsStore,
    DEFAULT_CHANNEL_NAME,
    DirectLinkRefreshService,
    DirectLinkStore,
    DirectLoginFields,
    RefreshAccount,
    RefreshResult,
    RefreshSummaryWriter,
    build_client_direct_url,
    default_channel_config,
    default_refresh_data_dir,
    ensure_refresh_data_dir,
    import_accounts_from_text,
    legacy_refresh_data_dirs,
    load_channels,
    migrate_refresh_data,
    resolve_client_direct_url_for_account,
    resolve_client_direct_url_for_identity,
    summarize_results,
    update_accounts_after_result,
    write_account_url_shortcut,
    write_url_shortcut,
)


class DirectLinkRefreshTests(unittest.TestCase):
    def test_frozen_legacy_sources_never_include_repo_or_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release = root / "repo" / "dist" / "release"
            appdata = root / "appdata"
            release.mkdir(parents=True)
            executable = release / "上号器.exe"
            with patch.dict(os.environ, {
                "H5_LAUNCHER_DATA_DIR": str(appdata / "DouluoH5Launcher"),
                "H5_LAUNCHER_REFRESH_DATA_DIR": str(appdata / "DouluoH5Launcher" / "refresh_data"),
            }), patch("douluo_launcher.direct_link_refresh.sys.frozen", True, create=True), patch(
                "douluo_launcher.config.sys.frozen", True, create=True
            ), patch("douluo_launcher.config.sys.executable", str(executable)):
                sources = legacy_refresh_data_dirs(environ={"APPDATA": str(appdata)})
            self.assertIn(release / "上号器数据", sources)
            self.assertIn(appdata / "DouluoH5Launcher", sources)
            self.assertNotIn(root / "repo" / "上号器数据", sources)

    def test_frozen_default_migration_does_not_copy_repo_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            release = repo / "dist" / "release"
            appdata = root / "appdata"
            (repo / "上号器数据").mkdir(parents=True)
            release.mkdir(parents=True)
            (repo / "上号器数据" / "accounts.enc.json").write_text("repo-canary", encoding="utf-8")
            with patch.dict(os.environ, {
                "H5_LAUNCHER_DATA_DIR": str(appdata / "DouluoH5Launcher"),
                "H5_LAUNCHER_REFRESH_DATA_DIR": str(appdata / "DouluoH5Launcher" / "refresh_data"),
            }), patch("douluo_launcher.direct_link_refresh.sys.frozen", True, create=True), patch(
                "douluo_launcher.config.sys.frozen", True, create=True
            ), patch("douluo_launcher.config.sys.executable", str(release / "上号器.exe")):
                paths = ensure_refresh_data_dir()
            self.assertFalse(paths.accounts_path.exists())
            self.assertFalse(any("repo-canary" in p.read_text(encoding="utf-8", errors="ignore") for p in paths.data_dir.rglob("*") if p.is_file()))

    def test_migration_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, outside, target = root / "source", root / "outside", root / "target"
            source.mkdir()
            outside.mkdir()
            (outside / "accounts.enc.json").write_text("outside-canary", encoding="utf-8")
            link = source / "accounts.enc.json"
            try:
                link.symlink_to(outside / "accounts.enc.json")
            except OSError:
                self.skipTest("symlink creation is unavailable")
            counts = migrate_refresh_data(target, [source])
            self.assertEqual(counts, {"copied": 0, "replaced": 0, "skipped_newer": 0})
            self.assertFalse((target / "accounts.enc.json").exists())

    def test_frozen_legacy_sources_reject_release_root_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            release, outside, appdata = root / "release", root / "outside", root / "appdata"
            release.mkdir()
            outside.mkdir()
            try:
                (release / "上号器数据").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlink creation is unavailable")
            with patch("douluo_launcher.direct_link_refresh.sys.frozen", True, create=True), patch(
                "douluo_launcher.config.sys.frozen", True, create=True
            ), patch("douluo_launcher.config.sys.executable", str(release / "上号器.exe")):
                sources = legacy_refresh_data_dirs(environ={"APPDATA": str(appdata)})
            self.assertNotIn(release / "上号器数据", sources)

    def test_empty_bookmark_path_writes_only_to_flat_direct_link_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            account = RefreshAccount("alpha", "user", "password", bookmark_path="")

            target = write_account_url_shortcut(paths, account, "https://example.invalid/alpha")

            self.assertEqual(target, paths.url_dir / "alpha.url")
            self.assertTrue(target.exists())
            self.assertFalse(any(paths.grouped_url_dir.rglob("*.url")))

    def test_bookmark_path_writes_only_to_full_group_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            account = RefreshAccount("alpha", "user", "password", bookmark_path="账号/存钻/1")

            target = write_account_url_shortcut(paths, account, "https://example.invalid/alpha")

            self.assertEqual(target, paths.grouped_url_dir / "账号" / "存钻" / "1.url")
            self.assertTrue(target.exists())
            self.assertFalse((paths.url_dir / "alpha.url").exists())

    def test_group_mirror_supports_root_path_and_windows_separators(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            root_target = write_account_url_shortcut(
                paths,
                RefreshAccount("one", "u", "p", bookmark_path="账号/1"),
                "https://example.invalid/one",
            )
            nested_target = write_account_url_shortcut(
                paths,
                RefreshAccount("two", "u", "p", bookmark_path=r"账号\存钻\2"),
                "https://example.invalid/two",
            )

            self.assertEqual(root_target.relative_to(paths.data_dir).as_posix(), "分组/账号/1.url")
            self.assertEqual(nested_target.relative_to(paths.data_dir).as_posix(), "分组/账号/存钻/2.url")

    def test_group_mirror_sanitizes_each_segment_and_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            target = write_account_url_shortcut(
                paths,
                RefreshAccount("alpha", "u", "p", bookmark_path="账号/存:钻/1*"),
                "https://example.invalid/alpha",
            )

            self.assertEqual(target.relative_to(paths.data_dir).as_posix(), "分组/账号/存_钻/1_.url")
            for unsafe in ("../escape", r"账号\..\escape", r"C:\escape\1", r"\\server\share\1", "/absolute/1"):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaises(ValueError):
                        write_account_url_shortcut(
                            paths,
                            RefreshAccount("bad", "u", "p", bookmark_path=unsafe),
                            "https://example.invalid/bad",
                        )

    def test_path_change_writes_new_file_then_removes_only_previous_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            flat_account = RefreshAccount("alpha", "u", "p", bookmark_path="")
            old_target = write_account_url_shortcut(paths, flat_account, "https://example.invalid/old")
            unrelated = paths.url_dir / "unrelated.url"
            unrelated.write_text("keep", encoding="utf-8")

            grouped_account = RefreshAccount("alpha", "u", "p", bookmark_path="账号/存钻/1")
            new_target = write_account_url_shortcut(
                paths,
                grouped_account,
                "https://example.invalid/new",
                previous_url_file=old_target.relative_to(paths.data_dir).as_posix(),
            )

            self.assertTrue(new_target.exists())
            self.assertFalse(old_target.exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
            self.assertTrue(paths.grouped_url_dir.exists())

    def test_imported_account_order_is_explicit_and_not_filesystem_dependent(self) -> None:
        imported = import_accounts_from_text(
            "name,username,password,bookmark_path\n"
            "zeta,u1,p1,\n"
            "alpha,u2,p2,\n"
        )

        self.assertEqual([(account.name, account.order_index) for account in imported.accounts], [("zeta", 0), ("alpha", 1)])

    def test_accounts_store_loads_by_stable_order_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            store = AccountsStore(paths.accounts_path)
            store.protected_file.write(
                {
                    "schema_version": 1,
                    "accounts": [
                        {"name": "second", "username": "u2", "password": "p2", "order_index": 1},
                        {"name": "first", "username": "u1", "password": "p1", "order_index": 0},
                    ],
                }
            )

            loaded = store.load()

            self.assertEqual([account.name for account in loaded], ["first", "second"])

    def test_group_mirror_deduplicates_sanitized_path_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            used_paths: set[Path] = set()

            first = write_account_url_shortcut(
                paths,
                RefreshAccount("first", "u1", "p1", bookmark_path="账号/存钻/1?"),
                "https://example.invalid/first",
                used_paths=used_paths,
            )
            second = write_account_url_shortcut(
                paths,
                RefreshAccount("second", "u2", "p2", bookmark_path="账号/存钻/1*"),
                "https://example.invalid/second",
                used_paths=used_paths,
            )

            self.assertEqual(first.relative_to(paths.data_dir).as_posix(), "分组/账号/存钻/1_.url")
            self.assertEqual(second.relative_to(paths.data_dir).as_posix(), "分组/账号/存钻/1__2.url")

    def test_subset_refresh_preserves_unselected_account_sanitized_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            other = RefreshAccount("alpha*", "other-user", "other-password")
            target = RefreshAccount("alpha?", "target-user", "target-password")
            AccountsStore(paths.accounts_path).save([other, target])
            other_file = write_account_url_shortcut(paths, other, "https://example.invalid/other")
            direct_store = DirectLinkStore(paths.direct_links_path)
            direct_store.links = {
                other.name: {
                    "direct_url": "https://example.invalid/other",
                    "url_file": other_file.relative_to(paths.data_dir).as_posix(),
                }
            }
            direct_store.save()
            fields = DirectLoginFields(
                token="token",
                time="2000000000",
                sign="sign",
                uid="10001",
                uname="target-user",
            )
            service = DirectLinkRefreshService(
                data_dir=paths.data_dir,
                login_capturer=lambda _account, _channel, _stop: fields,
            )

            summary = service.refresh_accounts([target], retries=0)

            target_record = DirectLinkStore(paths.direct_links_path).get(target.name)
            self.assertEqual(summary.success, 1)
            self.assertEqual(other_file.read_text(encoding="utf-8"), "[InternetShortcut]\nURL=https://example.invalid/other\n")
            self.assertEqual(target_record["url_file"], "直登链接/alpha__2.url")
            self.assertTrue((paths.data_dir / target_record["url_file"]).is_file())

    def test_path_migration_keeps_previous_file_still_reserved_by_another_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            protected_file = paths.url_dir / "shared.url"
            protected_file.write_text("other-account", encoding="utf-8")

            new_target = write_account_url_shortcut(
                paths,
                RefreshAccount("alpha", "u", "p", bookmark_path="账号/存钻/1"),
                "https://example.invalid/new",
                used_paths={protected_file},
                previous_url_file=protected_file.relative_to(paths.data_dir).as_posix(),
            )

            self.assertTrue(new_target.is_file())
            self.assertEqual(protected_file.read_text(encoding="utf-8"), "other-account")

    def test_packaged_refresh_data_dir_uses_appdata_and_supports_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir) / "Roaming"
            packaged = default_refresh_data_dir(environ={"APPDATA": str(appdata)}, frozen=True)
            overridden = default_refresh_data_dir(
                environ={"APPDATA": str(appdata), "H5_LAUNCHER_REFRESH_DATA_DIR": str(Path(temp_dir) / "custom")},
                frozen=True,
            )

            self.assertEqual(packaged, appdata / "DouluoH5Launcher" / "refresh_data")
            self.assertEqual(overridden, Path(temp_dir) / "custom")

    def test_refresh_data_migration_backs_up_replaced_files_and_keeps_newer_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "legacy"
            target = root / "current"
            source.mkdir()
            target.mkdir()
            old_source = source / "accounts.enc.json"
            old_source.write_text("source-newer", encoding="utf-8")
            replaced_target = target / "accounts.enc.json"
            replaced_target.write_text("target-older", encoding="utf-8")
            newer_target = target / "channels.json"
            newer_target.write_text("target-newer", encoding="utf-8")
            older_source = source / "channels.json"
            older_source.write_text("source-older", encoding="utf-8")
            grouped_source = source / "分组" / "账号"
            grouped_source.mkdir(parents=True)
            grouped_file = grouped_source / "1.url"
            grouped_file.write_text("grouped", encoding="utf-8")
            os.utime(replaced_target, (1, 1))
            os.utime(old_source, (2, 2))
            os.utime(older_source, (1, 1))
            os.utime(newer_target, (2, 2))

            counts = migrate_refresh_data(target, [source])

            self.assertEqual(replaced_target.read_text(encoding="utf-8"), "source-newer")
            self.assertEqual(newer_target.read_text(encoding="utf-8"), "target-newer")
            self.assertEqual(counts, {"copied": 1, "replaced": 1, "skipped_newer": 1})
            self.assertEqual((target / "分组" / "账号" / "1.url").read_text(encoding="utf-8"), "grouped")
            backups = list((target / "backups").glob("migration_accounts.enc.json_*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "target-older")

    def test_default_channel_builds_client_direct_url_with_launcher_gid(self) -> None:
        channel = default_channel_config()
        url = build_client_direct_url(
            DirectLoginFields(
                token="token-from-login",
                time="1783000000",
                sign="sign-from-login",
                uid="1517000000",
                uname="user1",
            ),
            channel=channel,
        )

        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)

        self.assertEqual(channel.name, DEFAULT_CHANNEL_NAME)
        self.assertEqual(channel.web_login_url, "http://37.com.cn/h5game/public/?pid=1&gid=1005172&refer=1_100172_10552_1")
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "dldl.50pk.com")
        self.assertEqual(parsed.path, "/login.php")
        self.assertEqual(query["gid"], ["1002997"])
        self.assertEqual(query["pid"], ["1"])
        self.assertEqual(query["token"], ["token-from-login"])
        self.assertEqual(query["time"], ["1783000000"])
        self.assertEqual(query["sign"], ["sign-from-login"])
        self.assertEqual(query["appVer"], [""])
        self.assertEqual(query["platCode"], ["37wan"])
        self.assertEqual(query["IMEI"], [""])
        self.assertEqual(query["isPcLauncher"], ["true"])

    def test_ensure_refresh_data_dir_creates_v140_layout_and_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "上号器数据"

            paths = ensure_refresh_data_dir(data_dir)
            channels = load_channels(data_dir)

            self.assertTrue(paths.accounts_path.parent.exists())
            self.assertTrue(paths.direct_links_path.parent.exists())
            self.assertTrue(paths.url_dir.exists())
            self.assertTrue(paths.backups_dir.exists())
            self.assertTrue(paths.logs_dir.exists())
            self.assertTrue(paths.channels_path.exists())
            self.assertEqual(channels[DEFAULT_CHANNEL_NAME].client_params["gid"], "1002997")

    def test_import_accounts_supports_header_and_optional_bookmark_path(self) -> None:
        imported = import_accounts_from_text(
            "name,username,password,bookmark_path\n"
            "111,user-one,pw-one,\n"
            "112,user-two,pw-two,账号/第一层/112\n"
            ",missing,pw,\n"
        )

        self.assertEqual(len(imported.accounts), 2)
        self.assertEqual(imported.accounts[0].name, "111")
        self.assertEqual(imported.accounts[0].refresh_mode, "本地链接")
        self.assertEqual(imported.accounts[1].bookmark_path, "账号/第一层/112")
        self.assertEqual(imported.accounts[1].refresh_mode, "收藏夹")
        self.assertEqual(imported.failures[0].status, "import_failed")
        self.assertIn("name", imported.failures[0].message)

    def test_import_accounts_supports_no_header_tab_separated_rows(self) -> None:
        imported = import_accounts_from_text("111\tuser-one\tpw-one\n112\tuser-two\tpw-two\t账号/第一层/112\n")

        self.assertEqual([account.name for account in imported.accounts], ["111", "112"])
        self.assertEqual(imported.accounts[1].bookmark_path, "账号/第一层/112")
        self.assertEqual(imported.failures, [])

    def test_write_url_shortcut_uses_safe_atomic_unique_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            used: set[Path] = set()

            first = write_url_shortcut(output_dir, "111:*?", "https://example.test/one?token=secret", used_paths=used)
            second = write_url_shortcut(output_dir, "111:*?", "https://example.test/two?token=secret", used_paths=used)

            self.assertEqual(first.name, "111___.url")
            self.assertEqual(second.name, "111____2.url")
            self.assertEqual(first.read_text(encoding="utf-8"), "[InternetShortcut]\nURL=https://example.test/one?token=secret\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "[InternetShortcut]\nURL=https://example.test/two?token=secret\n")
            self.assertFalse(list(output_dir.glob("*.tmp")))

    def test_direct_link_store_failure_does_not_overwrite_previous_success_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DirectLinkStore(Path(temp_dir) / "direct_links.enc.json")
            generated_at = datetime(2026, 7, 9, 12, 30, 0, tzinfo=timezone.utc)

            store.update_from_result(
                RefreshResult(
                    name="111",
                    channel=DEFAULT_CHANNEL_NAME,
                    generated_at=generated_at,
                    expire_hint=generated_at,
                    status="success",
                    message="ok",
                    direct_url="https://example.test/login?token=old&sign=old",
                    uid_len=4,
                    uname_len=5,
                    token_len=3,
                    time_len=10,
                    sign_len=3,
                    bookmark_path="",
                    url_file="111.url",
                )
            )
            store.update_from_result(
                RefreshResult(
                    name="111",
                    channel=DEFAULT_CHANNEL_NAME,
                    generated_at=generated_at,
                    expire_hint=generated_at,
                    status="login_failed",
                    message="bad password",
                    bookmark_path="",
                )
            )

            record = store.get("111")
            self.assertIsNotNone(record)
            self.assertEqual(record["direct_url"], "https://example.test/login?token=old&sign=old")
            self.assertEqual(record["status"], "login_failed")
            self.assertEqual(record["message"], "bad password")

    def test_summary_writer_excludes_password_token_sign_and_direct_url(self) -> None:
        generated_at = datetime(2026, 7, 9, 12, 30, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "refresh_summary.csv"

            RefreshSummaryWriter(summary_path).write(
                [
                    RefreshResult(
                        name="111",
                        channel=DEFAULT_CHANNEL_NAME,
                        generated_at=generated_at,
                        expire_hint=generated_at,
                        status="success",
                        message="token_len=262 sign_len=32",
                        direct_url="https://example.test/login?token=secret&sign=secret",
                        uid_len=10,
                        uname_len=4,
                        token_len=262,
                        time_len=10,
                        sign_len=32,
                        bookmark_path="账号/第一层/111",
                        url_file="111.url",
                    )
                ]
            )

            text = summary_path.read_text(encoding="utf-8-sig")
            self.assertNotIn("https://example.test/login", text)
            self.assertNotIn("secret", text)
            with summary_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))

            self.assertEqual(rows[0]["name"], "111")
            self.assertEqual(rows[0]["refresh_mode"], "收藏夹")
            self.assertEqual(rows[0]["uid_len"], "10")
            self.assertEqual(rows[0]["token_len"], "262")
            self.assertEqual(rows[0]["url_file"], "111.url")

    def test_bookmark_failure_with_local_link_remains_success_and_is_counted_separately(self) -> None:
        generated_at = datetime(2026, 7, 9, 12, 30, 0, tzinfo=timezone.utc)
        summary = summarize_results(
            [
                RefreshResult(
                    name="111",
                    channel=DEFAULT_CHANNEL_NAME,
                    generated_at=generated_at,
                    expire_hint=generated_at,
                    status="bookmark_not_found",
                    message="已刷新本地链接，收藏夹路径未找到",
                    direct_url="https://example.test/login?token=secret&sign=secret",
                    bookmark_path="账号/第一层/111",
                    url_file="111.url",
                )
            ]
        )

        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.failure, 0)
        self.assertEqual(summary.local_links, 1)
        self.assertEqual(summary.bookmark_success, 0)
        self.assertEqual(summary.bookmark_failure, 1)

    def test_resolve_client_direct_url_prefers_fresh_local_link_by_bookmark_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DirectLinkStore(Path(temp_dir) / "direct_links.enc.json")
            generated_at = datetime(2026, 7, 9, 12, 30, 0, tzinfo=timezone.utc)
            store.update_from_result(
                RefreshResult(
                    name="111",
                    channel=DEFAULT_CHANNEL_NAME,
                    generated_at=generated_at,
                    expire_hint=datetime(2026, 7, 31, 12, 30, 0, tzinfo=timezone.utc),
                    status="success",
                    message="ok",
                    direct_url="https://fresh.example/login?token=t&time=1&sign=s&gid=1002997&pid=1&isPcLauncher=true",
                )
            )
            account = AccountConfig(
                level="第一层",
                bookmark_no=1,
                game_window_no=1,
                url="https://bookmark.example/login?token=old&time=1&sign=s&gid=1002997&pid=1&isPcLauncher=true",
                bookmark_title="111",
            )

            resolved = resolve_client_direct_url_for_account(account, store.path, now=generated_at)

            self.assertEqual(resolved.status, "found")
            self.assertEqual(resolved.direct_url, "https://fresh.example/login?token=t&time=1&sign=s&gid=1002997&pid=1&isPcLauncher=true")
            self.assertEqual(resolved.name, "111")

    def test_resolve_client_direct_url_rejects_conflicting_alias_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DirectLinkStore(Path(temp_dir) / "direct_links.enc.json")
            store.links = {
                "111": {"direct_url": "https://first.invalid/login?token=a&sign=a"},
                "第一层-1": {"direct_url": "https://second.invalid/login?token=b&sign=b"},
            }
            store.save()
            account = AccountConfig(
                level="第一层",
                bookmark_no=1,
                game_window_no=1,
                url="https://bookmark.invalid/original",
                bookmark_title="111",
            )

            resolved = resolve_client_direct_url_for_account(account, store.path)

            self.assertEqual(resolved.status, "conflict")
            self.assertEqual(resolved.direct_url, "")

    def test_resolve_client_direct_url_uses_unique_bookmark_path_when_refresh_name_differs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DirectLinkStore(Path(temp_dir) / "direct_links.enc.json")
            store.links = {
                "csv-row-alpha": {
                    "direct_url": "https://fresh.invalid/login/1",
                    "bookmark_path": "账号/存钻/1",
                }
            }
            store.save()
            account = AccountConfig("存钻", 1, 1, "/", bookmark_title="1")

            resolved = resolve_client_direct_url_for_identity(
                account,
                store.path,
                account_key=account.key,
                refresh_account_name="1",
                slot_index=1,
            )

            self.assertEqual(resolved.status, "found")
            self.assertEqual(resolved.name, "csv-row-alpha")
            self.assertEqual(resolved.bookmark_path, "账号/存钻/1")

    def test_resolve_client_direct_url_rejects_duplicate_bookmark_path_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DirectLinkStore(Path(temp_dir) / "direct_links.enc.json")
            store.links = {
                "csv-row-alpha": {"direct_url": "https://first.invalid/", "bookmark_path": "账号/存钻/1"},
                "csv-row-beta": {"direct_url": "https://second.invalid/", "bookmark_path": "账号/存钻/1"},
            }
            store.save()
            account = AccountConfig("存钻", 1, 1, "/", bookmark_title="1")

            resolved = resolve_client_direct_url_for_identity(account, store.path, slot_index=1)

            self.assertEqual(resolved.status, "conflict")
            self.assertEqual(resolved.direct_url, "")

    def test_update_accounts_after_result_records_status_without_changing_password(self) -> None:
        account = RefreshAccount(name="111", username="user", password="pw", channel=DEFAULT_CHANNEL_NAME)
        generated_at = datetime(2026, 7, 9, 12, 30, 0, tzinfo=timezone.utc)

        updated = update_accounts_after_result(
            [account],
            RefreshResult(
                name="111",
                channel=DEFAULT_CHANNEL_NAME,
                generated_at=generated_at,
                expire_hint=generated_at,
                status="success",
                message="ok",
            ),
        )

        self.assertEqual(updated[0].password, "pw")
        self.assertEqual(updated[0].last_status, "success")
        self.assertEqual(updated[0].last_refresh_time, "2026-07-09T12:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
