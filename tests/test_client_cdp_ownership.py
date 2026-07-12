from __future__ import annotations

import unittest
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest import mock

from douluo_launcher.client_cdp_ownership import (
    CdpOwnershipResult,
    discover_window_cdp_endpoint,
    validate_window_cdp_endpoint,
)


class ClientCdpOwnershipTests(unittest.TestCase):
    def test_same_pid_skips_process_snapshot_even_when_snapshot_would_fail(self) -> None:
        snapshot = mock.Mock(side_effect=OSError(5, "snapshot failed"))

        result = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {200}},
            process_parents=snapshot,
            endpoint_probe=lambda _port: True,
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.relation_mode, "verified_same_pid")
        self.assertEqual(result.snapshot_attempts, 0)
        snapshot.assert_not_called()

    def test_discovers_endpoint_owned_by_window_pid_without_port_guessing(self) -> None:
        result = discover_window_cdp_endpoint(
            100,
            200,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {200}, 9238: {999}},
            process_parents=lambda: {200: 1, 999: 1},
            endpoint_probe=lambda port: port == 9237,
        )

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.port, 9237)
        self.assertEqual(result.owner_pid, 200)

    def test_accepts_verified_descendant_listener_owner(self) -> None:
        result = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {201}},
            process_parents=lambda: {200: 1, 201: 200},
            endpoint_probe=lambda _port: True,
        )

        self.assertEqual(result.status, "verified")
        self.assertEqual(result.owner_pid, 201)
        self.assertEqual(result.relation_mode, "verified_process_tree")
        self.assertEqual(result.snapshot_attempts, 1)

    def test_rejects_listener_owned_by_unrelated_process(self) -> None:
        result = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {999}},
            process_parents=lambda: {200: 1, 999: 1},
            endpoint_probe=lambda _port: True,
        )

        self.assertEqual(result.status, "cdp_owner_mismatch")
        self.assertEqual(result.owner_pid, 999)
        self.assertEqual(result.relation_mode, "process_tree_mismatch")

    def test_process_snapshot_retries_after_transient_failure(self) -> None:
        snapshots = mock.Mock(
            side_effect=[
                OSError(5, "snapshot temporarily unavailable"),
                {200: 1, 201: 200},
            ]
        )

        with mock.patch("douluo_launcher.client_cdp_ownership.time.sleep") as sleep:
            result = validate_window_cdp_endpoint(
                100,
                200,
                9237,
                hwnd_pid=lambda _hwnd: 200,
                tcp_listeners=lambda: {9237: {201}},
                process_parents=snapshots,
                endpoint_probe=lambda _port: True,
            )

        self.assertTrue(result.verified)
        self.assertEqual(result.snapshot_attempts, 2)
        self.assertIn("snapshot temporarily unavailable", result.snapshot_error)
        self.assertEqual(result.winerror, 5)
        self.assertEqual(snapshots.call_count, 2)
        sleep.assert_called_once_with(0.05)

    def test_process_snapshot_stops_after_finite_failures_with_diagnostics(self) -> None:
        snapshots = mock.Mock(side_effect=OSError(5, "snapshot unavailable"))

        with mock.patch("douluo_launcher.client_cdp_ownership.time.sleep") as sleep:
            result = validate_window_cdp_endpoint(
                100,
                200,
                9237,
                hwnd_pid=lambda _hwnd: 200,
                tcp_listeners=lambda: {9237: {201}},
                process_parents=snapshots,
                endpoint_probe=lambda _port: True,
            )

        self.assertEqual(result.status, "cdp_owner_unverified")
        self.assertEqual(result.relation_mode, "process_tree_snapshot_failed")
        self.assertEqual(result.snapshot_attempts, 3)
        self.assertIn("snapshot unavailable", result.snapshot_error)
        self.assertEqual(result.winerror, 5)
        self.assertEqual(snapshots.call_count, 3)
        self.assertEqual(sleep.call_args_list, [mock.call(0.05), mock.call(0.1)])

    def test_31_same_pid_bindings_all_verify_with_concurrency_eight(self) -> None:
        snapshot = mock.Mock(side_effect=OSError(5, "snapshot failed"))

        def verify(index: int):
            pid = 2000 + index
            port = 9200 + index
            return validate_window_cdp_endpoint(
                1000 + index,
                pid,
                port,
                hwnd_pid=lambda _hwnd, expected=pid: expected,
                tcp_listeners=lambda expected_port=port, expected_pid=pid: {expected_port: {expected_pid}},
                process_parents=snapshot,
                endpoint_probe=lambda candidate, expected=port: candidate == expected,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(verify, range(31)))

        self.assertEqual(len(results), 31)
        self.assertTrue(all(result.verified for result in results))
        self.assertTrue(all(result.relation_mode == "verified_same_pid" for result in results))
        snapshot.assert_not_called()

    def test_process_snapshots_are_serialized_across_concurrent_validations(self) -> None:
        state_lock = Lock()
        active_snapshots = 0
        max_active_snapshots = 0

        def snapshot():
            nonlocal active_snapshots, max_active_snapshots
            with state_lock:
                active_snapshots += 1
                max_active_snapshots = max(max_active_snapshots, active_snapshots)
            time.sleep(0.005)
            with state_lock:
                active_snapshots -= 1
            return {200: 1, 201: 200}

        def verify(index: int):
            return validate_window_cdp_endpoint(
                1000 + index,
                200,
                9300 + index,
                hwnd_pid=lambda _hwnd: 200,
                tcp_listeners=lambda port=9300 + index: {port: {201}},
                process_parents=snapshot,
                endpoint_probe=lambda _port: True,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(verify, range(8)))

        self.assertTrue(all(result.verified for result in results))
        self.assertEqual(max_active_snapshots, 1)

    def test_rejects_hwnd_pid_change_before_navigation(self) -> None:
        result = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 201,
            tcp_listeners=lambda: {9237: {200}},
            process_parents=lambda: {200: 1},
            endpoint_probe=lambda _port: True,
        )

        self.assertEqual(result.status, "hwnd_pid_mismatch")

    def test_rejects_missing_listener_and_unreachable_endpoint_separately(self) -> None:
        snapshot = mock.Mock(side_effect=OSError(5, "snapshot failed"))
        missing = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {},
            process_parents=lambda: {200: 1},
            endpoint_probe=lambda _port: True,
        )
        unavailable = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {200}},
            process_parents=snapshot,
            endpoint_probe=lambda _port: False,
        )

        self.assertEqual(missing.status, "cdp_port_missing")
        self.assertEqual(unavailable.status, "cdp_unavailable")
        self.assertEqual(unavailable.relation_mode, "verified_same_pid")
        self.assertEqual(unavailable.endpoint_status, "probe_failed")
        snapshot.assert_not_called()

    def test_discovery_blocks_multiple_verified_ports_in_same_process_tree(self) -> None:
        result = discover_window_cdp_endpoint(
            100,
            200,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {200}, 9238: {201}},
            process_parents=lambda: {200: 1, 201: 200},
            endpoint_probe=lambda _port: True,
        )

        self.assertEqual(result.status, "cdp_owner_conflict")
        self.assertEqual(result.port, 0)

    def test_validation_blocks_port_with_multiple_listener_owners(self) -> None:
        result = validate_window_cdp_endpoint(
            100,
            200,
            9237,
            hwnd_pid=lambda _hwnd: 200,
            tcp_listeners=lambda: {9237: {200, 999}},
            process_parents=lambda: {200: 1, 999: 1},
            endpoint_probe=lambda _port: True,
        )

        self.assertEqual(result.status, "cdp_owner_conflict")

    def test_result_message_contains_only_safe_runtime_identifiers(self) -> None:
        result = CdpOwnershipResult(
            status="cdp_owner_mismatch",
            hwnd=100,
            window_pid=200,
            port=9237,
            owner_pid=999,
            relation_mode="process_tree_mismatch",
            snapshot_attempts=1,
            snapshot_error="",
            winerror=0,
            endpoint_status="not_checked",
        )

        message = result.safe_message()
        self.assertIn("hwnd=100 pid=200 port=9237 owner_pid=999", message)
        self.assertIn("relation_mode=process_tree_mismatch", message)
        self.assertIn("snapshot_attempts=1", message)
        self.assertIn("snapshot_error=none", message)
        self.assertIn("winerror=0", message)
        self.assertIn("endpoint_status=not_checked", message)
        self.assertIn("final_status=cdp_owner_mismatch", message)


if __name__ == "__main__":
    unittest.main()
