from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from douluo_launcher.client_cdp import CdpEventMarkers, ImportServerIdentity
from douluo_launcher.client_direct_login import (
    ClientBinding,
    ClientDirectLoginConfig,
    ClientRuntimeState,
    DirectLoginCheck,
    PreparedClientDirectLoginConfig,
    is_auto_enter_success,
    is_complete_direct_login_url,
    is_no_enter_success,
    execute_prepared_client_direct_login,
    prepare_client_direct_client,
    wait_for_client_hwnd_by_pid,
)


class ClientDirectLoginTests(unittest.TestCase):
    def test_is_complete_direct_login_url_accepts_known_signed_pc_launcher_entries(self) -> None:
        query = "gid=1002997&pid=1&token=t&time=123&sign=s&appVer=&platCode=37wan&IMEI=i&isPcLauncher=true"

        self.assertTrue(is_complete_direct_login_url(f"https://dldl.50pk.com/login.php?{query}"))
        self.assertTrue(is_complete_direct_login_url(f"https://app.xxh5.z7xz.com/login.php?{query}"))
        self.assertTrue(is_complete_direct_login_url(f"https://7tu7tu.com/dldl?{query}"))

    def test_is_complete_direct_login_url_rejects_qr_and_incomplete_urls(self) -> None:
        good = (
            "https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&"
            "sign=s&appVer=&platCode=37wan&IMEI=i&isPcLauncher=true"
        )

        self.assertFalse(is_complete_direct_login_url("https://dldl.50pk.com/login.php?genCode=true&lid=85"))
        self.assertFalse(is_complete_direct_login_url("https://7tu7tu.com/dldl?genCode=true"))
        self.assertFalse(is_complete_direct_login_url(good.replace("&token=t", "")))
        self.assertFalse(is_complete_direct_login_url(good.replace("&sign=s", "")))
        self.assertFalse(is_complete_direct_login_url(good.replace("&time=123", "")))
        self.assertFalse(is_complete_direct_login_url(good.replace("isPcLauncher=true", "isPcLauncher=false")))

    def test_client_binding_preserves_account_pid_hwnd_port(self) -> None:
        binding = ClientBinding(
            account_id="第一层-1",
            account_name="一号",
            pid=1234,
            hwnd=5678,
            cdp_port=9222,
            login_url="https://7tu7tu.com/dldl?token=t",
            status="客户端已就绪",
        )

        self.assertEqual(binding.account_id, "第一层-1")
        self.assertEqual(binding.account_name, "一号")
        self.assertEqual(binding.pid, 1234)
        self.assertEqual(binding.hwnd, 5678)
        self.assertEqual(binding.cdp_port, 9222)
        self.assertEqual(binding.login_url, "https://7tu7tu.com/dldl?token=t")
        self.assertEqual(binding.status, "客户端已就绪")

    def test_wait_for_client_hwnd_by_pid_uses_pid_lister(self) -> None:
        calls: list[int] = []

        def lister(pid: int):
            calls.append(pid)
            return [5678]

        self.assertEqual(wait_for_client_hwnd_by_pid(1234, timeout=0.1, hwnd_lister=lister), 5678)
        self.assertEqual(calls, [1234])

    def test_prepare_client_direct_client_starts_and_binds_without_navigation(self) -> None:
        config = ClientDirectLoginConfig(
            account_id="第一层-1",
            account_name="一号",
            full_login_url="https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            x5game_path=r"E:\Program Files\DLH5\X5Game.exe",
            cdp_port=9222,
        )
        process = SimpleNamespace(pid=1234)

        with mock.patch("douluo_launcher.client_direct_login.start_x5game_with_cdp", return_value=process), mock.patch(
            "douluo_launcher.client_direct_login.wait_for_client_hwnd_by_pid",
            return_value=5678,
        ), mock.patch(
            "douluo_launcher.client_direct_login.wait_for_cdp_targets",
            return_value=[{"type": "page", "url": "about:blank", "webSocketDebuggerUrl": "ws://one"}],
        ), mock.patch("douluo_launcher.client_direct_login.RawCdpClient") as raw_cdp:
            result = prepare_client_direct_client(config)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "客户端已启动")
        self.assertEqual(result.binding.pid, 1234)
        self.assertEqual(result.binding.hwnd, 5678)
        self.assertEqual(result.binding.cdp_port, 9222)
        self.assertEqual(result.binding.status, "待登录")
        raw_cdp.assert_not_called()

    def test_no_enter_success_requires_import_server_identity_and_notice(self) -> None:
        check = DirectLoginCheck(
            markers=CdpEventMarkers(import_server=True, game_notice=True),
            import_server_state=1,
            import_server_id=ImportServerIdentity(server_id=83499, has_uid=True),
            runtime=ClientRuntimeState(client_alive=True, has_x5web_app=True, has_enter_game_function=True),
        )

        self.assertTrue(is_no_enter_success(check))

    def test_no_enter_success_rejects_missing_uid(self) -> None:
        check = DirectLoginCheck(
            markers=CdpEventMarkers(import_server=True, game_notice=True),
            import_server_state=1,
            import_server_id=ImportServerIdentity(server_id=83499, has_uid=False),
            runtime=ClientRuntimeState(client_alive=True, has_x5web_app=True, has_enter_game_function=True),
        )

        self.assertFalse(is_no_enter_success(check))

    def test_auto_enter_success_requires_server_mobile_game_runtime_and_visible_canvas(self) -> None:
        check = DirectLoginCheck(
            markers=CdpEventMarkers(
                import_server=True,
                server_mobile=True,
                game_main=True,
                main_js=True,
                main_ui=True,
            ),
            import_server_state=1,
            import_server_id=ImportServerIdentity(server_id=83499, has_uid=True),
            server_mobile_state=1,
            runtime=ClientRuntimeState(
                client_alive=True,
                canvas_count=2,
                visible_canvas=True,
                has_com_game=True,
                has_app_params=True,
                server=83499,
                ip="37wans83610.xxh5.z7xz.com",
                port=20003,
                is_pc_launch=True,
            ),
        )

        self.assertTrue(is_auto_enter_success(check))

    def test_auto_enter_success_rejects_missing_server_mobile_state(self) -> None:
        check = DirectLoginCheck(
            markers=CdpEventMarkers(import_server=True, server_mobile=True, game_main=True, main_js=True),
            import_server_state=1,
            import_server_id=ImportServerIdentity(server_id=83499, has_uid=True),
            server_mobile_state=0,
            runtime=ClientRuntimeState(
                client_alive=True,
                canvas_count=1,
                visible_canvas=True,
                has_com_game=True,
                has_app_params=True,
                server=83499,
                ip="37wans83610.xxh5.z7xz.com",
                port=20003,
                is_pc_launch=True,
            ),
        )

        self.assertFalse(is_auto_enter_success(check))

    def test_prepared_login_processes_speed_panel_with_safe_hook_stages(self) -> None:
        config = PreparedClientDirectLoginConfig(
            account_id="第一层-1",
            account_name="一号",
            full_login_url="https://7tu7tu.com/dldl?gid=1002997&pid=1&token=t&time=123&sign=s&isPcLauncher=true",
            cdp_port=9222,
            auto_enter_game=True,
            timeout=1.0,
            speed_panel_remove_original_toggle=False,
        )
        binding = ClientBinding("第一层-1", "一号", pid=1234, hwnd=5678, cdp_port=9222, login_url=config.full_login_url)
        cdp_instance = mock.Mock()
        runtime_payload = {
            "canvasCount": 1,
            "visibleCanvas": True,
            "hasComGame": True,
            "hasAppParams": True,
            "hasX5WebApp": True,
            "hasEnterGameFunction": True,
            "params": {"SERVER": 83499, "IP": "127.0.0.1", "PORT": 20003, "isPcLaunch": True},
        }
        cdp_instance.evaluate.side_effect = [runtime_payload, "called", runtime_payload, runtime_payload]

        def mark_ready(_deadline, _cdp, tracker, predicate, *, stop_event):
            tracker.markers.import_server = True
            tracker.import_server_state = 1
            tracker.import_server_id = ImportServerIdentity(server_id=83499, has_uid=True)
            tracker.markers.game_notice = True
            tracker.markers.server_mobile = True
            tracker.server_mobile_state = 1
            tracker.markers.game_main = True
            tracker.markers.main_js = True
            self.assertTrue(predicate())

        with mock.patch("douluo_launcher.client_direct_login.wait_for_cdp_targets", return_value=[{"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"}]), mock.patch(
            "douluo_launcher.client_direct_login.select_page_target",
            return_value={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/1"},
        ), mock.patch("douluo_launcher.client_direct_login.RawCdpClient", return_value=cdp_instance), mock.patch(
            "douluo_launcher.client_direct_login._wait_until",
            side_effect=mark_ready,
        ), mock.patch("douluo_launcher.client_direct_login._binding_alive", return_value=True), mock.patch(
            "douluo_launcher.client_direct_login.process_client_speed_panel"
        ) as process_panel:
            result = execute_prepared_client_direct_login(config, binding)

        self.assertTrue(result.success)
        self.assertEqual(process_panel.call_count, 3)
        self.assertEqual(
            [call.kwargs["trigger_stage"] for call in process_panel.call_args_list],
            ["after_navigate", "after_game_ready", "after_game_ready"],
        )
        self.assertFalse(process_panel.call_args_list[0].args[1].speed_panel_remove_original_toggle)


if __name__ == "__main__":
    unittest.main()
