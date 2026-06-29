from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import app_root


REQUIRED_BACKGROUND_CAPABILITY_FIELDS = (
    "后台截图",
    "后台点击",
    "后台输入",
    "遮挡运行",
    "黑屏保护",
    "后台批量",
    "后台方式一单账号",
    "后台方式二",
    "是否会抢鼠标",
    "是否会抢键盘",
    "是否调用 SetForegroundWindow",
    "是否使用大漠 BindWindow",
    "是否使用全局 MoveTo / LeftClick",
    "是否使用全局键盘输入",
)


@dataclass(frozen=True)
class CapabilityItem:
    value: str
    reason: str


@dataclass(frozen=True)
class BackgroundCapabilityReport:
    default_mode: str
    is_true_background: bool
    capabilities: dict[str, CapabilityItem]

    @property
    def frontend_summary(self) -> str:
        return (
            f"后台能力检测：当前默认模式={self.default_mode}；"
            f"后台点击={self.capabilities['后台点击'].value}，"
            f"后台输入={self.capabilities['后台输入'].value}，"
            f"遮挡运行={self.capabilities['遮挡运行'].value}，"
            f"会抢鼠标={self.capabilities['是否会抢鼠标'].value}，"
            f"会抢键盘={self.capabilities['是否会抢键盘'].value}。"
        )


def build_background_capability_report() -> BackgroundCapabilityReport:
    capabilities = {
        "后台截图": CapabilityItem(
            "支持",
            "background_operator_probe 已对登录/浏览器窗口做 hwnd 后台截图真实验证；后台通行证提取以截图 OCR 为主路径。",
        ),
        "后台点击": CapabilityItem(
            "支持",
            "background_operator_probe 已验证 PostMessage hwnd 点击可关闭区服弹窗并打开通行证输入面板；本轮接入方式一单账号实验流程。",
        ),
        "后台输入": CapabilityItem(
            "支持",
            "background_operator_probe 已验证 WM_CHAR 后台输入可进入通行证输入框，验证方法为截图差异/人工复核。",
        ),
        "遮挡运行": CapabilityItem(
            "待验证",
            "后台截图/点击/输入已验证，但遮挡运行尚未做完整回归验证，不标记为支持。",
        ),
        "黑屏保护": CapabilityItem(
            "未接入",
            "本轮不接黑屏保护，仅保留后续接口方向。",
        ),
        "后台批量": CapabilityItem(
            "当前层串行/全部串行已接入（并发=1）",
            "后台当前层串行/全部串行复用 BackgroundSingleAccountRunner，按账号列表逐个运行，不做并发。",
        ),
        "后台方式一单账号": CapabilityItem(
            "已接入",
            "GUI 后台登录模式的单账号、当前层串行、全部串行均使用 BackgroundSingleAccountRunner；单账号 live 已验证成功。",
        ),
        "后台方式二": CapabilityItem(
            "未接入",
            "方式二在后台模式下会被阻止并提示切回前台辅助模式。",
        ),
        "是否会抢鼠标": CapabilityItem(
            "后台否；前台是",
            "后台实验流程使用 hwnd 消息点击，不移动系统鼠标；前台辅助模式仍会使用全局鼠标。",
        ),
        "是否会抢键盘": CapabilityItem(
            "后台否；前台是",
            "后台实验流程使用 hwnd WM_CHAR 输入，不使用全局键盘，不再读取或写入剪贴板；前台辅助模式仍会使用全局键盘/剪贴板。",
        ),
        "是否调用 SetForegroundWindow": CapabilityItem(
            "后台否；前台部分路径是",
            "BackgroundOperator 不调用 SetForegroundWindow；前台辅助历史路径仍可能前置窗口。",
        ),
        "是否使用大漠 BindWindow": CapabilityItem(
            "否",
            "当前正式流程禁止使用 Dm BindWindow；历史验证为 Win11 不兼容。",
        ),
        "是否使用全局 MoveTo / LeftClick": CapabilityItem(
            "后台否；前台是",
            "后台实验流程使用 PostMessage 点击；前台辅助模式仍保留 dm_click_helper 全局点击。",
        ),
        "是否使用全局键盘输入": CapabilityItem(
            "后台否；前台是",
            "后台实验流程使用窗口消息输入；前台辅助模式仍保留 Ctrl+V / 键盘事件。",
        ),
    }
    return BackgroundCapabilityReport(
        default_mode="前台辅助模式",
        is_true_background=False,
        capabilities=capabilities,
    )


def render_background_capability_markdown(report: BackgroundCapabilityReport | None = None) -> str:
    report = report or build_background_capability_report()
    lines = [
        "# 后台能力检测报告",
        "",
        f"当前默认模式：{report.default_mode}",
        "",
        "说明：本报告只记录当前上号器项目内部已验证能力，不接 H5 总工程，不改变默认运行流程。",
        "",
        "| 能力项 | 结论 | 依据 |",
        "|--------|------|------|",
    ]
    for field in REQUIRED_BACKGROUND_CAPABILITY_FIELDS:
        item = report.capabilities[field]
        lines.append(f"| {field} | {item.value} | {item.reason} |")
    lines.extend(
        [
            "",
            "实验说明：项目已新增后台登录模式框架和 `tools/background_operator_probe.py` 探针脚本。"
            "探针已验证后台截图、点击、输入真实生效；后台模式已接入方式一单账号、当前层串行、全部串行（并发=1）。",
            "后台 WM_GETTEXT、UIA、后台复制和剪贴板 marker 链路已真实验证失败并废弃；后台通行证提取使用后台截图进入前台同款 OCR 兜底链，red_bar_box 仅作为受 QR 几何约束的增强证据。",
            "前台辅助模式仍保持复制优先、OCR 兜底。",
            "",
            "结论：默认稳定流程仍是前台辅助模式；后台登录模式当前支持方式一单账号、当前层串行、全部串行，"
            "方式二、遮挡运行和黑屏保护仍未接入。",
            "",
        ]
    )
    return "\n".join(lines)


def write_background_capability_report(path: str | Path | None = None) -> Path:
    output_path = Path(path) if path is not None else app_root() / "BACKGROUND_CAPABILITY.md"
    output_path.write_text(render_background_capability_markdown(), encoding="utf-8")
    return output_path
