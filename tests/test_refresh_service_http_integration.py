from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event

from douluo_launcher.direct_link_refresh import (
    BookmarkUrlUpdater,
    DirectLinkRefreshService,
    DirectLoginFields,
    RefreshAccount,
)


class RefreshServiceHttpIntegrationTests(unittest.TestCase):
    def test_successful_capture_updates_store_and_writes_url_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            account = RefreshAccount(
                name="alpha",
                username="user-one",
                password="pass-one",
            )

            service = DirectLinkRefreshService(
                data_dir=data_dir,
                login_capturer=lambda _account, _channel, _stop: DirectLoginFields(
                    token="x" * 40,
                    time="2000000000",
                    sign="s" * 32,
                    uid="10001",
                    uname="user-one",
                ),
                bookmark_updater=BookmarkUrlUpdater(dry_run=True),
                log=lambda _message: None,
            )

            summary = service.refresh_accounts([account], retries=0)

            self.assertEqual(summary.total, 1)
            self.assertEqual(summary.success, 1)
            self.assertEqual(summary.failure, 0)
            self.assertEqual(summary.results[0].status, "local_success")

            store_path = data_dir / "direct_links.enc.json"
            raw = store_path.read_text(encoding="utf-8-sig")
            self.assertNotIn("https://dldl.50pk.com/login.php", raw)
            from douluo_launcher.direct_link_refresh import DirectLinkStore

            record = DirectLinkStore(store_path).get("alpha")
            self.assertIsNotNone(record)
            self.assertEqual(record["token_len"], 40)
            self.assertEqual(record["sign_len"], 32)
            self.assertTrue(str(record["direct_url"]).startswith("https://dldl.50pk.com/login.php?"))

            url_path = data_dir / str(record["url_file"])
            self.assertTrue(url_path.exists())
            self.assertIn("URL=https://dldl.50pk.com/login.php?", url_path.read_text(encoding="utf-8"))

    def test_stop_during_capture_does_not_retry_or_start_next_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stop_event = Event()
            calls: list[str] = []

            def capture(account, _channel, _stop_event):
                calls.append(account.name)
                stop_event.set()
                raise InterruptedError("用户停止")

            service = DirectLinkRefreshService(
                data_dir=Path(temp_dir),
                login_capturer=capture,
                bookmark_updater=BookmarkUrlUpdater(dry_run=True),
            )
            summary = service.refresh_accounts(
                [
                    RefreshAccount(name="alpha", username="u1", password="p1"),
                    RefreshAccount(name="beta", username="u2", password="p2"),
                ],
                retries=3,
                stop_event=stop_event,
            )

            self.assertEqual(calls, ["alpha"])
            self.assertEqual(summary.total, 1)
            self.assertEqual(summary.results[0].status, "stopped")


if __name__ == "__main__":
    unittest.main()
