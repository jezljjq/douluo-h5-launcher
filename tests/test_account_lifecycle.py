from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from douluo_launcher.client_batch_store import ClientBatchBinding, ClientBatchStore
from douluo_launcher.direct_link_refresh import (
    AccountsStore,
    DirectLinkStore,
    RefreshAccount,
    delete_refresh_account_resources,
    ensure_refresh_data_dir,
    write_account_url_shortcut,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AccountLifecycleTests(unittest.TestCase):
    def test_delete_account_cleans_only_program_owned_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = ensure_refresh_data_dir(root / "data")
            target = RefreshAccount("alpha", "user-a", "password-a", bookmark_path="账号/存钻/1")
            other = RefreshAccount("alpha-other", "user-b", "password-b", bookmark_path="账号/其它/1")
            AccountsStore(paths.accounts_path).save([target, other])

            target_file = write_account_url_shortcut(paths, target, "https://example.invalid/alpha")
            other_file = write_account_url_shortcut(paths, other, "https://example.invalid/other")
            legacy_flat = paths.url_dir / "alpha.url"
            legacy_flat.write_text("legacy-generated", encoding="utf-8")
            links = DirectLinkStore(paths.direct_links_path)
            links.links = {
                target.name: {
                    "direct_url": "https://example.invalid/alpha",
                    "bookmark_path": target.bookmark_path,
                    "url_file": target_file.relative_to(paths.data_dir).as_posix(),
                },
                other.name: {
                    "direct_url": "https://example.invalid/other",
                    "bookmark_path": other.bookmark_path,
                    "url_file": other_file.relative_to(paths.data_dir).as_posix(),
                },
            }
            links.save()

            batch_store = ClientBatchStore(root / "sessions.json")
            batch_store.create_batch("batch", scope="存钻")
            batch_store.append_binding(
                ClientBatchBinding(
                    "存钻-1",
                    "目标",
                    account_key="存钻-1",
                    refresh_account_name="alpha",
                    cdp_port=19201,
                )
            )
            batch_store.append_binding(
                ClientBatchBinding(
                    "其它-1",
                    "保留",
                    account_key="其它-1",
                    refresh_account_name="alpha-other",
                    cdp_port=19202,
                )
            )
            batch_store.save()
            runtime_cache = {"alpha": "cached", "alpha-other": "keep"}

            user_csv = root / "user.csv"
            bookmarks = root / "Bookmarks"
            backup = paths.backups_dir / "bookmark-backup.json"
            log = paths.logs_dir / "run.log"
            summary = paths.summary_path
            for path, content in (
                (user_csv, "user-owned-csv"),
                (bookmarks, "user-owned-bookmarks"),
                (backup, "backup"),
                (log, "log"),
                (summary, "summary"),
            ):
                path.write_text(content, encoding="utf-8")
            protected_hashes = {path: _sha256(path) for path in (user_csv, bookmarks, backup, log, summary)}

            result = delete_refresh_account_resources(
                paths,
                "alpha",
                account_keys={"存钻-1"},
                client_batch_store=batch_store,
                runtime_cache=runtime_cache,
            )

            self.assertTrue(result.account_removed)
            self.assertTrue(result.direct_link_removed)
            self.assertEqual(result.errors, [])
            self.assertFalse(target_file.exists())
            self.assertFalse(legacy_flat.exists())
            self.assertTrue(other_file.exists())
            self.assertTrue(paths.grouped_url_dir.exists())
            self.assertEqual([account.name for account in AccountsStore(paths.accounts_path).load()], ["alpha-other"])
            self.assertIsNone(DirectLinkStore(paths.direct_links_path).get("alpha"))
            self.assertIsNotNone(DirectLinkStore(paths.direct_links_path).get("alpha-other"))
            self.assertEqual([binding.account_key for binding in batch_store.current_batch().bindings], ["其它-1"])
            self.assertEqual(runtime_cache, {"alpha-other": "keep"})
            self.assertEqual({path: _sha256(path) for path in protected_hashes}, protected_hashes)

    def test_delete_file_failure_reports_partial_success_without_touching_unrelated_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            target = RefreshAccount("alpha", "user", "password", bookmark_path="")
            AccountsStore(paths.accounts_path).save([target])
            target_file = write_account_url_shortcut(paths, target, "https://example.invalid/alpha")
            unrelated = paths.url_dir / "other.url"
            unrelated.write_text("keep", encoding="utf-8")
            store = DirectLinkStore(paths.direct_links_path)
            store.links = {
                "alpha": {
                    "direct_url": "https://example.invalid/alpha",
                    "url_file": target_file.relative_to(paths.data_dir).as_posix(),
                }
            }
            store.save()

            def fail_unlink(path: Path) -> None:
                if path == target_file.resolve():
                    raise PermissionError("locked")
                path.unlink()

            result = delete_refresh_account_resources(paths, "alpha", unlink_file=fail_unlink)

            self.assertTrue(result.account_removed)
            self.assertTrue(result.direct_link_removed)
            self.assertTrue(target_file.exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
            self.assertEqual(len(result.errors), 1)
            self.assertIn("PermissionError", result.errors[0])

    def test_delete_does_not_remove_generated_file_referenced_by_another_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            target = RefreshAccount("alpha?", "user-a", "password-a", bookmark_path="账号/目标")
            other = RefreshAccount("alpha*", "user-b", "password-b", bookmark_path="")
            AccountsStore(paths.accounts_path).save([target, other])
            target_file = write_account_url_shortcut(paths, target, "https://example.invalid/target")
            other_file = write_account_url_shortcut(paths, other, "https://example.invalid/other")
            links = DirectLinkStore(paths.direct_links_path)
            links.links = {
                target.name: {
                    "url_file": target_file.relative_to(paths.data_dir).as_posix(),
                    "bookmark_path": target.bookmark_path,
                },
                other.name: {
                    "url_file": other_file.relative_to(paths.data_dir).as_posix(),
                    "bookmark_path": other.bookmark_path,
                },
            }
            links.save()

            result = delete_refresh_account_resources(paths, target.name)

            self.assertEqual(result.errors, [])
            self.assertFalse(target_file.exists())
            self.assertTrue(other_file.exists())
            self.assertIsNotNone(DirectLinkStore(paths.direct_links_path).get(other.name))

    def test_delete_rejects_ambiguous_duplicate_account_name_without_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            account_store = AccountsStore(paths.accounts_path)
            account_store.protected_file.write(
                {
                    "schema_version": 1,
                    "accounts": [
                        {"name": "duplicate", "username": "u1", "password": "p1", "order_index": 0},
                        {"name": "duplicate", "username": "u2", "password": "p2", "order_index": 1},
                    ],
                }
            )
            target_file = paths.url_dir / "duplicate.url"
            target_file.write_text("generated", encoding="utf-8")
            links = DirectLinkStore(paths.direct_links_path)
            links.links = {"duplicate": {"url_file": "直登链接/duplicate.url"}}
            links.save()

            result = delete_refresh_account_resources(paths, "duplicate")

            self.assertFalse(result.account_removed)
            self.assertFalse(result.direct_link_removed)
            self.assertTrue(target_file.exists())
            self.assertIn("accounts:identity_conflict", result.errors)

    def test_binding_cleanup_rolls_back_in_memory_when_batch_save_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ensure_refresh_data_dir(Path(temp_dir) / "data")
            AccountsStore(paths.accounts_path).save([RefreshAccount("alpha", "u", "p")])
            target_binding = ClientBatchBinding(
                "存钻-1",
                "目标",
                account_key="存钻-1",
                refresh_account_name="alpha",
                cdp_port=19201,
            )
            other_binding = ClientBatchBinding(
                "其它-1",
                "保留",
                account_key="其它-1",
                refresh_account_name="beta",
                cdp_port=19202,
            )
            batch = type("Batch", (), {"bindings": [target_binding, other_binding]})()

            class FailingBatchStore:
                batches = [batch]

                @staticmethod
                def save() -> None:
                    raise RuntimeError("save failed")

            result = delete_refresh_account_resources(
                paths,
                "alpha",
                account_keys={"存钻-1"},
                client_batch_store=FailingBatchStore(),
            )

            self.assertEqual(batch.bindings, [target_binding, other_binding])
            self.assertEqual(result.bindings_removed, 0)
            self.assertIn("bindings:RuntimeError", result.errors)


if __name__ == "__main__":
    unittest.main()
