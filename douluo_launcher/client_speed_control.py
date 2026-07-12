from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Callable, Iterable

from .client_cdp import RawCdpClient, mask_sensitive_text, select_page_target, wait_for_cdp_targets
from .client_cdp_ownership import CdpOwnershipResult, validate_window_cdp_endpoint
from .client_speed_panel import (
    ClientSpeedPanelConfig,
    apply_speed_rate_to_cdp,
    build_speed_tree_toggle_script,
)


LogFunc = Callable[[str], None]


@dataclass(frozen=True)
class SpeedApplyResult:
    success: bool
    status: str
    message: str = ""
    ownership: CdpOwnershipResult | None = None
    response: object = None


@dataclass(frozen=True)
class SpeedControlOutcome:
    account_id: str
    account_name: str
    status: str
    message: str = ""


@dataclass
class SpeedControlSummary:
    total: int
    success: int = 0
    failed: int = 0
    skipped: int = 0
    stopped: int = 0
    outcomes: list[SpeedControlOutcome] = field(default_factory=list)


def apply_speed_rate_to_binding(
    binding,
    rate: float,
    config: ClientSpeedPanelConfig,
    *,
    ownership_validator=validate_window_cdp_endpoint,
    target_loader=wait_for_cdp_targets,
    target_selector=select_page_target,
    cdp_factory=RawCdpClient,
    apply_func=apply_speed_rate_to_cdp,
    log: LogFunc | None = None,
) -> SpeedApplyResult:
    logger = log or (lambda _message: None)
    hwnd = int(getattr(binding, "hwnd", 0) or 0)
    pid = int(getattr(binding, "pid", 0) or 0)
    port = int(getattr(binding, "cdp_port", 0) or 0)
    ownership = ownership_validator(hwnd, pid, port)
    logger(f"[加速总控][CDP归属] {ownership.safe_message()}")
    if not ownership.verified:
        return SpeedApplyResult(
            False,
            "ownership_failed",
            f"CDP 归属校验失败: {ownership.status}",
            ownership=ownership,
        )

    cdp = None
    try:
        targets = target_loader(port, timeout=3.0)
        target = target_selector(targets)
        cdp = cdp_factory(str(target["webSocketDebuggerUrl"]))
        cdp.connect()
        cdp.enable_default_domains()
        response = apply_func(cdp, float(rate), config, log=logger)
        if not isinstance(response, dict) or response.get("ok") is not True:
            reason = "unknown"
            if isinstance(response, dict):
                reason = mask_sensitive_text(response.get("reason") or "apply returned ok=false")
            return SpeedApplyResult(
                False,
                "apply_failed",
                f"加速应用失败: {reason}",
                ownership=ownership,
                response=response,
            )
        return SpeedApplyResult(
            True,
            "applied",
            "加速倍率应用成功",
            ownership=ownership,
            response=response,
        )
    except Exception as exc:
        return SpeedApplyResult(
            False,
            "apply_failed",
            mask_sensitive_text(exc),
            ownership=ownership,
        )
    finally:
        if cdp is not None:
            try:
                cdp.close()
            except Exception:
                pass


def toggle_speed_tree_for_binding(
    binding,
    *,
    ownership_validator=validate_window_cdp_endpoint,
    target_loader=wait_for_cdp_targets,
    target_selector=select_page_target,
    cdp_factory=RawCdpClient,
    log: LogFunc | None = None,
) -> SpeedApplyResult:
    logger = log or (lambda _message: None)
    hwnd = int(getattr(binding, "hwnd", 0) or 0)
    pid = int(getattr(binding, "pid", 0) or 0)
    port = int(getattr(binding, "cdp_port", 0) or 0)
    ownership = ownership_validator(hwnd, pid, port)
    logger(f"[加速器快捷键][CDP归属] {ownership.safe_message()}")
    if not ownership.verified:
        return SpeedApplyResult(False, "ownership_failed", f"CDP 归属校验失败: {ownership.status}", ownership=ownership)
    cdp = None
    try:
        target = target_selector(target_loader(port, timeout=3.0))
        cdp = cdp_factory(str(target["webSocketDebuggerUrl"]))
        cdp.connect()
        cdp.enable_default_domains()
        response = cdp.evaluate(build_speed_tree_toggle_script())
        if not isinstance(response, dict) or response.get("ok") is not True:
            reason = response.get("reason") if isinstance(response, dict) else "toggle returned ok=false"
            return SpeedApplyResult(False, "toggle_failed", mask_sensitive_text(reason), ownership=ownership, response=response)
        return SpeedApplyResult(True, "toggled", "树形加速器已切换", ownership=ownership, response=response)
    except Exception as exc:
        return SpeedApplyResult(False, "toggle_failed", mask_sensitive_text(exc), ownership=ownership)
    finally:
        if cdp is not None:
            try:
                cdp.close()
            except Exception:
                pass


def run_speed_control_batch(
    bindings: Iterable[object],
    rate: float,
    *,
    stop_event: Event | None,
    skip_reason: Callable[[object], str],
    apply_binding: Callable[[object, float], SpeedApplyResult],
    log: LogFunc | None = None,
) -> SpeedControlSummary:
    logger = log or (lambda _message: None)
    items = list(bindings)
    summary = SpeedControlSummary(total=len(items))
    for index, binding in enumerate(items):
        if stop_event is not None and stop_event.is_set():
            for pending in items[index:]:
                summary.outcomes.append(_outcome(pending, "stopped", "用户停止，未启动"))
                summary.stopped += 1
            break

        name = _binding_name(binding)
        try:
            reason = str(skip_reason(binding) or "")
        except Exception as exc:
            reason = f"precheck_failed: {mask_sensitive_text(exc)}"
        if reason:
            summary.skipped += 1
            summary.outcomes.append(_outcome(binding, "skipped", reason))
            logger(f"[加速总控] 跳过 {name}：{mask_sensitive_text(reason)}")
            continue

        try:
            result = apply_binding(binding, float(rate))
        except Exception as exc:
            result = SpeedApplyResult(False, "apply_failed", mask_sensitive_text(exc))
        if result.success:
            setattr(binding, "speed_rate", float(rate))
            summary.success += 1
            summary.outcomes.append(_outcome(binding, "success", result.message))
            logger(f"[加速总控] 成功 {name}：倍率={_format_rate(rate)}")
        else:
            summary.failed += 1
            message = mask_sensitive_text(result.message or result.status or "unknown")
            summary.outcomes.append(_outcome(binding, "failed", message))
            logger(f"[加速总控] 失败 {name}：{message}")
    return summary


def _outcome(binding, status: str, message: str) -> SpeedControlOutcome:
    return SpeedControlOutcome(
        account_id=str(getattr(binding, "account_id", "") or ""),
        account_name=str(getattr(binding, "account_name", "") or ""),
        status=status,
        message=mask_sensitive_text(message),
    )


def _binding_name(binding) -> str:
    return str(getattr(binding, "account_name", "") or getattr(binding, "account_id", "") or "未命名窗口")


def _format_rate(rate: float) -> str:
    value = float(rate)
    return str(int(value)) if value.is_integer() else str(value)
