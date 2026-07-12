from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.run_http_direct_login_from_csv import (
    sanitize_account_error,
    select_accounts_from_csv,
)


class HttpDirectLoginCsvRunnerTests(unittest.TestCase):
    def _write_accounts(self, root: Path) -> Path:
        path = root / "accounts.csv"
        path.write_text(
            "alpha,user-one,pass-one\n"
            "beta,user-two,pass-two\n",
            encoding="utf-8-sig",
        )
        return path

    def test_selects_first_valid_account_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_accounts(Path(temp_dir))
            before = path.read_bytes()

            accounts = select_accounts_from_csv(path, limit=1)

            self.assertEqual([account.name for account in accounts], ["alpha"])
            self.assertEqual(path.read_bytes(), before)

    def test_selects_account_by_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_accounts(Path(temp_dir))

            accounts = select_accounts_from_csv(path, name="beta", limit=1)

            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].username, "user-two")

    def test_limit_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_accounts(Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "limit"):
                select_accounts_from_csv(path, limit=0)

    def test_error_sanitizer_masks_selected_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_accounts(Path(temp_dir))
            account = select_accounts_from_csv(path, limit=1)[0]

            text = sanitize_account_error(
                RuntimeError(f"request failed user={account.username} password={account.password}"),
                account,
            )

            self.assertNotIn(account.username, text)
            self.assertNotIn(account.password, text)


if __name__ == "__main__":
    unittest.main()
