from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from douluo_launcher.direct_link_refresh import (
    AccountsStore,
    BookmarkUrlUpdater,
    RefreshAccount,
    ensure_refresh_data_dir,
)
from tools.refresh_client_direct_links import DEFAULT_CHANNEL_NAME, _bookmark_updater_from_args, main


class RefreshClientDirectLinksSelectionTests(unittest.TestCase):
    def test_cli_bookmark_write_requires_complete_explicit_context(self) -> None:
        args = argparse.Namespace(
            write_bookmarks=True,
            bookmark_file=Path("Bookmarks"),
            bookmark_browser="Edge",
            bookmark_profile="",
            bookmark_root_path="roots/bookmark_bar/children/1",
            bookmark_root_name="账号",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            with self.assertRaisesRegex(ValueError, "--bookmark-profile"):
                _bookmark_updater_from_args(args, paths)

    def test_cli_bookmark_write_builds_real_updater_with_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ensure_refresh_data_dir(root / "data")
            bookmark_file = root / "Bookmarks"
            bookmark_file.write_text("{}", encoding="utf-8")
            args = argparse.Namespace(
                write_bookmarks=True,
                bookmark_file=bookmark_file,
                bookmark_browser="Edge",
                bookmark_profile="Default",
                bookmark_root_path="roots/bookmark_bar/children/1",
                bookmark_root_name="账号",
            )

            updater = _bookmark_updater_from_args(args, paths)

            self.assertIsInstance(updater, BookmarkUrlUpdater)
            self.assertFalse(updater.dry_run)
            self.assertEqual(updater.context.bookmark_file, bookmark_file)
            self.assertEqual(updater.backups_dir, paths.backups_dir)

    def test_cli_defaults_to_bookmark_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            updater = _bookmark_updater_from_args(argparse.Namespace(), paths)

            self.assertTrue(updater.dry_run)
            self.assertIsNone(updater.context)

    def test_import_file_limits_only_freshly_imported_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            paths = ensure_refresh_data_dir(data_dir)
            AccountsStore(paths.accounts_path).save(
                [RefreshAccount(name="old", username="old-user", password="old-pass")]
            )
            import_file = root / "incoming.csv"
            import_file.write_text(
                "first,new-user-one,new-pass-one\n"
                "second,new-user-two,new-pass-two\n",
                encoding="utf-8-sig",
            )
            args = argparse.Namespace(
                import_file=import_file,
                channel=DEFAULT_CHANNEL_NAME,
                name="",
                limit=1,
                expire_days=22,
                data_dir=data_dir,
                dry_run=True,
                settings=root / "settings.json",
                login_mode="auto",
                http_har=root / "research.har",
                http_timeout=5.0,
                capture_timeout=5.0,
                headless=True,
                retries=0,
            )
            service = MagicMock()
            service.refresh_accounts.return_value = SimpleNamespace(
                total=1,
                success=1,
                failure=0,
                local_links=1,
                bookmark_success=0,
                bookmark_failure=0,
            )

            with patch(
                "tools.refresh_client_direct_links.parse_args",
                return_value=args,
            ), patch(
                "tools.refresh_client_direct_links._load_http_har_for_mode",
                return_value={"log": {"entries": []}},
            ), patch(
                "tools.refresh_client_direct_links.DirectLinkRefreshService",
                return_value=service,
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            candidates = service.refresh_accounts.call_args.args[0]
            self.assertEqual([account.name for account in candidates], ["first", "second"])
            self.assertEqual(service.refresh_accounts.call_args.kwargs["limit"], 1)


if __name__ == "__main__":
    unittest.main()
