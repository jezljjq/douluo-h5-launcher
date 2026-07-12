from __future__ import annotations

import unittest
from threading import Event
from unittest import mock

from douluo_launcher.client_batch_store import ClientBatchBinding
from douluo_launcher.client_cdp_ownership import CdpOwnershipResult
from douluo_launcher.client_speed_control import (
    SpeedApplyResult,
    apply_speed_rate_to_binding,
    run_speed_control_batch,
    toggle_speed_tree_for_binding,
)
from douluo_launcher.client_speed_panel import ClientSpeedPanelConfig


class FakeCdp:
    def __init__(self, _url: str) -> None:
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def enable_default_domains(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def binding(account_id: str = "a1", *, speed_rate: float = 1.0) -> ClientBatchBinding:
    return ClientBatchBinding(
        account_id,
        f"账号{account_id}",
        pid=100,
        hwnd=200,
        cdp_port=9222,
        status="客户端登录成功",
        window_status="restored",
        speed_rate=speed_rate,
    )


class ClientSpeedControlTests(unittest.TestCase):
    def test_hotkey_toggle_blocks_unverified_binding_before_cdp(self) -> None:
        target_loader = mock.Mock()
        result = toggle_speed_tree_for_binding(
            binding(),
            ownership_validator=lambda *_args: CdpOwnershipResult(
                "cdp_owner_mismatch", hwnd=200, window_pid=100, port=9222, owner_pid=999
            ),
            target_loader=target_loader,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "ownership_failed")
        target_loader.assert_not_called()

    def test_hotkey_toggle_uses_verified_binding_and_only_toggles_tree(self) -> None:
        class ToggleCdp(FakeCdp):
            expression = ""

            def evaluate(self, expression: str):
                self.expression = expression
                return {"ok": True, "expanded": True}

        instance = ToggleCdp("ws://local")
        result = toggle_speed_tree_for_binding(
            binding(),
            ownership_validator=lambda *_args: CdpOwnershipResult(
                "verified", hwnd=200, window_pid=100, port=9222, owner_pid=100
            ),
            target_loader=lambda _port, timeout: [{"webSocketDebuggerUrl": "ws://local"}],
            target_selector=lambda targets: targets[0],
            cdp_factory=lambda _url: instance,
        )

        self.assertTrue(result.success)
        self.assertIn("__H5_SPEED_TREE_TOGGLE__", instance.expression)
        self.assertNotIn("__H5_SPEED_APPLY__", instance.expression)
        self.assertTrue(instance.closed)

    def test_ownership_failure_blocks_target_connection_and_apply(self) -> None:
        target_loader = mock.Mock()
        apply_func = mock.Mock()
        ownership_validator = mock.Mock(
            return_value=CdpOwnershipResult(
                "cdp_owner_mismatch",
                hwnd=200,
                window_pid=100,
                port=9222,
                owner_pid=999,
            )
        )

        result = apply_speed_rate_to_binding(
            binding(),
            50,
            ClientSpeedPanelConfig(),
            ownership_validator=ownership_validator,
            target_loader=target_loader,
            apply_func=apply_func,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "ownership_failed")
        ownership_validator.assert_called_once_with(200, 100, 9222)
        target_loader.assert_not_called()
        apply_func.assert_not_called()

    def test_apply_ok_false_is_failure(self) -> None:
        result = apply_speed_rate_to_binding(
            binding(),
            50,
            ClientSpeedPanelConfig(),
            ownership_validator=lambda *_args: CdpOwnershipResult(
                "verified", hwnd=200, window_pid=100, port=9222, owner_pid=100
            ),
            target_loader=lambda _port, timeout: [{"webSocketDebuggerUrl": "ws://local"}],
            target_selector=lambda targets: targets[0],
            cdp_factory=FakeCdp,
            apply_func=lambda *_args, **_kwargs: {"ok": False, "reason": "hook rejected"},
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "apply_failed")
        self.assertIn("hook rejected", result.message)

    def test_confirmed_apply_returns_success(self) -> None:
        result = apply_speed_rate_to_binding(
            binding(),
            500,
            ClientSpeedPanelConfig(),
            ownership_validator=lambda *_args: CdpOwnershipResult(
                "verified", hwnd=200, window_pid=100, port=9222, owner_pid=100
            ),
            target_loader=lambda _port, timeout: [{"webSocketDebuggerUrl": "ws://local"}],
            target_selector=lambda targets: targets[0],
            cdp_factory=FakeCdp,
            apply_func=lambda *_args, **_kwargs: {"ok": True, "current": 500},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "applied")

    def test_batch_continues_and_only_success_persists_rate_without_status_changes(self) -> None:
        first = binding("a1", speed_rate=1)
        second = binding("a2", speed_rate=2)
        third = binding("a3", speed_rate=5)
        original_statuses = [(item.status, item.window_status, item.login_status) for item in (first, second, third)]

        def apply(item, _rate):
            if item.account_id == "a2":
                return SpeedApplyResult(False, "apply_failed", "rejected")
            return SpeedApplyResult(True, "applied", "ok")

        summary = run_speed_control_batch(
            [first, second, third],
            50,
            stop_event=Event(),
            skip_reason=lambda _item: "",
            apply_binding=apply,
        )

        self.assertEqual((summary.success, summary.failed, summary.skipped, summary.stopped), (2, 1, 0, 0))
        self.assertEqual((first.speed_rate, second.speed_rate, third.speed_rate), (50, 2, 50))
        self.assertEqual(
            [(item.status, item.window_status, item.login_status) for item in (first, second, third)],
            original_statuses,
        )

    def test_stop_after_first_does_not_start_following_bindings(self) -> None:
        stop_event = Event()
        started: list[str] = []

        def apply(item, _rate):
            started.append(item.account_id)
            stop_event.set()
            return SpeedApplyResult(True, "applied", "ok")

        summary = run_speed_control_batch(
            [binding("a1"), binding("a2"), binding("a3")],
            5,
            stop_event=stop_event,
            skip_reason=lambda _item: "",
            apply_binding=apply,
        )

        self.assertEqual(started, ["a1"])
        self.assertEqual((summary.success, summary.stopped), (1, 2))
        self.assertEqual([item.status for item in summary.outcomes], ["success", "stopped", "stopped"])

    def test_failure_log_masks_sensitive_values(self) -> None:
        logs: list[str] = []

        run_speed_control_batch(
            [binding()],
            2,
            stop_event=Event(),
            skip_reason=lambda _item: "",
            apply_binding=lambda *_args: SpeedApplyResult(
                False,
                "apply_failed",
                "https://example.test/?token=secret&sign=private",
            ),
            log=logs.append,
        )

        joined = "\n".join(logs)
        self.assertNotIn("secret", joined)
        self.assertNotIn("private", joined)


if __name__ == "__main__":
    unittest.main()
