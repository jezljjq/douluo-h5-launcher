from __future__ import annotations

import json
import socket
import unittest

from douluo_launcher.client_cdp import (
    CdpEventTracker,
    CdpMessageBuilder,
    cdp_port_for_index,
    is_tcp_port_available,
    mask_sensitive_text,
    select_page_target,
)


class ClientCdpTests(unittest.TestCase):
    def test_mask_sensitive_text_masks_url_and_json_values(self) -> None:
        text = (
            'https://dldl.50pk.com/login.php?token=abc&sign=def&IMEI=ghi&uid=123&safe=ok '
            '{"token":"abc","openid":"oid","username":"1526842081"}'
        )

        masked = mask_sensitive_text(text)

        self.assertIn("token=***MASKED***", masked)
        self.assertIn("sign=***MASKED***", masked)
        self.assertIn("IMEI=***MASKED***", masked)
        self.assertIn("uid=***MASKED***", masked)
        self.assertIn('"token":"***MASKED***"', masked)
        self.assertIn('"openid":"***MASKED***"', masked)
        self.assertIn('"username":"***MASKED***"', masked)
        self.assertIn("safe=ok", masked)
        self.assertNotIn("abc", masked)
        self.assertNotIn("1526842081", masked)

    def test_cdp_message_builder_increments_ids(self) -> None:
        builder = CdpMessageBuilder()

        first = json.loads(builder.build("Page.enable"))
        second = json.loads(builder.build("Runtime.evaluate", {"expression": "1+1"}))

        self.assertEqual(first["id"], 1)
        self.assertEqual(first["method"], "Page.enable")
        self.assertEqual(second["id"], 2)
        self.assertEqual(second["params"], {"expression": "1+1"})

    def test_tracker_recognizes_import_server_state_and_identity(self) -> None:
        tracker = CdpEventTracker()
        tracker.handle_event(
            {
                "method": "Network.responseReceived",
                "params": {
                    "requestId": "1",
                    "response": {
                        "status": 200,
                        "url": "https://app.xxh5.z7xz.com/importServer?token=secret",
                    },
                },
            }
        )

        tracker.record_response_body(
            "1",
            '{"state":1,"server":[{"serverId":83499,"uid":"secret-uid","isolduser":1}]}',
        )

        self.assertTrue(tracker.markers.import_server)
        self.assertEqual(tracker.import_server_state, 1)
        self.assertEqual(tracker.import_server_id.server_id, 83499)
        self.assertTrue(tracker.import_server_id.has_uid)

    def test_tracker_recognizes_server_mobile_state(self) -> None:
        tracker = CdpEventTracker()
        tracker.handle_event(
            {
                "method": "Network.responseReceived",
                "params": {
                    "requestId": "2",
                    "response": {
                        "status": 200,
                        "url": "https://app.xxh5.z7xz.com/serverMobile?sign=secret",
                    },
                },
            }
        )
        tracker.record_response_body("2", '{"state":1,"msg":{"server":83499}}')

        self.assertTrue(tracker.markers.server_mobile)
        self.assertEqual(tracker.server_mobile_state, 1)

    def test_tracker_recognizes_game_resources_and_websocket(self) -> None:
        tracker = CdpEventTracker()
        urls = [
            "https://res.xxh5.z7xz.com/xxh5dev3/ver20260704004349.js",
            "https://res.xxh5.z7xz.com/xxh5dev3/GameMain.max_003302.js",
            "https://res.xxh5.z7xz.com/xxh5dev3/js/login_000088.js",
            "https://res.xxh5.z7xz.com/xxh5dev3/js/main_003449.js",
            "https://res.xxh5.z7xz.com/xxh5dev3/res/pages/X5_MainTop_000012.json",
        ]
        for index, url in enumerate(urls):
            tracker.handle_event(
                {
                    "method": "Network.responseReceived",
                    "params": {"requestId": str(index), "response": {"status": 200, "url": url}},
                }
            )
        tracker.handle_event(
            {"method": "Network.webSocketCreated", "params": {"url": "wss://37wans83610.xxh5.z7xz.com:20103/"}}
        )

        self.assertTrue(tracker.markers.verjs)
        self.assertTrue(tracker.markers.game_main)
        self.assertTrue(tracker.markers.login_js)
        self.assertTrue(tracker.markers.main_js)
        self.assertTrue(tracker.markers.main_ui)
        self.assertTrue(tracker.markers.websocket)

    def test_select_page_target_prefers_login_related_page(self) -> None:
        target = select_page_target(
            [
                {"type": "page", "url": "https://example.com", "webSocketDebuggerUrl": "ws://one"},
                {"type": "page", "url": "https://app.xxh5.z7xz.com/login.php?genCode=true", "webSocketDebuggerUrl": "ws://two"},
            ]
        )

        self.assertEqual(target["webSocketDebuggerUrl"], "ws://two")

    def test_cdp_port_for_index(self) -> None:
        self.assertEqual(cdp_port_for_index(0), 9222)
        self.assertEqual(cdp_port_for_index(1), 9223)
        self.assertEqual(cdp_port_for_index(2, base_port=9300), 9302)

    def test_is_tcp_port_available_ignores_bound_but_not_listening_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            self.assertTrue(is_tcp_port_available(port))

    def test_is_tcp_port_available_detects_listening_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]

            self.assertFalse(is_tcp_port_available(port))


if __name__ == "__main__":
    unittest.main()
