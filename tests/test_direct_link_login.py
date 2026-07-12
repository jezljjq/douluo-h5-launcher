from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from douluo_launcher.direct_link_login import DirectLinkLoginOptions, create_login_capturer, load_http_har_for_mode
from douluo_launcher.direct_link_refresh import RefreshAccount, default_channel_config


class DirectLinkLoginTests(unittest.TestCase):
    def test_auto_mode_missing_har_stops_before_playwright(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            options = DirectLinkLoginOptions(mode="auto", http_har=Path(temp_dir) / "missing.har")
            with self.assertRaises(FileNotFoundError):
                load_http_har_for_mode(options)

            playwright = Mock()
            capture = create_login_capturer(options, None, playwright_capturer=playwright)
            with self.assertRaises(FileNotFoundError):
                capture(RefreshAccount("one", "user", "password"), default_channel_config(), None)
            playwright.assert_not_called()


if __name__ == "__main__":
    unittest.main()
