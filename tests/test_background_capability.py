import unittest

from douluo_launcher.background_capability import (
    REQUIRED_BACKGROUND_CAPABILITY_FIELDS,
    build_background_capability_report,
    render_background_capability_markdown,
)


class BackgroundCapabilityTests(unittest.TestCase):
    def test_report_contains_all_required_fields(self) -> None:
        report = build_background_capability_report()

        self.assertEqual(set(REQUIRED_BACKGROUND_CAPABILITY_FIELDS), set(report.capabilities))

    def test_global_mouse_click_marks_mouse_as_taken(self) -> None:
        report = build_background_capability_report()

        self.assertEqual(report.capabilities["是否使用全局 MoveTo / LeftClick"].value, "后台否；前台是")
        self.assertEqual(report.capabilities["是否会抢鼠标"].value, "后台否；前台是")
        self.assertEqual(report.default_mode, "前台辅助模式")

    def test_set_foreground_window_marks_not_true_background(self) -> None:
        report = build_background_capability_report()

        self.assertEqual(report.capabilities["是否调用 SetForegroundWindow"].value, "后台否；前台部分路径是")
        self.assertFalse(report.is_true_background)

    def test_verified_background_operator_capabilities_are_supported_but_limited(self) -> None:
        report = build_background_capability_report()

        self.assertEqual(report.capabilities["后台截图"].value, "支持")
        self.assertEqual(report.capabilities["后台点击"].value, "支持")
        self.assertEqual(report.capabilities["后台输入"].value, "支持")
        self.assertEqual(report.capabilities["遮挡运行"].value, "待验证")
        self.assertEqual(report.capabilities["黑屏保护"].value, "未接入")
        self.assertEqual(report.capabilities["后台批量"].value, "当前层串行/全部串行已接入（并发=1）")
        self.assertEqual(report.capabilities["后台方式一单账号"].value, "已接入")
        self.assertEqual(report.capabilities["后台方式二"].value, "未接入")

    def test_markdown_renders_frontend_summary_and_details(self) -> None:
        markdown = render_background_capability_markdown(build_background_capability_report())

        self.assertIn("当前默认模式：前台辅助模式", markdown)
        self.assertIn("| 后台点击 | 支持 |", markdown)
        self.assertIn("| 是否会抢鼠标 | 后台否；前台是 |", markdown)
        self.assertIn("后台 WM_GETTEXT、UIA、后台复制和剪贴板 marker 链路已真实验证失败并废弃", markdown)
        self.assertIn("后台通行证提取直接使用 red_bar_box 局部 OCR 多证据主路径", markdown)
        self.assertIn("前台辅助模式仍保持复制优先、OCR 兜底", markdown)


if __name__ == "__main__":
    unittest.main()
