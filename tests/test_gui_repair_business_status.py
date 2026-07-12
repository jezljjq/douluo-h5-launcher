import unittest
from types import SimpleNamespace

from douluo_launcher.client_batch_store import ClientBatchBinding, ClientBatchStore
from douluo_launcher.gui import LauncherApp


class GuiRepairBusinessStatusTests(unittest.TestCase):
    def test_previous_window_error_is_not_restored_after_successful_repair(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("旧批次", scope="当前层", base_port=9271)
        binding = ClientBatchBinding(
            "a1",
            "账号1",
            pid=100,
            hwnd=200,
            cdp_port=9271,
            status="pid_not_x5game",
            error_message="旧窗口状态错误",
        )
        store.append_binding(binding)

        LauncherApp._client_direct_restore_repaired_business_statuses(
            SimpleNamespace(),
            batch,
            {"a1": ("pid_not_x5game", "", "", "旧窗口状态错误")},
            {"a1": "repaired"},
            set(),
        )

        self.assertEqual(binding.status, "客户端已就绪")
        self.assertEqual(binding.error_message, "")

    def test_real_login_status_is_preserved_after_successful_repair(self) -> None:
        store = ClientBatchStore()
        batch = store.create_batch("旧批次", scope="当前层", base_port=9271)
        binding = ClientBatchBinding(
            "a1",
            "账号1",
            pid=100,
            hwnd=200,
            cdp_port=9271,
            status="pid_not_x5game",
            login_status="客户端登录成功",
            error_message="旧窗口状态错误",
        )
        store.append_binding(binding)

        LauncherApp._client_direct_restore_repaired_business_statuses(
            SimpleNamespace(),
            batch,
            {"a1": ("pid_not_x5game", "", "客户端登录成功", "旧窗口状态错误")},
            {"a1": "repaired"},
            set(),
        )

        self.assertEqual(binding.status, "客户端登录成功")
        self.assertEqual(binding.error_message, "")


if __name__ == "__main__":
    unittest.main()
