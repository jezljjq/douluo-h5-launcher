from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from douluo_launcher.direct_link_refresh import (
    DirectLoginFields,
    RefreshAccount,
    default_channel_config,
)
from tools.refresh_client_direct_links import (
    _build_login_capturer,
    _load_http_har_for_mode,
)


class RefreshClientDirectLinksHttpModeTests(unittest.TestCase):
    def _args(self, *, mode: str, har_path: Path | None = None) -> argparse.Namespace:
        return argparse.Namespace(
            login_mode=mode,
            http_timeout=5.0,
            http_har=har_path or Path("missing.har"),
            settings=Path("automation_settings.json"),
            headless=True,
            capture_timeout=5.0,
        )

    def _account(self) -> RefreshAccount:
        return RefreshAccount(name="alpha", username="user-one", password="pass-one")

    def _fields(self, token: str) -> DirectLoginFields:
        return DirectLoginFields(
            token=token,
            time="2000000000",
            sign="s" * 32,
            uid="10001",
            uname="user-one",
        )

    def test_auto_mode_uses_http_without_starting_playwright_when_http_succeeds(self) -> None:
        args = self._args(mode="auto")
        expected = self._fields("http-token")
        capturer = _build_login_capturer(args, {"log": {"entries": []}})

        with patch(
            "tools.refresh_client_direct_links._capture_account_fields_http",
            return_value=expected,
        ) as http_capture, patch(
            "tools.refresh_client_direct_links._capture_account_fields"
        ) as browser_capture:
            actual = capturer(self._account(), default_channel_config(), None)

        self.assertIs(actual, expected)
        http_capture.assert_called_once()
        browser_capture.assert_not_called()

    def test_auto_mode_falls_back_to_playwright_when_http_fails(self) -> None:
        args = self._args(mode="auto")
        expected = self._fields("browser-token")
        capturer = _build_login_capturer(args, {"log": {"entries": []}})

        with patch(
            "tools.refresh_client_direct_links._capture_account_fields_http",
            side_effect=RuntimeError("network failed"),
        ) as http_capture, patch(
            "tools.refresh_client_direct_links._capture_account_fields",
            return_value=expected,
        ) as browser_capture, patch("builtins.input", return_value="y"):
            actual = capturer(self._account(), default_channel_config(), None)

        self.assertIs(actual, expected)
        http_capture.assert_called_once()
        browser_capture.assert_called_once()

    def test_auto_mode_stop_during_http_does_not_fall_back_to_playwright(self) -> None:
        args = self._args(mode="auto")
        stop_event = Event()
        capturer = _build_login_capturer(args, {"log": {"entries": []}})

        def stop_http(*_args, **_kwargs):
            stop_event.set()
            raise TimeoutError("read timeout")

        with patch(
            "tools.refresh_client_direct_links._capture_account_fields_http",
            side_effect=stop_http,
        ), patch("tools.refresh_client_direct_links._capture_account_fields") as browser_capture:
            with self.assertRaisesRegex(InterruptedError, "用户停止"):
                capturer(self._account(), default_channel_config(), stop_event)

        browser_capture.assert_not_called()

    def test_http_mode_does_not_fall_back_to_playwright(self) -> None:
        args = self._args(mode="http")
        capturer = _build_login_capturer(args, {"log": {"entries": []}})

        with patch(
            "tools.refresh_client_direct_links._capture_account_fields_http",
            side_effect=RuntimeError("network failed"),
        ), patch("tools.refresh_client_direct_links._capture_account_fields") as browser_capture:
            with self.assertRaisesRegex(RuntimeError, "network failed"):
                capturer(self._account(), default_channel_config(), None)

        browser_capture.assert_not_called()

    def test_playwright_mode_skips_http(self) -> None:
        args = self._args(mode="playwright")
        expected = self._fields("browser-token")
        capturer = _build_login_capturer(args, None)

        with patch(
            "tools.refresh_client_direct_links._capture_account_fields_http"
        ) as http_capture, patch(
            "tools.refresh_client_direct_links._capture_account_fields",
            return_value=expected,
        ) as browser_capture:
            actual = capturer(self._account(), default_channel_config(), None)

        self.assertIs(actual, expected)
        http_capture.assert_not_called()
        browser_capture.assert_called_once()

    def test_auto_and_http_modes_missing_har_stop_before_playwright(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.har"
            with self.assertRaises(FileNotFoundError):
                _load_http_har_for_mode(self._args(mode="auto", har_path=missing))
            with self.assertRaises(FileNotFoundError):
                _load_http_har_for_mode(self._args(mode="http", har_path=missing))


if __name__ == "__main__":
    unittest.main()
