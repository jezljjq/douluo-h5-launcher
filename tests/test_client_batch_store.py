import tempfile
import unittest
import os
from pathlib import Path

from douluo_launcher.client_batch_store import (
    ClientBatchBinding,
    ClientBatchStore,
    LocalClientScan,
    RepairProbe,
    check_port_range_available,
    default_sessions_path,
    find_next_available_port_range,
)


class ClientBatchStoreTests(unittest.TestCase):
    def test_default_sessions_path_uses_appdata_user_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_appdata = os.environ.get("APPDATA")
            old_override = os.environ.get("H5_LAUNCHER_DATA_DIR")
            os.environ["APPDATA"] = str(Path(tmp) / "Roaming")
            os.environ.pop("H5_LAUNCHER_DATA_DIR", None)
            try:
                self.assertEqual(
                    default_sessions_path(),
                    Path(tmp) / "Roaming" / "DouluoH5Launcher" / "client_direct_sessions.json",
                )
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata
                if old_override is None:
                    os.environ.pop("H5_LAUNCHER_DATA_DIR", None)
                else:
                    os.environ["H5_LAUNCHER_DATA_DIR"] = old_override

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

    def test_refresh_all_batches_preserves_business_status_and_records_window_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(
                ClientBatchBinding(
                    "success",
                    "成功账号",
                    pid=100,
                    hwnd=200,
                    cdp_port=9231,
                    login_url="u",
                    status="客户端登录成功",
                )
            )

            statuses = store.refresh_all_batch_statuses(
                pid_exists=lambda pid: True,
                process_is_x5game=lambda pid: True,
                cdp_available=lambda port: True,
                hwnd_valid=lambda hwnd: True,
            )

            binding = store.current_batch().bindings[0]
            self.assertEqual(statuses[store.current_batch().batch_id]["success"], "restored")
            self.assertEqual(binding.status, "客户端登录成功")
            self.assertEqual(binding.window_status, "restored")

    def test_repair_preserves_success_status_and_uses_repair_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientBatchStore(Path(tmp) / "client_direct_sessions.json")
            store.create_batch("桌面2", scope="全部串行", base_port=9231)
            store.append_binding(
                ClientBatchBinding(
                    "a1",
                    "账号1",
                    pid=100,
                    hwnd=11,
                    cdp_port=9231,
                    login_url="u1",
                    status="game_entered",
                    error_message="business note",
                )
            )

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
            self.assertEqual(binding.status, "game_entered")
            self.assertEqual(binding.error_message, "business note")
            self.assertEqual(binding.repair_status, "repaired")
            self.assertEqual(binding.window_status, "restored")

    def test_pid_not_x5game_does_not_overwrite_business_status_or_count_as_live(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("桌面2", scope="全部串行", base_port=9231)
        store.append_binding(
            ClientBatchBinding("a1", "账号1", pid=100, hwnd=11, cdp_port=9231, login_url="u1", status="客户端登录成功")
        )

        results = store.refresh_all_batch_statuses(
            pid_exists=lambda pid: True,
            process_is_x5game=lambda pid: False,
            cdp_available=lambda port: True,
            hwnd_valid=lambda hwnd: True,
        )

        binding = batch.bindings[0]
        self.assertEqual(results[batch.batch_id]["a1"], "pid_not_x5game")
        self.assertEqual(binding.status, "客户端登录成功")
        self.assertEqual(binding.window_status, "pid_not_x5game")
        self.assertEqual(
            store.batch_live_count(batch, pid_exists=lambda pid: True, process_is_x5game=lambda pid: False),
            0,
        )

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

    def test_identify_local_clients_adds_missing_bindings_without_overwriting_existing_business_status(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("当前批次", scope="当前层", base_port=9222)
        store.append_binding(
            ClientBatchBinding(
                "old",
                "旧账号",
                pid=100,
                hwnd=1000,
                cdp_port=9222,
                login_url="https://example.com/login.php?token=secret&sign=secret",
                status="客户端登录成功",
            )
        )

        result = store.identify_local_clients(
            [
                LocalClientScan(pid=100, hwnd=1000, title="斗罗大陆H5-1号", cdp_port=9222, cdp_available=True),
                LocalClientScan(pid=101, hwnd=1001, title="斗罗大陆H5-2号", cdp_port=9223, cdp_available=True),
                LocalClientScan(pid=102, hwnd=1002, title="斗罗大陆H5-3号", cdp_port=9224, cdp_available=True),
            ]
        )

        self.assertEqual(result["scanned"], 3)
        self.assertEqual(result["existing"], 1)
        self.assertEqual(result["added"], 2)
        self.assertEqual(len(batch.bindings), 3)
        self.assertEqual(batch.bindings[0].status, "客户端登录成功")
        self.assertEqual(batch.bindings[0].window_status, "restored")
        added = batch.bindings[1:]
        self.assertEqual([binding.source for binding in added], ["local_scan", "local_scan"])
        self.assertEqual([binding.status for binding in added], ["pending", "pending"])
        self.assertEqual([binding.window_status for binding in added], ["restored", "restored"])
        self.assertEqual([binding.repair_status for binding in added], ["restored", "restored"])
        self.assertEqual([(binding.pid, binding.hwnd, binding.cdp_port) for binding in added], [(101, 1001, 9223), (102, 1002, 9224)])

    def test_identify_local_clients_marks_invalid_scan_states_without_deleting_bindings(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("当前批次", scope="当前层", base_port=9222)

        result = store.identify_local_clients(
            [
                LocalClientScan(pid=201, hwnd=2001, title="CDP坏", cdp_port=9222, cdp_available=False),
                LocalClientScan(pid=202, hwnd=2002, title="其它进程", cdp_port=9223, cdp_available=True, is_x5game=False),
                LocalClientScan(pid=203, hwnd=0, title="无窗口", cdp_port=9224, cdp_available=True),
            ]
        )

        self.assertEqual(result["added"], 3)
        self.assertEqual(result["cdp_unavailable"], 1)
        self.assertEqual(result["binding_invalid"], 2)
        self.assertEqual(len(batch.bindings), 3)
        self.assertEqual([binding.window_status for binding in batch.bindings], ["cdp_unavailable", "pid_not_x5game", "hwnd_invalid"])
        self.assertEqual([binding.repair_status for binding in batch.bindings], ["cdp_unavailable", "pid_not_x5game", "hwnd_invalid"])
        self.assertEqual([binding.status for binding in batch.bindings], ["pending", "pending", "pending"])

    def test_identify_local_clients_keeps_current_scan_collection_instead_of_splitting_by_history_ranges(self) -> None:
        store = ClientBatchStore()
        batch1 = store.create_batch("桌面1-1号", scope="当前层", base_port=9222)
        store.append_binding(ClientBatchBinding("old-1", "旧1", pid=1001, hwnd=2001, cdp_port=9222, status="客户端登录成功"))
        batch2 = store.create_batch("桌面2-10号", scope="当前层", base_port=9231)
        store.append_binding(ClientBatchBinding("old-10", "旧10", pid=1010, hwnd=2010, cdp_port=9231, status="客户端登录成功"))
        batch3 = store.create_batch("桌面3-19号", scope="当前层", base_port=9240)
        store.append_binding(ClientBatchBinding("old-19", "旧19", pid=1019, hwnd=2019, cdp_port=9240, status="客户端登录成功"))
        store.switch_batch(batch2.batch_id)
        scans = [
            LocalClientScan(
                pid=1000 + index,
                hwnd=2000 + index,
                title=f"斗罗大陆H5-{index}号",
                cdp_port=9221 + index,
                cdp_available=True,
            )
            for index in range(1, 28)
        ]

        result = store.identify_local_clients(scans)

        self.assertEqual(result["scanned"], 27)
        self.assertEqual(result["restored_batches"], 0)
        self.assertEqual(result["created_batches"], 1)
        self.assertEqual(result["unassigned"], 0)
        self.assertEqual([len(batch.bindings) for batch in store.batches], [1, 1, 1, 27])
        self.assertNotEqual(store.active_batch_id, batch2.batch_id)
        self.assertEqual([binding.cdp_port for binding in batch1.bindings], [9222])
        self.assertEqual([binding.cdp_port for binding in batch2.bindings], [9231])
        self.assertEqual([binding.cdp_port for binding in batch3.bindings], [9240])
        self.assertEqual([binding.cdp_port for binding in store.current_batch().bindings], list(range(9222, 9249)))
        self.assertEqual(batch2.bindings[0].status, "客户端登录成功")
        self.assertTrue(all(binding.window_status == "restored" for binding in store.current_batch().bindings))

    def test_identify_local_clients_creates_new_batch_when_scan_is_subset_of_large_history_batch(self) -> None:
        store = ClientBatchStore()
        old_batch = store.create_batch("本地识别-端口9222~9252", scope="本地识别", base_port=9222)
        for index, port in enumerate(range(9222, 9253), start=1):
            store.append_binding(
                ClientBatchBinding(
                    f"old-{index}",
                    f"旧{index}",
                    pid=1000 + index,
                    hwnd=2000 + index,
                    cdp_port=port,
                    status="客户端登录成功",
                )
            )

        result = store.identify_local_clients(
            [
                LocalClientScan(
                    pid=3000 + index,
                    hwnd=4000 + index,
                    title=f"斗罗大陆H5-{index}号",
                    cdp_port=9221 + index,
                    cdp_available=True,
                )
                for index in range(1, 10)
            ]
        )

        self.assertEqual(result["restored_batches"], 0)
        self.assertEqual(result["created_batches"], 1)
        self.assertEqual([len(batch.bindings) for batch in store.batches], [31, 9])
        self.assertEqual(store.batches[0].batch_id, old_batch.batch_id)
        self.assertEqual([binding.status for binding in old_batch.bindings], ["客户端登录成功"] * 31)
        self.assertEqual(store.current_batch().batch_name, "当前桌面识别-9窗-端口9222~9230")
        self.assertEqual([binding.cdp_port for binding in store.current_batch().bindings], list(range(9222, 9231)))
        self.assertTrue(any("数量差距较大" in note for note in result["notes"]))

    def test_identify_local_clients_creates_new_batch_when_history_is_subset_of_large_scan(self) -> None:
        store = ClientBatchStore()
        old_batch = store.create_batch("当前桌面识别-9窗-端口9222~9230", scope="本地识别", base_port=9222)
        for index, port in enumerate(range(9222, 9231), start=1):
            store.append_binding(
                ClientBatchBinding(
                    f"old-{index}",
                    f"旧{index}",
                    pid=1000 + index,
                    hwnd=2000 + index,
                    cdp_port=port,
                    status="客户端登录成功",
                )
            )

        result = store.identify_local_clients(
            [
                LocalClientScan(
                    pid=3000 + index,
                    hwnd=4000 + index,
                    title=f"斗罗大陆H5-{index}号",
                    cdp_port=9221 + index,
                    cdp_available=True,
                )
                for index in range(1, 32)
            ]
        )

        self.assertEqual(result["restored_batches"], 0)
        self.assertEqual(result["created_batches"], 1)
        self.assertEqual([len(batch.bindings) for batch in store.batches], [9, 31])
        self.assertEqual(store.batches[0].batch_id, old_batch.batch_id)
        self.assertEqual(store.current_batch().batch_name, "当前桌面识别-31窗-端口9222~9252")
        self.assertEqual([binding.cdp_port for binding in store.current_batch().bindings], list(range(9222, 9253)))
        self.assertTrue(any("数量差距较大" in note for note in result["notes"]))

    def test_identify_local_clients_same_port_count_but_different_pid_hwnd_creates_new_batch(self) -> None:
        store = ClientBatchStore()
        old_batch = store.create_batch("当前桌面识别-9窗-端口9222~9230", scope="本地识别", base_port=9222)
        for index, port in enumerate(range(9222, 9231), start=1):
            store.append_binding(
                ClientBatchBinding(
                    f"old-{index}",
                    f"旧{index}",
                    pid=1000 + index,
                    hwnd=2000 + index,
                    cdp_port=port,
                    status="客户端登录成功",
                )
            )

        result = store.identify_local_clients(
            [
                LocalClientScan(
                    pid=3000 + index,
                    hwnd=4000 + index,
                    title=f"斗罗大陆H5-{index}号",
                    cdp_port=9221 + index,
                    cdp_available=True,
                )
                for index in range(1, 10)
            ]
        )

        self.assertEqual(result["restored_batches"], 0)
        self.assertEqual(result["created_batches"], 1)
        self.assertEqual([len(batch.bindings) for batch in store.batches], [9, 9])
        self.assertEqual(store.batches[0].batch_id, old_batch.batch_id)
        self.assertEqual(store.current_batch().batch_name, "当前桌面识别-9窗-端口9222~9230-2")
        self.assertEqual([binding.pid for binding in old_batch.bindings], list(range(1001, 1010)))
        self.assertTrue(any("pid/hwnd 集合不同" in note for note in result["notes"]))

    def test_identify_local_clients_same_pid_hwnd_restores_history_batch(self) -> None:
        store = ClientBatchStore()
        old_batch = store.create_batch("当前桌面识别-9窗-端口9222~9230", scope="本地识别", base_port=9222)
        for index, port in enumerate(range(9222, 9231), start=1):
            store.append_binding(
                ClientBatchBinding(
                    f"old-{index}",
                    f"旧{index}",
                    pid=1000 + index,
                    hwnd=2000 + index,
                    cdp_port=port,
                    status="客户端登录成功",
                )
            )

        result = store.identify_local_clients(
            [
                LocalClientScan(
                    pid=1000 + index,
                    hwnd=2000 + index,
                    title=f"斗罗大陆H5-{index}号",
                    cdp_port=9221 + index,
                    cdp_available=True,
                )
                for index in range(1, 10)
            ]
        )

        self.assertEqual(result["restored_batches"], 1)
        self.assertEqual(result["created_batches"], 0)
        self.assertEqual(len(store.batches), 1)
        self.assertEqual(store.active_batch_id, old_batch.batch_id)
        self.assertEqual([binding.status for binding in old_batch.bindings], ["客户端登录成功"] * 9)
        self.assertTrue(all(binding.window_status == "restored" for binding in old_batch.bindings))

    def test_identify_local_clients_inferred_ports_do_not_strong_match_history_batch(self) -> None:
        store = ClientBatchStore()
        old_batch = store.create_batch("当前桌面识别-9窗-端口9222~9230", scope="本地识别", base_port=9222)
        for index, port in enumerate(range(9222, 9231), start=1):
            store.append_binding(
                ClientBatchBinding(
                    f"old-{index}",
                    f"旧{index}",
                    pid=1000 + index,
                    hwnd=2000 + index,
                    cdp_port=port,
                    status="客户端登录成功",
                )
            )

        result = store.identify_local_clients(
            [
                LocalClientScan(
                    pid=3000 + index,
                    hwnd=4000 + index,
                    title=f"斗罗大陆H5-{index}号",
                    cdp_port=9221 + index,
                    cdp_available=True,
                    cdp_port_inferred=True,
                )
                for index in range(1, 10)
            ]
        )

        self.assertEqual(result["restored_batches"], 0)
        self.assertEqual(result["created_batches"], 1)
        self.assertEqual([len(batch.bindings) for batch in store.batches], [9, 9])
        self.assertTrue(any("推断端口" in note for note in result["notes"]))

    def test_identify_local_clients_puts_unknown_windows_in_unassigned_batch(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("桌面1-1号", scope="当前层", base_port=9222)
        store.append_binding(ClientBatchBinding("old-1", "旧1", pid=1001, hwnd=2001, cdp_port=9222, status="客户端登录成功"))

        result = store.identify_local_clients(
            [
                LocalClientScan(pid=5001, hwnd=6001, title="未知客户端", cdp_port=9500, cdp_available=True),
            ]
        )

        self.assertEqual(result["unassigned"], 1)
        self.assertEqual(len(store.batches), 2)
        self.assertEqual(store.batches[0].batch_name, "桌面1-1号")
        self.assertEqual(store.batches[1].batch_name, "未归属本地客户端")
        self.assertEqual(store.batches[1].bindings[0].source, "local_scan")
        self.assertEqual(store.batches[1].bindings[0].window_status, "restored")


if __name__ == "__main__":
    unittest.main()
