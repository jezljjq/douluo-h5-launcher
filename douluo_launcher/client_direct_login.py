from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable
from urllib.parse import parse_qs, urlparse

from .client_cdp import (
    CdpEventMarkers,
    CdpEventTracker,
    ImportServerIdentity,
    RawCdpClient,
    mask_sensitive_text,
    select_page_target,
    start_x5game_with_cdp,
    wait_for_cdp_targets,
)
from .client_speed_panel import ClientSpeedPanelConfig, process_client_speed_panel


LogFunc = Callable[[str], None]

DIRECT_LOGIN_ENTRY_PATHS = {
    "dldl.50pk.com": {"/login.php"},
    "app.xxh5.z7xz.com": {"/login.php"},
    "7tu7tu.com": {"/dldl"},
}


@dataclass
class ClientBinding:
    account_id: str
    account_name: str
    pid: int
    hwnd: int
    cdp_port: int
    login_url: str = ""
    status: str = ""


@dataclass
class ClientDirectRunRecord:
    account_id: str
    account_name: str
    pid: int = 0
    hwnd: int = 0
    cdp_port: int = 0
    login_url: str = ""
    status: str = "未开始"
    error_message: str = ""


@dataclass
class ClientRuntimeState:
    client_alive: bool = False
    canvas_count: int = 0
    visible_canvas: bool = False
    has_com_game: bool = False
    has_app_params: bool = False
    server: int | None = None
    ip: str = ""
    port: int | None = None
    is_pc_launch: bool = False
    has_x5web_app: bool = False
    has_enter_game_function: bool = False


@dataclass
class DirectLoginCheck:
    markers: CdpEventMarkers
    import_server_state: int | None = None
    import_server_id: ImportServerIdentity | None = None
    server_mobile_state: int | None = None
    runtime: ClientRuntimeState | None = None


@dataclass(frozen=True)
class ClientDirectLoginConfig:
    account_id: str
    account_name: str
    full_login_url: str
    x5game_path: str | Path
    cdp_port: int
    auto_enter_game: bool = True
    timeout: float = 60.0
    auto_replace_speed_panel: bool = True
    custom_speed_panel_enabled: bool = True
    speed_engine: str = "timer_hook"
    default_speed_rate: float = 1.0
    speed_hook_stage: str = "after_game_ready"
    speed_panel_position: str = "left_top"
    speed_panel_left: int = 12
    speed_panel_top: int = 12
    speed_panel_debug: bool = False
    speed_panel_remove_original_toggle: bool = True


@dataclass(frozen=True)
class PreparedClientDirectLoginConfig:
    account_id: str
    account_name: str
    full_login_url: str
    cdp_port: int
    auto_enter_game: bool = True
    timeout: float = 60.0
    auto_replace_speed_panel: bool = True
    custom_speed_panel_enabled: bool = True
    speed_engine: str = "timer_hook"
    default_speed_rate: float = 1.0
    speed_hook_stage: str = "after_game_ready"
    speed_panel_position: str = "left_top"
    speed_panel_left: int = 12
    speed_panel_top: int = 12
    speed_panel_debug: bool = False
    speed_panel_remove_original_toggle: bool = True


@dataclass
class ClientDirectLoginResult:
    success: bool
    status: str
    message: str
    binding: ClientBinding | None = None
    check: DirectLoginCheck | None = None
    process: subprocess.Popen | None = None


RUNTIME_STATE_EXPR = r"""(() => {
    const canvases = Array.from(document.querySelectorAll("canvas")).map(c => ({
        width: c.width,
        height: c.height,
        clientWidth: c.clientWidth,
        clientHeight: c.clientHeight
    }));
    const params = window.app && window.app.Params ? {
        SERVER: window.app.Params.SERVER,
        IP: window.app.Params.IP,
        PORT: window.app.Params.PORT,
        isPcLaunch: window.app.Params.isPcLaunch
    } : null;
    const visibleCanvas = canvases.some(c => c.clientWidth > 0 && c.clientHeight > 0);
    return {
        canvasCount: canvases.length,
        visibleCanvas,
        hasComGame: !!(window.com && window.com.Game),
        hasAppParams: !!params,
        params,
        hasX5WebApp: !!window.s_x5webApp,
        hasEnterGameFunction: !!(window.s_x5webApp && typeof window.s_x5webApp.enterGame === "function")
    };
})()"""


def is_complete_direct_login_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return False
    host = parsed.hostname or ""
    path = parsed.path or ""
    if parsed.scheme not in ("http", "https"):
        return False
    if path not in DIRECT_LOGIN_ENTRY_PATHS.get(host, set()):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    required = ("gid", "pid", "token", "time", "sign")
    if any(not query.get(key) or query.get(key) == [""] for key in required):
        return False
    return (query.get("isPcLauncher") or [""])[0].lower() == "true"


def runtime_state_from_payload(payload: object, *, client_alive: bool = True) -> ClientRuntimeState:
    if not isinstance(payload, dict):
        return ClientRuntimeState(client_alive=client_alive)
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    return ClientRuntimeState(
        client_alive=client_alive,
        canvas_count=int(payload.get("canvasCount") or 0),
        visible_canvas=bool(payload.get("visibleCanvas")),
        has_com_game=bool(payload.get("hasComGame")),
        has_app_params=bool(payload.get("hasAppParams")),
        server=_as_int(params.get("SERVER")),
        ip=str(params.get("IP") or ""),
        port=_as_int(params.get("PORT")),
        is_pc_launch=bool(params.get("isPcLaunch")),
        has_x5web_app=bool(payload.get("hasX5WebApp")),
        has_enter_game_function=bool(payload.get("hasEnterGameFunction")),
    )


def build_check(tracker: CdpEventTracker, runtime: ClientRuntimeState) -> DirectLoginCheck:
    return DirectLoginCheck(
        markers=tracker.markers,
        import_server_state=tracker.import_server_state,
        import_server_id=tracker.import_server_id,
        server_mobile_state=tracker.server_mobile_state,
        runtime=runtime,
    )


def is_no_enter_success(check: DirectLoginCheck) -> bool:
    runtime = check.runtime or ClientRuntimeState()
    identity = check.import_server_id or ImportServerIdentity()
    return bool(
        check.markers.import_server
        and check.markers.game_notice
        and check.import_server_state == 1
        and identity.server_id
        and identity.has_uid
        and runtime.client_alive
        and runtime.has_x5web_app
        and runtime.has_enter_game_function
    )


def is_auto_enter_success(check: DirectLoginCheck) -> bool:
    runtime = check.runtime or ClientRuntimeState()
    identity = check.import_server_id or ImportServerIdentity()
    return bool(
        check.markers.import_server
        and check.import_server_state == 1
        and identity.server_id
        and identity.has_uid
        and check.markers.server_mobile
        and check.server_mobile_state == 1
        and check.markers.game_main
        and check.markers.main_js
        and runtime.client_alive
        and runtime.visible_canvas
        and runtime.has_com_game
        and runtime.has_app_params
        and runtime.server
        and runtime.ip
        and runtime.port
        and runtime.is_pc_launch
    )


def execute_client_direct_login(
    config: ClientDirectLoginConfig,
    *,
    stop_event: Event | None = None,
    log: LogFunc | None = None,
) -> ClientDirectLoginResult:
    logger = log or (lambda _message: None)
    prepared = prepare_client_direct_client(config, stop_event=stop_event, log=logger)
    if not prepared.success or prepared.binding is None:
        return prepared
    login_result = execute_prepared_client_direct_login(
        PreparedClientDirectLoginConfig(
            account_id=config.account_id,
            account_name=config.account_name,
            full_login_url=config.full_login_url,
            cdp_port=int(config.cdp_port),
            auto_enter_game=bool(config.auto_enter_game),
            timeout=float(config.timeout),
            auto_replace_speed_panel=bool(config.auto_replace_speed_panel),
            custom_speed_panel_enabled=bool(config.custom_speed_panel_enabled),
            speed_engine=str(config.speed_engine or "timer_hook"),
            default_speed_rate=float(config.default_speed_rate or 1.0),
            speed_hook_stage=str(config.speed_hook_stage or "after_game_ready"),
            speed_panel_position=str(config.speed_panel_position or "left_top"),
            speed_panel_left=int(config.speed_panel_left),
            speed_panel_top=int(config.speed_panel_top),
            speed_panel_debug=bool(config.speed_panel_debug),
            speed_panel_remove_original_toggle=bool(config.speed_panel_remove_original_toggle),
        ),
        prepared.binding,
        stop_event=stop_event,
        log=logger,
    )
    login_result.process = prepared.process
    return login_result


def prepare_client_direct_client(
    config: ClientDirectLoginConfig,
    *,
    stop_event: Event | None = None,
    log: LogFunc | None = None,
) -> ClientDirectLoginResult:
    logger = log or (lambda _message: None)
    if not is_complete_direct_login_url(config.full_login_url):
        return ClientDirectLoginResult(False, "失败", "URL 不是完整客户端直登 URL")

    process: subprocess.Popen | None = None
    try:
        _raise_if_stopped(stop_event)
        process = start_x5game_with_cdp(config.x5game_path, config.cdp_port)
        logger(f"X5Game.exe started pid={process.pid} cdp_port={config.cdp_port}")
        _raise_if_stopped(stop_event)
        hwnd = wait_for_client_hwnd_by_pid(process.pid, timeout=min(10.0, config.timeout), stop_event=stop_event)
        binding = ClientBinding(
            account_id=config.account_id,
            account_name=config.account_name,
            pid=int(process.pid or 0),
            hwnd=int(hwnd or 0),
            cdp_port=int(config.cdp_port),
            login_url=config.full_login_url,
            status="待登录",
        )
        logger(f"client window bound pid={binding.pid} hwnd={binding.hwnd} cdp_port={binding.cdp_port}")
        _raise_if_stopped(stop_event)
        targets = wait_for_cdp_targets(config.cdp_port, timeout=min(30.0, config.timeout))
        select_page_target(targets)
        logger("CDP connected")
        return ClientDirectLoginResult(
            True,
            "客户端已启动",
            "客户端已启动，待登录",
            binding=binding,
            process=process,
        )
    except Exception as exc:
        binding = None
        if process is not None:
            binding = ClientBinding(
                account_id=config.account_id,
                account_name=config.account_name,
                pid=int(process.pid or 0),
                hwnd=wait_for_client_hwnd_by_pid(process.pid, timeout=0.1),
                cdp_port=int(config.cdp_port),
                login_url=config.full_login_url,
                status="客户端启动失败",
            )
        return ClientDirectLoginResult(
            False,
            "失败",
            mask_sensitive_text(str(exc)),
            binding=binding,
            process=process,
        )


def execute_prepared_client_direct_login(
    config: PreparedClientDirectLoginConfig,
    binding: ClientBinding,
    *,
    stop_event: Event | None = None,
    log: LogFunc | None = None,
) -> ClientDirectLoginResult:
    logger = log or (lambda _message: None)
    if not is_complete_direct_login_url(config.full_login_url):
        return ClientDirectLoginResult(False, "失败", "URL 不是完整客户端直登 URL", binding=binding)

    cdp: RawCdpClient | None = None
    tracker = CdpEventTracker()
    try:
        _raise_if_stopped(stop_event)
        targets = wait_for_cdp_targets(config.cdp_port, timeout=min(30.0, config.timeout))
        target = select_page_target(targets)
        logger("CDP connected")
        _raise_if_stopped(stop_event)
        cdp = RawCdpClient(str(target["webSocketDebuggerUrl"]), event_tracker=tracker)
        cdp.connect()
        cdp.enable_default_domains()

        _raise_if_stopped(stop_event)
        cdp.navigate(config.full_login_url)
        logger("Page.navigate sent")
        _safe_process_speed_panel(cdp, config, logger, trigger_stage="after_navigate")

        runtime = ClientRuntimeState(client_alive=_binding_alive(binding))
        check = build_check(tracker, runtime)
        deadline = time.time() + float(config.timeout)
        _wait_until(
            deadline,
            cdp,
            tracker,
            lambda: tracker.import_server_state == 1
            and tracker.import_server_id.server_id is not None
            and tracker.import_server_id.has_uid,
            stop_event=stop_event,
        )
        logger("importServer success")

        _wait_until(deadline, cdp, tracker, lambda: tracker.markers.game_notice, stop_event=stop_event)
        logger("gameNotice loaded")
        _safe_process_speed_panel(cdp, config, logger, trigger_stage="after_game_ready")

        runtime = _safe_runtime_state_for_binding(cdp, binding)
        check = build_check(tracker, runtime)
        if not config.auto_enter_game:
            if is_no_enter_success(check):
                binding.status = "客户端已就绪"
                return ClientDirectLoginResult(True, "客户端已就绪", "客户端已就绪，未自动进入游戏", binding=binding, check=check)
            binding.status = "客户端直登失败"
            return ClientDirectLoginResult(False, "失败", "客户端就绪判定失败", binding=binding, check=check)

        _raise_if_stopped(stop_event)
        enter_result = cdp.evaluate(
            r"""(() => {
                if (window.s_x5webApp && typeof window.s_x5webApp.enterGame === "function") {
                    window.s_x5webApp.enterGame();
                    return "called";
                }
                return "missing";
            })()"""
        )
        if enter_result != "called":
            binding.status = "客户端直登失败"
            return ClientDirectLoginResult(False, "失败", "enterGame 方法不可用", binding=binding, check=check)
        logger("enterGame called")

        _wait_until(deadline, cdp, tracker, lambda: tracker.server_mobile_state == 1, stop_event=stop_event)
        logger("serverMobile success")
        _wait_until(deadline, cdp, tracker, lambda: tracker.markers.game_main and tracker.markers.main_js, stop_event=stop_event)
        logger("GameMain/main.js loaded")
        _wait_until(
            deadline,
            cdp,
            tracker,
            lambda: is_auto_enter_success(build_check(tracker, _safe_runtime_state_for_binding(cdp, binding))),
            stop_event=stop_event,
        )
        runtime = _safe_runtime_state_for_binding(cdp, binding)
        check = build_check(tracker, runtime)
        if is_auto_enter_success(check):
            logger("canvas visible")
            _safe_process_speed_panel(cdp, config, logger, trigger_stage="after_game_ready")
            binding.status = "客户端登录成功"
            return ClientDirectLoginResult(True, "客户端登录成功", "client direct login success", binding=binding, check=check)
        binding.status = "客户端直登失败"
        return ClientDirectLoginResult(False, "失败", "客户端登录成功判定失败", binding=binding, check=check)
    except Exception as exc:
        runtime = _safe_runtime_state_for_binding(cdp, binding) if cdp else ClientRuntimeState(client_alive=_binding_alive(binding))
        binding.status = "客户端直登失败"
        return ClientDirectLoginResult(
            False,
            "失败",
            mask_sensitive_text(str(exc)),
            binding=binding,
            check=build_check(tracker, runtime),
        )
    finally:
        if cdp:
            cdp.close()


def _wait_until(
    deadline: float,
    cdp: RawCdpClient,
    tracker: CdpEventTracker,
    predicate: Callable[[], bool],
    *,
    stop_event: Event | None,
) -> None:
    fetched_bodies: set[str] = set()
    while time.time() < deadline:
        _raise_if_stopped(stop_event)
        cdp.pump(0.5)
        for request_id in tracker.key_response_ids_needing_body():
            if request_id in fetched_bodies:
                continue
            fetched_bodies.add(request_id)
            try:
                tracker.record_response_body(request_id, cdp.get_response_body(request_id))
            except Exception:
                pass
        if predicate():
            return
    raise TimeoutError("客户端直登等待超时")


def _safe_runtime_state(cdp: RawCdpClient | None, process: subprocess.Popen | None) -> ClientRuntimeState:
    if not cdp:
        return ClientRuntimeState(client_alive=_process_alive(process))
    try:
        return runtime_state_from_payload(cdp.evaluate(RUNTIME_STATE_EXPR), client_alive=_process_alive(process))
    except Exception:
        return ClientRuntimeState(client_alive=_process_alive(process))


def _safe_runtime_state_for_binding(cdp: RawCdpClient | None, binding: ClientBinding) -> ClientRuntimeState:
    if not cdp:
        return ClientRuntimeState(client_alive=_binding_alive(binding))
    try:
        return runtime_state_from_payload(cdp.evaluate(RUNTIME_STATE_EXPR), client_alive=_binding_alive(binding))
    except Exception:
        return ClientRuntimeState(client_alive=_binding_alive(binding))


def _safe_process_speed_panel(
    cdp: RawCdpClient,
    config: PreparedClientDirectLoginConfig,
    logger: LogFunc,
    *,
    trigger_stage: str,
) -> None:
    try:
        process_client_speed_panel(
            cdp,
            ClientSpeedPanelConfig(
                auto_replace_speed_panel=bool(config.auto_replace_speed_panel),
                custom_speed_panel_enabled=bool(config.custom_speed_panel_enabled),
                speed_engine=str(config.speed_engine or "timer_hook"),
                default_speed_rate=float(config.default_speed_rate or 1.0),
                speed_hook_stage=str(config.speed_hook_stage or "after_game_ready"),
                speed_panel_position=str(config.speed_panel_position or "left_top"),
                speed_panel_left=int(config.speed_panel_left),
                speed_panel_top=int(config.speed_panel_top),
                speed_panel_debug=bool(config.speed_panel_debug),
                speed_panel_remove_original_toggle=bool(config.speed_panel_remove_original_toggle),
            ),
            trigger_stage=trigger_stage,
            log=logger,
        )
    except Exception as exc:
        logger(f"[客户端直登] 加速面板处理失败，已跳过：{mask_sensitive_text(exc)}")


def _process_alive(process: subprocess.Popen | None) -> bool:
    return bool(process is not None and process.poll() is None)


def _binding_alive(binding: ClientBinding | None) -> bool:
    if binding is None:
        return False
    hwnd = int(getattr(binding, "hwnd", 0) or 0)
    if hwnd <= 0:
        return False
    try:
        from .window_manager import user32, wintypes

        return bool(user32.IsWindow(wintypes.HWND(hwnd)))
    except Exception:
        return True


def _raise_if_stopped(stop_event: Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise RuntimeError("用户停止")


def wait_for_client_hwnd_by_pid(
    pid: int | None,
    *,
    timeout: float = 10.0,
    stop_event: Event | None = None,
    hwnd_lister: Callable[[int], Iterable[int]] | None = None,
) -> int:
    clean_pid = int(pid or 0)
    if clean_pid <= 0:
        return 0
    lister = hwnd_lister or _list_visible_hwnds_for_pid
    deadline = time.time() + max(0.0, float(timeout))
    while True:
        _raise_if_stopped(stop_event)
        hwnds = [int(hwnd) for hwnd in lister(clean_pid) if int(hwnd or 0)]
        if hwnds:
            return hwnds[0]
        if time.time() >= deadline:
            return 0
        time.sleep(0.2)


def _list_visible_hwnds_for_pid(pid: int) -> list[int]:
    try:
        from .window_manager import get_window_process_id, user32, wintypes
    except Exception:
        return []

    hwnds: list[int] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            if user32.IsWindowVisible(wintypes.HWND(hwnd)) and get_window_process_id(int(hwnd)) == int(pid):
                hwnds.append(int(hwnd))
        except Exception:
            pass
        return True

    try:
        from .window_manager import EnumWindowsProc

        user32.EnumWindows(EnumWindowsProc(callback), 0)
    except Exception:
        return []
    return hwnds


def _as_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
