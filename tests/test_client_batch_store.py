import tempfile
import unittest
from pathlib import Path

from douluo_launcher.client_batch_store import (
    ClientBatchBinding,
    ClientBatchStore,
    RepairProbe,
    check_port_range_available,
    find_next_available_port_range,
)


class ClientBatchStoreTests(unittest.TestCase):
    def test_create_append_save_and_reload_active_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client_direct_sessions.json"
            store = ClientBatchStore(path)
            batch = store.create_batch("桌面2-31号", scope="全部串行", base_port=9231, auto_enter_game=True)
            store.append_binding(
                ClientBatchBinding(
                    account_id="a1",
                    account_name="第一层-1",
                    pid=123,
                    hwnd=456,
                    cdp_port=9231,
                    login_url="https://dldl.50pk.com/login.php?gid=1&pid=1&token=t&time=1&sign=s&isPcLauncher=true",
                    status="prepared",
                )
            )
            store.save()

            loaded = ClientBatchStore(path)
            loaded.load()

            self.assertEqual(loaded.active_batch_id, batch.batch_id)
            self.assertEqual(loaded.current_batch().batch_name, "桌面2-31号")
            self.assertEqual(loaded.current_batch().bindings[0].login_url, store.current_batch().bindings[0].login_url)

    def test_batches_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            first = store.create_batch("桌面1", scope="当前层", base_port=9222)
            store.append_binding(ClientBatchBinding("a1", "账号1", pid=1, hwnd=11, cdp_port=9222, login_url="u1"))
            second = store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(ClientBatchBinding("a2", "账号2", pid=2, hwnd=22, cdp_port=9231, login_url="u2"))

            store.switch_batch(first.batch_id)
            self.assertEqual([binding.account_id for binding in store.current_batch().bindings], ["a1"])
            store.switch_batch(second.batch_id)
            self.assertEqual([binding.account_id for binding in store.current_batch().bindings], ["a2"])

    def test_append_binding_rejects_duplicate_account_and_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(ClientBatchBinding("a1", "账号1", pid=1, hwnd=11, cdp_port=9231, login_url="u1"))

            with self.assertRaises(ValueError):
                store.append_binding(ClientBatchBinding("a1", "账号1", pid=2, hwnd=22, cdp_port=9232, login_url="u2"))
            with self.assertRaises(ValueError):
                store.append_binding(ClientBatchBinding("a2", "账号2", pid=2, hwnd=22, cdp_port=9231, login_url="u2"))

    def test_port_range_precheck_reports_occupied_ports(self) -> None:
        occupied = check_port_range_available(9231, 3, port_available=lambda port: port != 9232)

        self.assertEqual(occupied, [9232])

    def test_port_range_recommendation_finds_next_continuous_range(self) -> None:
        occupied = set(range(9222, 9231))

        recommended = find_next_available_port_range(
            9222,
            31,
            port_available=lambda port: port not in occupied,
        )

        self.assertEqual(recommended, 9231)

    def test_port_range_recommendation_skips_middle_occupied_ports(self) -> None:
        occupied = {9222, 9223, 9225}

        recommended = find_next_available_port_range(
            9222,
            3,
            port_available=lambda port: port not in occupied,
        )

        self.assertEqual(recommended, 9226)

    def test_refresh_marks_pid_cdp_and_hwnd_status_without_global_takeover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(ClientBatchBinding("alive", "账号1", pid=1, hwnd=11, cdp_port=9231, login_url="u1"))
            store.append_binding(ClientBatchBinding("pid", "账号2", pid=2, hwnd=22, cdp_port=9232, login_url="u2"))
            store.append_binding(ClientBatchBinding("cdp", "账号3", pid=3, hwnd=33, cdp_port=9233, login_url="u3"))
            store.append_binding(ClientBatchBinding("hwnd", "账号4", pid=4, hwnd=44, cdp_port=9234, login_url="u4"))

            store.refresh_current_batch_status(
                pid_exists=lambda pid: pid != 2,
                cdp_available=lambda port: port != 9233,
                hwnd_valid=lambda hwnd: hwnd != 44,
            )

            statuses = {binding.account_id: binding.status for binding in store.current_batch().bindings}
            self.assertEqual(statuses["alive"], "restored")
            self.assertEqual(statuses["pid"], "pid_missing")
            self.assertEqual(statuses["cdp"], "cdp_unavailable")
            self.assertEqual(statuses["hwnd"], "hwnd_invalid")

    def test_refresh_all_batches_marks_missing_pid_without_removing_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            first = store.create_batch("桌面1", scope="当前层", base_port=9222)
            store.append_binding(ClientBatchBinding("old", "旧账号", pid=100, hwnd=11, cdp_port=9222, login_url="u1"))
            second = store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(ClientBatchBinding("new", "新账号", pid=200, hwnd=22, cdp_port=9231, login_url="u2"))

            statuses = store.refresh_all_batch_statuses(
                pid_exists=lambda pid: pid == 200,
                process_is_x5game=lambda pid: True,
                cdp_available=lambda port: True,
                hwnd_valid=lambda hwnd: True,
            )

            self.assertEqual(statuses[first.batch_id]["old"], "pid_missing")
            self.assertEqual(statuses[second.batch_id]["new"], "restored")
            self.assertEqual(len(store.batches[0].bindings), 1)

    def test_live_binding_ports_only_include_existing_x5game_pids(self) -> None:
        store = ClientBatchStore()
        store.create_batch("桌面1", scope="当前层", base_port=9222)
        store.append_binding(ClientBatchBinding("old", "旧账号", pid=100, hwnd=11, cdp_port=9222, login_url="u1"))
        store.create_batch("桌面2", scope="全部串行", base_port=9231)
        store.append_binding(ClientBatchBinding("alive", "活账号", pid=200, hwnd=22, cdp_port=9231, login_url="u2"))
        store.append_binding(ClientBatchBinding("other", "其它进程", pid=300, hwnd=33, cdp_port=9232, login_url="u3"))

        ports = store.live_binding_ports(
            pid_exists=lambda pid: pid in {200, 300},
            process_is_x5game=lambda pid: pid == 200,
        )

        self.assertEqual(ports, {9231})

    def test_delete_batch_switches_active_to_remaining_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            first = store.create_batch("批次1", scope="当前层", base_port=9222)
            second = store.create_batch("批次2", scope="当前层", base_port=9230)

            removed = store.delete_batch(second.batch_id)

            self.assertTrue(removed)
            self.assertEqual([batch.batch_id for batch in store.batches], [first.batch_id])
            self.assertEqual(store.active_batch_id, first.batch_id)

    def test_delete_last_batch_clears_active_batch_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            batch = store.create_batch("批次1", scope="当前层", base_port=9222)

            removed = store.delete_batch(batch.batch_id)

            self.assertTrue(removed)
            self.assertEqual(store.batches, [])
            self.assertEqual(store.active_batch_id, "")

    def test_cleanup_dead_batches_removes_only_zero_live_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            dead = store.create_batch("失效批次", scope="当前层", base_port=9222)
            dead.bindings = [
                ClientBatchBinding("dead", "失效", pid=100, hwnd=1, cdp_port=9222, status="pid_missing"),
            ]
            live = store.create_batch("存活批次", scope="当前层", base_port=9230)
            live.bindings = [
                ClientBatchBinding("live", "存活", pid=200, hwnd=2, cdp_port=9230, status="restored"),
            ]
            store.active_batch_id = dead.batch_id

            removed = store.cleanup_dead_batches(
                pid_exists=lambda pid: pid == 200,
                process_is_x5game=lambda pid: pid == 200,
            )

            self.assertEqual([batch.batch_id for batch in removed], [dead.batch_id])
            self.assertEqual([batch.batch_id for batch in store.batches], [live.batch_id])
            self.assertEqual(store.active_batch_id, live.batch_id)

    def test_repair_updates_hwnd_only_from_known_pid_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(ClientBatchBinding("a1", "账号1", pid=100, hwnd=11, cdp_port=9231, login_url="u1"))

            results = store.repair_current_batch_windows(
                probe=RepairProbe(
                    pid_exists=lambda pid: True,
                    process_is_x5game=lambda pid: True,
                    cdp_available=lambda port: True,
                    hwnd_for_pid=lambda pid: 999,
                )
            )

            binding = store.current_batch().bindings[0]
            self.assertEqual(results["a1"], "repaired")
            self.assertEqual(binding.hwnd, 999)
            self.assertEqual(binding.status, "repaired")


if __name__ == "__main__":
    unittest.main()
