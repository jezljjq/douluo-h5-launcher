from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from douluo_launcher.direct_link_refresh import AccountsStore, DirectLinkStore, RefreshAccount


class _FakeProtector:
    def protect(self, data: bytes) -> bytes:
        return b"P" + bytes(data)[::-1]

    def unprotect(self, data: bytes) -> bytes:
        if not data.startswith(b"P"):
            raise ValueError("invalid protected payload")
        return data[1:][::-1]


class _FailingProtector:
    def protect(self, _data: bytes) -> bytes:
        raise RuntimeError("protect failed")

    def unprotect(self, _data: bytes) -> bytes:
        raise RuntimeError("unprotect failed")


class ProtectedRefreshDataTests(unittest.TestCase):
    def test_accounts_store_encrypts_password_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.enc.json"
            store = AccountsStore(path, protector=_FakeProtector())
            store.save([RefreshAccount(name="alpha", username="user-one", password="private-password")])

            raw = path.read_text(encoding="utf-8")
            envelope = json.loads(raw)
            self.assertEqual(envelope["schema_version"], 2)
            self.assertEqual(envelope["protection"], "windows-dpapi")
            self.assertNotIn("private-password", raw)
            self.assertNotIn("user-one", raw)
            self.assertEqual(store.load()[0].password, "private-password")

    def test_direct_link_store_encrypts_full_url_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct_links.enc.json"
            store = DirectLinkStore(path, protector=_FakeProtector())
            store.links = {"alpha": {"direct_url": "https://example.invalid/login?token=private&sign=private"}}
            store.save()

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("https://example.invalid", raw)
            self.assertNotIn("token=private", raw)
            self.assertEqual(
                DirectLinkStore(path, protector=_FakeProtector()).get("alpha")["direct_url"],
                "https://example.invalid/login?token=private&sign=private",
            )

    def test_plaintext_load_creates_protected_backup_then_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "accounts.enc.json"
            legacy = {
                "schema_version": 1,
                "accounts": [{"name": "alpha", "username": "user", "password": "legacy-password"}],
            }
            path.write_text(json.dumps(legacy), encoding="utf-8")

            accounts = AccountsStore(path, protector=_FakeProtector()).load()

            self.assertEqual(accounts[0].password, "legacy-password")
            self.assertNotIn("legacy-password", path.read_text(encoding="utf-8"))
            backups = list((root / "backups").glob("accounts.enc.json.pre_migration_*.enc.json"))
            self.assertEqual(len(backups), 1)
            self.assertNotIn("legacy-password", backups[0].read_text(encoding="utf-8"))

    def test_failed_plaintext_migration_preserves_source_and_returns_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.enc.json"
            original = json.dumps(
                {"schema_version": 1, "accounts": [{"name": "alpha", "password": "legacy-password"}]}
            )
            path.write_text(original, encoding="utf-8")

            accounts = AccountsStore(path, protector=_FailingProtector()).load()

            self.assertEqual(accounts[0].password, "legacy-password")
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertFalse((path.parent / "backups").exists())

    def test_unreadable_protected_file_cannot_be_overwritten_with_empty_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct_links.enc.json"
            writer = DirectLinkStore(path, protector=_FakeProtector())
            writer.links = {"alpha": {"direct_url": "https://example.invalid/private"}}
            writer.save()
            original = path.read_bytes()

            unreadable = DirectLinkStore(path, protector=_FailingProtector())
            self.assertEqual(unreadable.links, {})
            with self.assertRaisesRegex(RuntimeError, "已阻止覆盖原文件"):
                unreadable.save()

            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
