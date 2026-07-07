import unittest

from douluo_launcher.client_speed_panel import (
    CUSTOM_SPEED_PANEL_ID,
    ClientSpeedPanelConfig,
    build_custom_speed_panel_script,
    build_hide_original_speed_overlay_script,
    build_speed_new_document_script,
    build_speed_navigation_guard_script,
    apply_speed_rate_to_cdp,
    install_speed_navigation_guard,
    process_client_speed_panel,
)


class FakeCdp:
    def __init__(self, results=None) -> None:
        self.expressions: list[str] = []
        self.results = list(results or [])

    def evaluate(self, expression: str):
        self.expressions.append(expression)
        if self.results:
            return self.results.pop(0)
        return {}


class ClientSpeedPanelTests(unittest.TestCase):
    def test_after_navigate_default_stage_only_hides_original_overlay(self) -> None:
        cdp = FakeCdp(results=[{"hidden": True}])
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(), trigger_stage="after_navigate", log=logs.append)

        self.assertEqual(len(cdp.expressions), 1)
        self.assertIn("请选择加速倍率", cdp.expressions[0])
        self.assertIn("[客户端直登] 原加速浮层隐藏：隐藏数量=1", logs)

    def test_after_game_ready_injects_timer_hook_panel(self) -> None:
        cdp = FakeCdp(
            results=[
                {"hidden": False, "observerInstalled": True},
                {"ok": True, "engine": "timer_hook", "panel": "speed-hack-panel", "current": 1.0},
                {"hidden": True, "hiddenCount": 1, "observerInstalled": False},
            ]
        )
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(), trigger_stage="after_game_ready", log=logs.append)

        self.assertEqual(len(cdp.expressions), 3)
        self.assertIn(CUSTOM_SPEED_PANEL_ID, cdp.expressions[1])
        self.assertIn("__H5_SPEED_HOOK_INSTALLED__", cdp.expressions[1])
        self.assertIn("__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__", cdp.expressions[2])
        self.assertIn("[客户端直登] 原加速浮层隐藏：隐藏数量=1", logs)

    def test_disabled_options_skip_matching_evaluate_calls(self) -> None:
        cdp = FakeCdp()

        process_client_speed_panel(
            cdp,
            ClientSpeedPanelConfig(auto_replace_speed_panel=False, custom_speed_panel_enabled=False),
        )

        self.assertEqual(cdp.expressions, [])

    def test_after_navigate_can_inject_when_configured(self) -> None:
        cdp = FakeCdp(
            results=[
                {"hidden": False},
                {"ok": True, "engine": "timer_hook", "panel": "speed-hack-panel", "current": 1.0},
                {"hidden": False},
            ]
        )

        process_client_speed_panel(
            cdp,
            ClientSpeedPanelConfig(speed_hook_stage="after_navigate"),
            trigger_stage="after_navigate",
        )

        self.assertEqual(len(cdp.expressions), 3)
        self.assertIn("__H5_SPEED_HOOK_INSTALLED__", cdp.expressions[1])

    def test_navigation_guard_blocks_context_menu_when_enabled(self) -> None:
        script = build_speed_navigation_guard_script(ClientSpeedPanelConfig(block_browser_context_menu=True))

        self.assertIn("__H5_SPEED_NAV_GUARD_INSTALLED__", script)
        self.assertIn("contextmenu", script)
        self.assertIn("preventDefault", script)
        self.assertIn("__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__", script)

    def test_navigation_guard_does_not_block_context_menu_when_disabled(self) -> None:
        script = build_speed_navigation_guard_script(ClientSpeedPanelConfig(block_browser_context_menu=False))

        self.assertIn("__H5_SPEED_NAV_GUARD_INSTALLED__", script)
        self.assertNotIn("preventDefault", script)

    def test_install_navigation_guard_uses_new_document_script_and_current_page(self) -> None:
        class GuardCdp(FakeCdp):
            def __init__(self) -> None:
                super().__init__()
                self.sent: list[tuple[str, dict | None]] = []

            def send(self, method: str, params: dict | None = None, *, timeout: float = 10.0) -> dict:
                self.sent.append((method, params))
                return {"identifier": "guard"}

        cdp = GuardCdp()

        install_speed_navigation_guard(cdp, ClientSpeedPanelConfig(block_browser_context_menu=True))

        self.assertEqual(cdp.sent[0][0], "Page.addScriptToEvaluateOnNewDocument")
        self.assertIn("__H5_SPEED_NAV_GUARD_INSTALLED__", cdp.sent[0][1]["source"])
        self.assertIn("window.__H5_SPEED_APPLY__", cdp.sent[0][1]["source"])
        self.assertIn("__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__", cdp.sent[0][1]["source"])
        self.assertIn("__H5_SPEED_NAV_GUARD_INSTALLED__", cdp.expressions[0])

    def test_new_document_script_contains_hide_hook_panel_and_guard(self) -> None:
        script = build_speed_new_document_script(ClientSpeedPanelConfig(default_speed_rate=50))

        self.assertIn("__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__", script)
        self.assertIn("window.__H5_SPEED_APPLY__", script)
        self.assertIn("__H5_SPEED_NAV_GUARD_INSTALLED__", script)
        self.assertIn("50", script)

    def test_apply_speed_rate_uses_existing_hook_directly(self) -> None:
        cdp = FakeCdp(results=[True, {"ok": True, "current": 50}])

        result = apply_speed_rate_to_cdp(cdp, 50, ClientSpeedPanelConfig())

        self.assertEqual(result["current"], 50)
        self.assertEqual(len(cdp.expressions), 2)
        self.assertIn("typeof window.__H5_SPEED_APPLY__", cdp.expressions[0])
        self.assertIn("window.__H5_SPEED_APPLY__(50.0)", cdp.expressions[1])

    def test_apply_speed_rate_reinjects_when_hook_missing(self) -> None:
        cdp = FakeCdp(
            results=[
                False,
                {"hidden": False},
                {"ok": True, "engine": "timer_hook", "panel": "speed-hack-panel", "current": 1.0},
                {"hidden": True},
                {"ok": True, "current": 50},
            ]
        )
        logs: list[str] = []

        result = apply_speed_rate_to_cdp(cdp, 50, ClientSpeedPanelConfig(), log=logs.append)

        self.assertEqual(result["current"], 50)
        self.assertTrue(any("hook 缺失" in item for item in logs))
        self.assertTrue(any("__H5_SPEED_HOOK_INSTALLED__" in expression for expression in cdp.expressions))

    def test_injected_js_contains_timer_hook_guard_default_rate_and_buttons(self) -> None:
        script = build_custom_speed_panel_script(ClientSpeedPanelConfig())

        self.assertIn('speed-hack-panel', script)
        self.assertIn("__H5_SPEED_HOOK_INSTALLED__", script)
        self.assertIn("__H5_SPEED_ORIGINALS__", script)
        self.assertIn("speed-apply-btn", script)
        self.assertIn("speed-reset-btn", script)
        self.assertIn('data-speed="50"', script)
        self.assertIn('data-speed="500"', script)
        self.assertIn("1.0", script)

    def test_speed_panel_buttons_use_scoped_grid_gap_layout(self) -> None:
        script = build_custom_speed_panel_script(ClientSpeedPanelConfig())

        self.assertIn('class="speed-panel-input"', script)
        self.assertIn('class="speed-panel-actions"', script)
        self.assertIn("#speed-hack-panel .speed-panel-actions", script)
        self.assertIn("display: grid", script)
        self.assertIn("grid-template-columns: repeat(2, minmax(64px, 1fr))", script)
        self.assertIn("gap: 8px 10px", script)

    def test_injected_js_hooks_time_functions_once_and_exposes_api(self) -> None:
        script = build_custom_speed_panel_script(ClientSpeedPanelConfig())

        self.assertIn("Date.now = function()", script)
        self.assertIn("performance.now = function()", script)
        self.assertIn("window.setTimeout = function", script)
        self.assertIn("window.setInterval = function", script)
        self.assertIn("window.requestAnimationFrame = function", script)
        self.assertIn("window.__H5_SPEED_APPLY__", script)
        self.assertIn("window.__H5_SPEED_GET__", script)
        self.assertIn("window.__H5_SPEED_ENSURE_PANEL__", script)

    def test_injected_js_is_idempotent_and_close_only_hides_panel(self) -> None:
        script = build_custom_speed_panel_script(ClientSpeedPanelConfig())

        self.assertIn("if (window.__H5_SPEED_HOOK_INSTALLED__)", script)
        self.assertIn("document.getElementById('speed-hack-panel')", script)
        self.assertIn("setPanelHidden(panel, reopenBtn, true)", script)
        self.assertIn("speed-panel-reopen-btn", script)
        self.assertNotIn("window.close()", script)

    def test_injected_js_removes_old_h5_custom_panel_and_uses_local_storage(self) -> None:
        script = build_custom_speed_panel_script(ClientSpeedPanelConfig())

        self.assertIn("h5-custom-speed-panel", script)
        self.assertIn("speed-hack-panel-position", script)
        self.assertIn("speed-hack-panel-size", script)
        self.assertIn("speed-hack-panel-minimized", script)
        self.assertIn("speed-hack-panel-hidden", script)

    def test_hide_script_does_not_delete_canvas_or_game_roots(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("querySelectorAll('body *')", script)
        self.assertIn("tagName === 'CANVAS'", script)
        self.assertIn("tagName === 'BODY'", script)
        self.assertIn("tagName === 'HTML'", script)
        self.assertIn("isProtectedNode(node)", script)

    def test_hide_script_installs_global_function_observer_and_timer_fallback(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("window.__H5_HIDE_ORIGINAL_SPEED_PANEL__", script)
        self.assertIn("window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__", script)
        self.assertIn("__H5_ORIGINAL_SPEED_HIDE_OBSERVER_INSTALLED__", script)
        self.assertIn("new MutationObserver", script)
        self.assertIn("setInterval", script)
        self.assertIn("500", script)
        self.assertIn("2000", script)
        self.assertIn("window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();", script)

    def test_hide_script_skips_custom_speed_panel_and_reopen_button(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("speed-hack-panel", script)
        self.assertIn("speed-panel-reopen-btn", script)
        self.assertIn("closest('#speed-hack-panel')", script)
        self.assertIn("closest('#speed-panel-reopen-btn')", script)

    def test_hide_script_matches_split_original_overlay_keywords(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("请选择加速倍率", script)
        self.assertIn("+3", script)
        self.assertIn("重置", script)
        self.assertIn("keywordMatches.length", script)
        self.assertIn("hideNode(container, true)", script)

    def test_hide_script_avoids_body_html_canvas_and_iframe_failures(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("tagName === 'BODY'", script)
        self.assertIn("tagName === 'HTML'", script)
        self.assertIn("querySelectorAll('iframe')", script)
        self.assertIn("iframe.contentDocument", script)
        self.assertIn("crossOriginIframe", script)
        self.assertIn("catch", script)

    def test_hide_script_adds_diagnose_function_and_uses_multiple_text_sources(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("window.__H5_SPEED_PANEL_DIAGNOSE__", script)
        self.assertIn("textContent", script)
        self.assertIn("innerText", script)
        self.assertIn("aria-label", script)
        self.assertIn("placeholder", script)
        self.assertIn("normalizeText", script)
        self.assertIn(".normalize('NFKC')", script)

    def test_hide_script_scans_shadow_root_and_point_diagnose(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("shadowRoot", script)
        self.assertIn('source === "shadowRoot"', script)
        self.assertIn("window.__H5_SPEED_PANEL_POINT_DIAGNOSE__", script)
        self.assertIn("elementFromPoint", script)

    def test_hide_script_strong_hide_uses_important_rules(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__", script)
        self.assertIn("style.setProperty('display', 'none', 'important')", script)
        self.assertIn("style.setProperty('visibility', 'hidden', 'important')", script)
        self.assertIn("style.setProperty('opacity', '0', 'important')", script)
        self.assertIn("style.setProperty('pointer-events', 'none', 'important')", script)
        self.assertIn("style.setProperty('width', '0px', 'important')", script)
        self.assertIn("style.setProperty('height', '0px', 'important')", script)

    def test_hide_script_has_original_speed_toggle_function_and_left_scan(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__", script)
        self.assertIn("elementFromPoint", script)
        self.assertIn("x <= 100", script)
        self.assertIn("y <= 380", script)
        self.assertIn("y = 120", script)
        self.assertIn("x += 10", script)
        self.assertIn("y += 10", script)
        self.assertIn("document.querySelectorAll('body *')", script)
        self.assertIn("window.__H5_SPEED_TOGGLE_DIAGNOSE__", script)

    def test_hide_script_toggle_does_not_depend_on_expanded_panel_text(self) -> None:
        script = build_hide_original_speed_overlay_script()

        toggle_helper_section = script.split("function toggleDescriptorText", 1)[1].split("function scanRoot", 1)[0]
        self.assertIn("TOGGLE_KEYWORDS", script)
        self.assertIn("backgroundImage", toggle_helper_section)
        self.assertIn("src", toggle_helper_section)
        self.assertIn("rocket", script)
        self.assertNotIn("请选择加速倍率", toggle_helper_section)

    def test_hide_script_toggle_skips_custom_panel_and_protected_roots(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("closest('#speed-hack-panel')", script)
        self.assertIn("closest('#speed-panel-reopen-btn')", script)
        self.assertIn("tagName === 'BODY'", script)
        self.assertIn("tagName === 'HTML'", script)
        self.assertIn("tagName === 'CANVAS'", script)

    def test_hide_script_toggle_removes_or_hides_small_confirmed_container(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("data-h5-original-speed-toggle-hidden", script)
        self.assertIn("hideToggleNode(container)", script)
        self.assertIn("node.remove()", script)
        self.assertIn("TOGGLE_REMOVE_ORIGINAL = true", script)

    def test_hide_script_toggle_can_be_configured_to_hide_without_remove(self) -> None:
        script = build_hide_original_speed_overlay_script(remove_original_toggle=False)

        self.assertIn("TOGGLE_REMOVE_ORIGINAL = false", script)
        self.assertIn("style.setProperty('display', 'none', 'important')", script)

    def test_hide_script_observer_and_timers_call_toggle_hide(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertGreaterEqual(script.count("window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__();"), 4)
        self.assertIn("window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();", script)
        self.assertIn("__H5_ORIGINAL_SPEED_TOGGLE_SUPPRESSOR_INSTALLED__", script)
        self.assertIn("30000", script)
        self.assertIn("300", script)

    def test_hide_script_runs_toggle_on_dom_ready_without_user_click(self) -> None:
        script = build_hide_original_speed_overlay_script()

        self.assertIn("DOMContentLoaded", script)
        self.assertIn("runToggleSuppression", script)
        self.assertNotIn(".click()", script)

    def test_speed_panel_debug_false_omits_candidate_detail_logs(self) -> None:
        cdp = FakeCdp(results=[{
            "hidden": False,
            "candidates": [{"path": "BODY>DIV.speed", "text": "请选择加速倍率 X1 重置"}],
        }])
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(speed_panel_debug=False), trigger_stage="after_navigate", log=logs.append)

        self.assertIn("[客户端直登] 原加速浮层隐藏：未发现候选", logs)
        self.assertFalse(any("候选1 path=" in item for item in logs))

    def test_speed_panel_debug_true_outputs_candidate_summaries(self) -> None:
        cdp = FakeCdp(results=[{
            "hidden": False,
            "candidates": [{
                "path": "BODY>DIV.speed",
                "text": "请选择加速倍率 X1 重置 - + +3",
                "rect": {"left": 1, "top": 2, "width": 120, "height": 80},
            }],
        }])
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(speed_panel_debug=True), trigger_stage="after_navigate", log=logs.append)

        self.assertIn("[客户端直登] 原加速浮层诊断：候选数量=1", logs)
        self.assertTrue(any("候选1 path=BODY>DIV.speed" in item for item in logs))

    def test_speed_panel_debug_true_outputs_pre_click_toggle_diagnosis(self) -> None:
        cdp = FakeCdp(results=[{
            "hidden": False,
            "togglePreClickCandidates": [{
                "path": "body>div.speed-toggle",
                "className": "speed-toggle rocket",
                "backgroundImage": "url(rocket.png)",
                "rect": {"left": 10, "top": 188, "width": 48, "height": 48},
            }],
        }])
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(speed_panel_debug=True), trigger_stage="after_navigate", log=logs.append)

        self.assertIn("[客户端直登] 火箭入口点击前诊断：候选数量=1", logs)
        self.assertTrue(any("候选1 path=body>div.speed-toggle" in item for item in logs))

    def test_toggle_logs_count_and_debug_candidate_summary(self) -> None:
        cdp = FakeCdp(results=[{
            "hidden": False,
            "toggleHidden": True,
            "toggleHiddenCount": 1,
            "toggleCandidates": [{
                "path": "body>div.rocket",
                "className": "speed-rocket",
                "src": "https://example.test/rocket.png?token=secret",
                "rect": {"left": 8, "top": 160, "width": 42, "height": 42},
            }],
        }])
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(speed_panel_debug=True), trigger_stage="after_navigate", log=logs.append)

        self.assertIn("[客户端直登] 已隐藏原加速器入口按钮，数量=1", logs)
        self.assertTrue(any("原加速器入口候选 path=body>div.rocket" in item for item in logs))
        self.assertFalse(any("secret" in item for item in logs))

    def test_toggle_logs_missed_dom_when_point_scan_only_hits_roots(self) -> None:
        cdp = FakeCdp(results=[{"hidden": False, "toggleHidden": False, "togglePointMissedDom": True}])
        logs: list[str] = []

        process_client_speed_panel(cdp, ClientSpeedPanelConfig(), trigger_stage="after_navigate", log=logs.append)

        self.assertIn("[客户端直登] 原加速器入口按钮未命中 DOM，可能是 canvas/native overlay。", logs)


if __name__ == "__main__":
    unittest.main()
