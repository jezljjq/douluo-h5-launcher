from __future__ import annotations

import unittest
import tempfile
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from douluo_launcher.config import AccountConfig
from douluo_launcher.direct_link_refresh import (
    BookmarkWriteContext,
    DirectLinkStore,
    RefreshAccount,
    RefreshResult,
    default_channel_config,
    summarize_results,
)
from douluo_launcher.gui import (
    LoginAccountManagerDialog,
    RefreshAddressDialog,
    _build_gui_refresh_login_capturer,
    _bookmark_write_context_from_owner,
    _centered_child_position,
    _format_refresh_summary,
    _inject_latest_client_direct_urls,
    _position_dialog_relative_to_owner,
    _refresh_status_display,
    _refresh_status_tag,
    _synchronize_refreshed_urls,
)


class GuiRefreshAddressTests(unittest.TestCase):
    def test_sync_existing_links_uses_stores_and_batch_updater_without_login(self) -> None:
        source = inspect.getsource(RefreshAddressDialog._sync_existing_links_worker)
        self.assertIn("DirectLinkStore", source)
        self.assertIn("BookmarkBatchItem", source)
        self.assertIn("apply_batch", source)
        self.assertNotIn("login_capturer", source)
        self.assertNotIn("_capture_login_fields", source)
        self.assertNotIn("Playwright", source)

    def test_login_account_manager_has_required_filters_order_and_non_destructive_actions(self) -> None:
        source = inspect.getsource(LoginAccountManagerDialog)

        for label in ("状态筛选", "分组筛选", "全部分组", "全部", "已参与", "未参与", "链接缺失", "链接过期"):
            self.assertIn(label, source)
        self.assertIn("status_filter_var", source)
        self.assertIn("group_filter_var", source)
        for action in ("上移", "下移", "选中账号加入上号列表", "选中账号移出上号列表", "当前筛选全部加入", "当前筛选全部移出"):
            self.assertIn(action, source)
        self.assertIn("mask_sensitive_text(direct_url)", source)
        self.assertNotIn("delete_refresh_account_resources", source)

    def test_centered_child_position_uses_owner_center(self) -> None:
        position = _centered_child_position(
            owner_bounds=(100, 200, 1200, 800),
            child_size=(1080, 560),
            work_area=(0, 0, 1920, 1040),
        )

        self.assertEqual(position, (160, 320))

    def test_centered_child_position_supports_negative_secondary_monitor_coordinates(self) -> None:
        position = _centered_child_position(
            owner_bounds=(-1800, 100, 1400, 900),
            child_size=(1080, 560),
            work_area=(-1920, 0, 0, 1040),
        )

        self.assertEqual(position, (-1640, 270))

    def test_centered_child_position_clamps_to_monitor_work_area(self) -> None:
        position = _centered_child_position(
            owner_bounds=(1800, 900, 500, 400),
            child_size=(1080, 560),
            work_area=(0, 0, 1920, 1040),
        )

        self.assertEqual(position, (840, 480))

    def test_position_dialog_relative_to_owner_uses_rendered_size_and_monitor(self) -> None:
        class FakeDialog:
            def __init__(self) -> None:
                self.updated = False

            def update_idletasks(self) -> None:
                self.updated = True

            def winfo_width(self) -> int:
                return 1

            def winfo_height(self) -> int:
                return 1

            def winfo_reqwidth(self) -> int:
                return 1080

            def winfo_reqheight(self) -> int:
                return 560

        owner = SimpleNamespace(
            winfo_rootx=lambda: -1800,
            winfo_rooty=lambda: 100,
            winfo_width=lambda: 1400,
            winfo_height=lambda: 900,
        )
        dialog = FakeDialog()
        moved: list[tuple[int, int]] = []

        position = _position_dialog_relative_to_owner(
            dialog,
            owner,
            work_area_provider=lambda _owner: (-1920, 0, 0, 1040),
            move_window=lambda _dialog, x, y: moved.append((x, y)),
        )

        self.assertTrue(dialog.updated)
        self.assertEqual(position, (-1640, 270))
        self.assertEqual(moved, [(-1640, 270)])

    def test_delete_selected_accounts_routes_through_owned_resource_cleanup(self) -> None:
        target = AccountConfig("存钻", 1, 1, "https://example.invalid/alpha", bookmark_title="alpha")
        other = AccountConfig("其它", 1, 2, "https://example.invalid/other", bookmark_title="beta")
        owner = SimpleNamespace(
            accounts=[target, other],
            client_batch_store=object(),
            client_direct_bindings={"alpha": "cached"},
            _refresh_table=Mock(),
            _refresh_account_choices=Mock(),
            _log=Mock(),
        )
        dialog = SimpleNamespace(
            paths=Path("data"),
            owner=owner,
            account_store=SimpleNamespace(load=Mock(return_value=[RefreshAccount("beta", "user", "password")])),
            checked_names={"alpha", "beta"},
            status_var=SimpleNamespace(set=Mock()),
            _selected_names=Mock(return_value={"alpha"}),
            _refresh_table=Mock(),
        )
        deletion = SimpleNamespace(
            account_removed=True,
            url_files_removed=["分组/账号/alpha.url"],
            bindings_removed=1,
            errors=[],
        )

        with patch("douluo_launcher.gui.messagebox.askyesno", return_value=True), patch(
            "douluo_launcher.gui.delete_refresh_account_resources", return_value=deletion
        ) as cleanup:
            RefreshAddressDialog._delete_selected_accounts(dialog)

        cleanup.assert_called_once_with(
            Path("data"),
            "alpha",
            account_keys={"存钻-1"},
            client_batch_store=owner.client_batch_store,
            runtime_cache=owner.client_direct_bindings,
        )
        self.assertEqual(owner.accounts, [other])
        self.assertEqual(dialog.checked_names, {"beta"})
        owner._refresh_table.assert_called_once_with()
        owner._refresh_account_choices.assert_called_once_with()

    def test_delete_selected_accounts_keeps_main_account_when_account_store_update_fails(self) -> None:
        target = AccountConfig("存钻", 1, 1, "https://example.invalid/alpha", bookmark_title="alpha")
        owner = SimpleNamespace(
            accounts=[target],
            client_batch_store=object(),
            client_direct_bindings={},
            _refresh_table=Mock(),
            _refresh_account_choices=Mock(),
            _log=Mock(),
        )
        dialog = SimpleNamespace(
            paths=Path("data"),
            owner=owner,
            account_store=SimpleNamespace(load=Mock(return_value=[RefreshAccount("alpha", "user", "password")])),
            checked_names={"alpha"},
            status_var=SimpleNamespace(set=Mock()),
            _selected_names=Mock(return_value={"alpha"}),
            _refresh_table=Mock(),
        )
        deletion = SimpleNamespace(account_removed=False, url_files_removed=[], bindings_removed=0, errors=["accounts:OSError"])

        with patch("douluo_launcher.gui.messagebox.askyesno", return_value=True), patch(
            "douluo_launcher.gui.delete_refresh_account_resources", return_value=deletion
        ):
            RefreshAddressDialog._delete_selected_accounts(dialog)

        self.assertEqual(owner.accounts, [target])

    def _account(self) -> RefreshAccount:
        return RefreshAccount(name="alpha", username="user-one", password="pass-one")

    def _fields(self, token: str):
        from douluo_launcher.direct_link_refresh import DirectLoginFields

        return DirectLoginFields(
            token=token,
            time="2000000000",
            sign="s" * 32,
            uid="10001",
            uname="user-one",
        )

    def test_gui_defaults_to_auto_and_http_success_does_not_start_playwright(self) -> None:
        expected = self._fields("http-token")
        playwright_capture = Mock()
        logs: list[str] = []

        with patch(
            "douluo_launcher.gui.load_http_har_for_mode",
            return_value={"log": {"entries": []}},
        ) as load_har, patch(
            "douluo_launcher.direct_link_login.http_login_from_har",
            return_value=expected,
        ) as http_login:
            capturer = _build_gui_refresh_login_capturer(playwright_capture, logs.append, lambda _name: True)
            actual = capturer(self._account(), default_channel_config(), None)

        self.assertIs(actual, expected)
        self.assertEqual(load_har.call_args.args[0].mode, "auto")
        http_login.assert_called_once()
        playwright_capture.assert_not_called()

    def test_gui_auto_falls_back_to_playwright_after_http_failure(self) -> None:
        expected = self._fields("browser-token")
        playwright_capture = Mock(return_value=expected)
        logs: list[str] = []

        with patch(
            "douluo_launcher.gui.load_http_har_for_mode",
            return_value={"log": {"entries": []}},
        ), patch(
            "douluo_launcher.direct_link_login.http_login_from_har",
            side_effect=RuntimeError("network failed"),
        ):
            capturer = _build_gui_refresh_login_capturer(playwright_capture, logs.append, lambda _name: True)
            actual = capturer(self._account(), default_channel_config(), None)

        self.assertIs(actual, expected)
        playwright_capture.assert_called_once()
        self.assertTrue(any("回退 Playwright" in line for line in logs))

    def test_bookmark_skipped_is_success_and_has_separate_gui_count(self) -> None:
        generated_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        result = RefreshResult(
            name="alpha",
            channel="正式服",
            generated_at=generated_at,
            expire_hint=generated_at + timedelta(days=22),
            status="bookmark_update_skipped",
            message="已刷新本地链接，收藏夹写回尚未接入",
            direct_url="https://example.test/login",
            bookmark_path="账号/第一层/alpha",
            url_file="alpha.url",
        )

        summary = summarize_results([result])
        text = _format_refresh_summary(summary)

        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.failure, 0)
        self.assertEqual(summary.bookmark_failure, 0)
        self.assertEqual(summary.bookmark_skipped, 1)
        self.assertIn("收藏夹未写回 1", text)
        self.assertEqual(_refresh_status_display(result.status), "本地成功/收藏夹未写回")
        self.assertEqual(_refresh_status_tag(result.status), "skip")

    def test_local_success_uses_success_display(self) -> None:
        self.assertEqual(_refresh_status_display("local_success"), "本地刷新成功")
        self.assertEqual(_refresh_status_tag("local_success"), "success")
        self.assertEqual(_refresh_status_display("stopping"), "停止中")
        self.assertEqual(_refresh_status_tag("stopping"), "running")

    def test_close_while_refresh_running_requests_stop_and_defers_destroy(self) -> None:
        dialog = SimpleNamespace(
            worker_thread=SimpleNamespace(is_alive=lambda: True),
            _close_when_idle=False,
            _stop_refresh=Mock(),
            status_var=SimpleNamespace(set=Mock()),
            _save_accounts=Mock(),
            destroy=Mock(),
        )

        RefreshAddressDialog._close(dialog)

        self.assertTrue(dialog._close_when_idle)
        dialog._stop_refresh.assert_called_once()
        dialog.destroy.assert_not_called()

    def test_gui_builds_bookmark_context_from_current_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bookmark_file = Path(temp_dir) / "Bookmarks"
            bookmark_file.write_text("{}", encoding="utf-8")
            owner = SimpleNamespace(
                bookmark_path=SimpleNamespace(get=lambda: str(bookmark_file)),
                bookmark_root_path=SimpleNamespace(get=lambda: "roots/bookmark_bar/children/1"),
                bookmark_root_name=SimpleNamespace(get=lambda: "账号"),
                bookmark_root_guid=SimpleNamespace(get=lambda: "stable-root-guid"),
                bookmark_root_parent_path=SimpleNamespace(get=lambda: "roots/bookmark_bar"),
            )

            with patch(
                "douluo_launcher.gui.describe_bookmark_file",
                return_value=SimpleNamespace(browser="Edge", profile="Default"),
            ):
                context = _bookmark_write_context_from_owner(owner)

            self.assertEqual(
                context,
                BookmarkWriteContext(
                    bookmark_file=bookmark_file,
                    browser="Edge",
                    profile="Default",
                    root_path="roots/bookmark_bar/children/1",
                    root_name="账号",
                    root_guid="stable-root-guid",
                    root_parent_path="roots/bookmark_bar",
                    allow_create_root=True,
                ),
            )

    def test_successful_writeback_updates_main_account_and_unique_current_binding(self) -> None:
        account = AccountConfig(
            level="存钻",
            bookmark_no=1,
            game_window_no=1,
            url="https://old.example/alpha",
            bookmark_title="alpha",
        )
        binding = SimpleNamespace(
            account_id=account.key,
            account_name=account.display_name,
            login_url="https://old.example/alpha",
        )
        store = SimpleNamespace(
            batches=[SimpleNamespace(bindings=[binding])],
            current_batch=lambda: SimpleNamespace(bindings=[binding]),
            save=Mock(),
        )
        owner = SimpleNamespace(
            accounts=[account],
            client_batch_store=store,
            _refresh_table=Mock(),
            _refresh_account_choices=Mock(),
            _log=Mock(),
        )
        generated_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        result = RefreshResult(
            name="alpha",
            channel="正式服",
            generated_at=generated_at,
            expire_hint=generated_at + timedelta(days=22),
            status="bookmark_success",
            direct_url="https://new.example/alpha",
            bookmark_path="存钻/alpha",
        )

        counts = _synchronize_refreshed_urls(owner, [result])

        self.assertEqual(owner.accounts[0].url, "https://new.example/alpha")
        self.assertEqual(binding.login_url, "https://new.example/alpha")
        self.assertEqual(counts, {"accounts": 1, "bindings": 1, "conflicts": 0})
        store.save.assert_called_once()
        owner._refresh_table.assert_called_once()

    def test_latest_local_link_updates_account_and_existing_batch_without_logging_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct_links.enc.json"
            store = DirectLinkStore(path)
            store.links = {
                "alpha": {
                    "direct_url": "https://latest.invalid/login?token=private&sign=private",
                    "expire_hint": "2099-01-01T00:00:00+00:00",
                }
            }
            store.save()
            account = AccountConfig("第一层", 1, 1, "https://bookmark.invalid/old", bookmark_title="alpha")
            record = SimpleNamespace(login_url=account.url)
            binding = SimpleNamespace(account_id=account.key, login_url=account.url)
            batch_store = SimpleNamespace(
                batches=[object()],
                current_batch=lambda: SimpleNamespace(bindings=[binding]),
                save=Mock(),
            )
            owner = SimpleNamespace(
                refresh_direct_links_path=path,
                client_direct_bindings={account.key: record},
                client_batch_store=batch_store,
                _log=Mock(),
            )

            updated = _inject_latest_client_direct_urls(owner, [account])

            self.assertEqual(updated[0].url, "https://latest.invalid/login?token=private&sign=private")
            self.assertEqual(record.login_url, updated[0].url)
            self.assertEqual(binding.login_url, updated[0].url)
            batch_store.save.assert_called_once()
            logged = str(owner._log.call_args.args[0])
            self.assertNotIn("latest.invalid", logged)
            self.assertNotIn("private", logged)

    def test_latest_link_metadata_is_persisted_when_url_text_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct_links.enc.json"
            direct_url = "https://latest.invalid/login"
            store = DirectLinkStore(path)
            store.links = {
                "alpha": {
                    "direct_url": direct_url,
                    "bookmark_path": "账号/存钻/1",
                    "expire_hint": "2099-01-01T00:00:00+00:00",
                }
            }
            store.save()
            account = AccountConfig("存钻", 1, 1, direct_url, bookmark_title="alpha")
            binding = SimpleNamespace(
                account_id=account.key,
                account_key=account.key,
                login_url=direct_url,
                refresh_account_name="",
                bookmark_path="",
                identity_status="",
                link_status="",
            )
            batch_store = SimpleNamespace(
                batches=[object()],
                current_batch=lambda: SimpleNamespace(bindings=[binding]),
                save=Mock(),
            )
            owner = SimpleNamespace(
                refresh_direct_links_path=path,
                client_direct_bindings={},
                client_batch_store=batch_store,
                _log=Mock(),
            )

            _inject_latest_client_direct_urls(owner, [account])

            self.assertEqual(binding.bookmark_path, "账号/存钻/1")
            self.assertEqual(binding.link_status, "ready")
            batch_store.save.assert_called_once_with()

    def test_missing_latest_link_preserves_bookmark_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct_links.enc.json"
            account = AccountConfig("第一层", 1, 1, "https://bookmark.invalid/original", bookmark_title="alpha")
            owner = SimpleNamespace(
                refresh_direct_links_path=path,
                client_direct_bindings={},
                client_batch_store=SimpleNamespace(batches=[]),
                _log=Mock(),
            )

            updated = _inject_latest_client_direct_urls(owner, [account])

            self.assertEqual(updated[0].url, account.url)

    def test_missing_link_does_not_overwrite_cdp_unavailable_window_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct_links.enc.json"
            account = AccountConfig("存钻", 1, 1, "/", bookmark_title="alpha")
            binding = SimpleNamespace(
                account_id=account.key,
                account_key=account.key,
                login_url="/",
                link_status="",
                window_status="cdp_unavailable",
            )
            owner = SimpleNamespace(
                refresh_direct_links_path=path,
                client_direct_bindings={},
                client_batch_store=SimpleNamespace(
                    batches=[object()],
                    current_batch=lambda: SimpleNamespace(bindings=[binding]),
                    save=Mock(),
                ),
                _log=Mock(),
            )

            updated = _inject_latest_client_direct_urls(owner, [account])

            self.assertEqual(updated[0].url, "/")
            self.assertEqual(binding.link_status, "link_missing")
            self.assertEqual(binding.window_status, "cdp_unavailable")


if __name__ == "__main__":
    unittest.main()
