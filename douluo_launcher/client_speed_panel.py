from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable


LogFunc = Callable[[str], None]

CUSTOM_SPEED_PANEL_ID = "speed-hack-panel"
OLD_CUSTOM_SPEED_PANEL_ID = "h5-custom-speed-panel"
SPEED_ENGINE_TIMER_HOOK = "timer_hook"
SPEED_HOOK_STAGE_AFTER_GAME_READY = "after_game_ready"
SPEED_HOOK_STAGE_AFTER_NAVIGATE = "after_navigate"


@dataclass(frozen=True)
class ClientSpeedPanelConfig:
    auto_replace_speed_panel: bool = True
    custom_speed_panel_enabled: bool = True
    speed_engine: str = SPEED_ENGINE_TIMER_HOOK
    default_speed_rate: float = 1.0
    speed_hook_stage: str = SPEED_HOOK_STAGE_AFTER_GAME_READY
    speed_panel_position: str = "left_top"
    speed_panel_left: int = 12
    speed_panel_top: int = 12
    speed_panel_debug: bool = False
    speed_panel_remove_original_toggle: bool = True
    block_browser_context_menu: bool = True


def build_speed_navigation_guard_script(config: ClientSpeedPanelConfig | None = None) -> str:
    panel_config = config or ClientSpeedPanelConfig()
    context_menu_block = ""
    if panel_config.block_browser_context_menu:
        context_menu_block = r"""
    document.addEventListener('contextmenu', function(e) {
        e.preventDefault();
        e.stopPropagation();
        return false;
    }, true);
"""
    return f"""(() => {{
    if (window.__H5_SPEED_NAV_GUARD_INSTALLED__) {{
        return {{ ok: true, existed: true, guard: 'speed_navigation' }};
    }}
    window.__H5_SPEED_NAV_GUARD_INSTALLED__ = true;

    function runSpeedNavigationGuards() {{
        try {{
            if (typeof window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__ === 'function') {{
                window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();
            }} else if (typeof window.__H5_HIDE_ORIGINAL_SPEED_PANEL__ === 'function') {{
                window.__H5_HIDE_ORIGINAL_SPEED_PANEL__();
            }}
        }} catch (_hideError) {{}}
        try {{
            if (typeof window.__H5_SPEED_ENSURE_PANEL__ === 'function') {{
                window.__H5_SPEED_ENSURE_PANEL__();
            }}
        }} catch (_panelError) {{}}
    }}
{context_menu_block}
    ['DOMContentLoaded', 'pageshow', 'popstate', 'hashchange', 'load'].forEach(function(eventName) {{
        window.addEventListener(eventName, function() {{
            setTimeout(runSpeedNavigationGuards, 500);
        }}, true);
    }});
    setInterval(runSpeedNavigationGuards, 2000);
    setTimeout(runSpeedNavigationGuards, 300);
    return {{ ok: true, guard: 'speed_navigation', blockContextMenu: {str(bool(panel_config.block_browser_context_menu)).lower()} }};
}})()"""


def build_speed_new_document_script(config: ClientSpeedPanelConfig | None = None) -> str:
    panel_config = config or ClientSpeedPanelConfig()
    return "\n;\n".join(
        [
            build_hide_original_speed_overlay_script(
                remove_original_toggle=panel_config.speed_panel_remove_original_toggle
            ),
            build_custom_speed_panel_script(panel_config),
            build_speed_navigation_guard_script(panel_config),
        ]
    )


def install_speed_navigation_guard(
    cdp,
    config: ClientSpeedPanelConfig | None = None,
    *,
    log: LogFunc | None = None,
) -> None:
    panel_config = config or ClientSpeedPanelConfig()
    logger = log or (lambda _message: None)
    script = build_speed_new_document_script(panel_config)
    send = getattr(cdp, "send", None)
    if callable(send):
        try:
            send("Page.addScriptToEvaluateOnNewDocument", {"source": script}, timeout=5.0)
        except TypeError:
            send("Page.addScriptToEvaluateOnNewDocument", {"source": script})
        except Exception as exc:
            logger(f"[加速器守护] 新文档预注入失败：{exc}")
    try:
        cdp.evaluate(script)
        if panel_config.block_browser_context_menu:
            logger("[加速器守护] 已启用右键菜单拦截，避免误点 Back / Forward。")
    except Exception as exc:
        logger(f"[加速器守护] 当前页面守护安装失败：{exc}")


def apply_speed_rate_to_cdp(
    cdp,
    rate: float,
    config: ClientSpeedPanelConfig | None = None,
    *,
    log: LogFunc | None = None,
) -> object:
    panel_config = config or ClientSpeedPanelConfig()
    logger = log or (lambda _message: None)
    clean_rate = float(rate)
    if clean_rate <= 0:
        raise ValueError(f"speed rate must be > 0: {rate}")

    hook_available = False
    try:
        hook_available = bool(cdp.evaluate("typeof window.__H5_SPEED_APPLY__ === 'function'"))
    except Exception:
        hook_available = False

    if not hook_available:
        logger(f"[加速总控] speed hook 缺失，重新注入后应用倍率={_format_rate(clean_rate)}。")
        process_client_speed_panel(
            cdp,
            panel_config,
            trigger_stage=SPEED_HOOK_STAGE_AFTER_GAME_READY,
            log=logger,
        )

    return cdp.evaluate(f"window.__H5_SPEED_APPLY__({clean_rate!r})")


def process_client_speed_panel(
    cdp,
    config: ClientSpeedPanelConfig | None = None,
    *,
    trigger_stage: str = SPEED_HOOK_STAGE_AFTER_GAME_READY,
    log: LogFunc | None = None,
) -> None:
    panel_config = config or ClientSpeedPanelConfig()
    logger = log or (lambda _message: None)
    logger("[客户端直登] 开始处理加速浮层")

    if panel_config.auto_replace_speed_panel:
        try:
            result = cdp.evaluate(
                build_hide_original_speed_overlay_script(
                    remove_original_toggle=panel_config.speed_panel_remove_original_toggle
                )
            )
        except Exception as exc:
            logger(f"[客户端直登] 隐藏原加速浮层失败：{exc}")
        else:
            _log_hide_result(result, logger, debug=panel_config.speed_panel_debug)
    else:
        result = None

    if not panel_config.custom_speed_panel_enabled:
        return
    if str(panel_config.speed_engine or "").strip() != SPEED_ENGINE_TIMER_HOOK:
        logger(f"[客户端直登] 未支持的变速器引擎={panel_config.speed_engine}")
        return
    if not _should_inject_timer_hook(panel_config, trigger_stage):
        return

    try:
        result = cdp.evaluate(build_custom_speed_panel_script(panel_config))
    except Exception as exc:
        logger(f"[客户端直登] 注入自定义时间加速器失败：{exc}")
        return

    if isinstance(result, dict):
        if result.get("existed"):
            logger("[客户端直登] 变速器已存在，跳过重复 hook")
        elif result.get("ok"):
            logger("[客户端直登] 已注入自定义时间加速器")
        else:
            logger(f"[客户端直登] 注入自定义时间加速器失败：{result.get('reason') or 'unknown'}")
            return
        logger(
            "[客户端直登] "
            f"变速器引擎={result.get('engine') or SPEED_ENGINE_TIMER_HOOK}，"
            f"当前倍率={_format_rate(result.get('current', panel_config.default_speed_rate))}"
        )
    else:
        logger("[客户端直登] 已请求注入自定义时间加速器")

    if panel_config.auto_replace_speed_panel:
        try:
            _log_hide_result(
                cdp.evaluate(
                    build_hide_original_speed_overlay_script(
                        remove_original_toggle=panel_config.speed_panel_remove_original_toggle
                    )
                ),
                logger,
                debug=panel_config.speed_panel_debug,
            )
        except Exception as exc:
            logger(f"[客户端直登] 隐藏原加速浮层失败：{exc}")


def build_hide_original_speed_overlay_script(*, remove_original_toggle: bool = True) -> str:
    return r"""(() => {
    const SPEED_PANEL_SELECTOR = '#speed-hack-panel';
    const REOPEN_SELECTOR = '#speed-panel-reopen-btn';
    const KEYWORDS = ["请选择加速倍率", "加速倍率", "倍率", "X1", "+3", "重置", "speed", "rate"];
    const NORMALIZED_KEYWORDS = KEYWORDS.map(keyword => normalizeText(keyword));
    const TOGGLE_KEYWORDS = ["speed", "accelerator", "rocket", "加速", "变速", "火箭"];
    const NORMALIZED_TOGGLE_KEYWORDS = TOGGLE_KEYWORDS.map(keyword => normalizeText(keyword));
    const TOGGLE_REMOVE_ORIGINAL = __H5_REMOVE_ORIGINAL_TOGGLE__;

    function isProtectedNode(node) {
        if (!node || node.nodeType !== 1) return true;
        const tagName = node.tagName;
        if (tagName === 'BODY' || tagName === 'HTML' || tagName === 'CANVAS') return true;
        if (node.id === 'speed-hack-panel' || node.id === 'speed-panel-reopen-btn') return true;
        if (typeof node.closest === 'function') {
            if (node.closest('#speed-hack-panel') || node.closest('#speed-panel-reopen-btn')) return true;
        }
        return false;
    }

    function normalizeText(value) {
        try {
            return String(value || '').normalize('NFKC').replace(/[\s\t\r\n\u00a0\u3000]+/g, '').toLowerCase();
        } catch (_error) {
            return String(value || '').replace(/[\s\t\r\n\u00a0\u3000]+/g, '').toLowerCase();
        }
    }

    function textSourceValue(node, name) {
        try {
            if (!node) return '';
            if (name === 'textContent') return String(node.textContent || '');
            if (name === 'innerText') return String(node.innerText || '');
            if (name === 'value') return String(node.value || '');
            if (name === 'placeholder') return String(node.placeholder || '');
            if (name === 'title') return String(node.title || '');
            if (name === 'aria-label') return String(node.getAttribute && node.getAttribute('aria-label') || '');
        } catch (_error) {
            return '';
        }
        return '';
    }

    function nodeText(node) {
        return [
            textSourceValue(node, 'textContent'),
            textSourceValue(node, 'innerText'),
            textSourceValue(node, 'aria-label'),
            textSourceValue(node, 'title'),
            textSourceValue(node, 'value'),
            textSourceValue(node, 'placeholder')
        ].filter(Boolean).join(' ').trim();
    }

    function visibleText(node) {
        return [
            textSourceValue(node, 'textContent'),
            textSourceValue(node, 'innerText'),
            textSourceValue(node, 'aria-label'),
            textSourceValue(node, 'title'),
            textSourceValue(node, 'value'),
            textSourceValue(node, 'placeholder')
        ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
    }

    function shortText(node, limit) {
        return visibleText(node).slice(0, limit || 120);
    }

    function findKeywordMatches(text) {
        const normalized = normalizeText(text);
        return KEYWORDS.filter((keyword, index) => normalized.includes(NORMALIZED_KEYWORDS[index]));
    }

    function looksLikeSpeedText(text) {
        if (!text) return false;
        const keywordMatches = findKeywordMatches(text);
        const normalized = normalizeText(text);
        return normalized.includes(normalizeText("请选择加速倍率"))
            || normalized.includes(normalizeText("加速倍率"))
            || (keywordMatches.length >= 2 && (
                normalized.includes(normalizeText("倍率"))
                || normalized.includes(normalizeText("重置"))
                || normalized.includes(normalizeText("+3"))
                || normalized.includes("speed")
                || normalized.includes("rate")
            ));
    }

    function rectInfo(node) {
        try {
            const rect = node.getBoundingClientRect();
            return {
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            };
        } catch (_error) {
            return { left: 0, top: 0, width: 0, height: 0 };
        }
    }

    function computedInfo(node) {
        try {
            const view = node && node.ownerDocument && node.ownerDocument.defaultView || window;
            const style = view.getComputedStyle(node);
            return {
                position: style.position || '',
                zIndex: style.zIndex || '',
                display: style.display || '',
                visibility: style.visibility || '',
                opacity: style.opacity || ''
            };
        } catch (_error) {
            return { position: '', zIndex: '', display: '', visibility: '', opacity: '' };
        }
    }

    function backgroundImageValue(node) {
        try {
            const view = node && node.ownerDocument && node.ownerDocument.defaultView || window;
            const style = view.getComputedStyle(node);
            return String(style.backgroundImage || '');
        } catch (_error) {
            return '';
        }
    }

    function cssPath(node) {
        try {
            const parts = [];
            let current = node;
            for (let depth = 0; depth < 8 && current && current.nodeType === 1; depth += 1) {
                let part = current.tagName.toLowerCase();
                if (current.id) {
                    part += '#' + String(current.id).slice(0, 60);
                    parts.unshift(part);
                    break;
                }
                const classes = String(current.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
                if (classes.length) part += '.' + classes.map(item => item.slice(0, 40)).join('.');
                if (current.parentElement) {
                    const siblings = Array.from(current.parentElement.children).filter(item => item.tagName === current.tagName);
                    if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(current) + 1) + ')';
                }
                parts.unshift(part);
                current = current.parentElement || current.host;
            }
            return parts.join('>');
        } catch (_error) {
            return '';
        }
    }

    function nodeSummary(node, source) {
        const style = computedInfo(node);
        const parents = [];
        let current = node && node.parentElement;
        for (let depth = 0; depth < 6 && current && current.nodeType === 1; depth += 1) {
            const parentStyle = computedInfo(current);
            parents.push({
                tagName: current.tagName,
                id: current.id || '',
                className: String(current.className || '').slice(0, 120),
                text: shortText(current, 80),
                rect: rectInfo(current),
                position: parentStyle.position,
                zIndex: parentStyle.zIndex
            });
            current = current.parentElement;
        }
        return {
            source: source === "shadowRoot" ? "shadowRoot" : (source || 'document'),
            tagName: node.tagName,
            id: node.id || '',
            className: String(node.className || '').slice(0, 120),
            text: shortText(node, 120),
            textContent: textSourceValue(node, 'textContent').slice(0, 120),
            innerText: textSourceValue(node, 'innerText').slice(0, 120),
            position: style.position,
            zIndex: style.zIndex,
            display: style.display,
            visibility: style.visibility,
            opacity: style.opacity,
            rect: rectInfo(node),
            path: cssPath(node),
            parents
        };
    }

    function toggleSummary(node, source) {
        const summary = nodeSummary(node, source || 'toggle');
        summary.src = String(node && node.src || '').slice(0, 160);
        summary.href = String(node && node.href || '').slice(0, 160);
        summary.title = textSourceValue(node, 'title').slice(0, 120);
        summary.ariaLabel = textSourceValue(node, 'aria-label').slice(0, 120);
        summary.backgroundImage = backgroundImageValue(node).slice(0, 160);
        return summary;
    }

    function toggleDescriptorText(node) {
        if (!node || node.nodeType !== 1) return '';
        return [
            node.tagName,
            node.id || '',
            node.className || '',
            node.src || '',
            node.href || '',
            textSourceValue(node, 'title'),
            textSourceValue(node, 'aria-label'),
            backgroundImageValue(node)
        ].join(' ');
    }

    function toggleKeywordMatches(node) {
        const normalized = normalizeText(toggleDescriptorText(node));
        return TOGGLE_KEYWORDS.filter((keyword, index) => normalized.includes(NORMALIZED_TOGGLE_KEYWORDS[index]));
    }

    function isReasonableToggleRect(node, doc) {
        if (isProtectedNode(node)) return false;
        const rect = rectInfo(node);
        const viewport = viewportSize(doc);
        if (rect.left < -5 || rect.left >= 120) return false;
        if (rect.top < 0 || rect.top > Math.max(430, viewport.height)) return false;
        if (rect.width < 20 || rect.width > 120) return false;
        if (rect.height < 20 || rect.height > 120) return false;
        return true;
    }

    function toggleContainerScore(node, doc, inheritedKeyword) {
        if (!isReasonableToggleRect(node, doc)) return -1000;
        const ownMatches = toggleKeywordMatches(node);
        if (!inheritedKeyword && ownMatches.length === 0) return -1000;
        const style = computedInfo(node);
        const position = style.position || '';
        const zIndex = parseInt(style.zIndex || '0', 10) || 0;
        let score = 0;
        if (['fixed', 'absolute', 'sticky'].includes(position)) score += 6;
        if (position === 'fixed') score += 2;
        if (zIndex >= 10) score += 2;
        if (zIndex >= 1000) score += 2;
        if (ownMatches.length > 0) score += 6;
        if (inheritedKeyword) score += 3;
        if (['IMG', 'BUTTON', 'DIV', 'A', 'SPAN'].includes(node.tagName)) score += 2;
        return score;
    }

    function findToggleContainer(node, doc) {
        const inheritedKeyword = toggleKeywordMatches(node).length > 0;
        let best = null;
        let bestScore = -1000;
        let current = node;
        for (let depth = 0; depth < 5 && current && current.nodeType === 1; depth += 1) {
            const score = toggleContainerScore(current, doc, inheritedKeyword);
            if (score > bestScore) {
                best = current;
                bestScore = score;
            }
            if (!current.parentElement || current.parentElement === doc.body || current.parentElement === doc.documentElement) {
                break;
            }
            current = current.parentElement;
        }
        return bestScore >= 7 ? best : null;
    }

    function hideToggleNode(node) {
        if (isProtectedNode(node)) return false;
        node.style.setProperty('display', 'none', 'important');
        node.style.setProperty('visibility', 'hidden', 'important');
        node.style.setProperty('opacity', '0', 'important');
        node.style.setProperty('pointer-events', 'none', 'important');
        node.setAttribute('data-h5-original-speed-toggle-hidden', '1');
        if (TOGGLE_REMOVE_ORIGINAL) {
            try {
                node.remove();
            } catch (_error) {}
        }
        return true;
    }

    function processToggleNode(node, doc, result, seen, hiddenContainers, shouldHide) {
        if (!node || node.nodeType !== 1 || seen.has(node)) return;
        seen.add(node);
        if (!isProtectedNode(node) && toggleKeywordMatches(node).length > 0 && isReasonableToggleRect(node, doc)) {
            result.candidates.push(toggleSummary(node, 'toggle'));
        }
        const container = findToggleContainer(node, doc);
        if (!container || hiddenContainers.has(container)) return;
        result.candidates.push(toggleSummary(container, 'toggle'));
        hiddenContainers.add(container);
        if (shouldHide && hideToggleNode(container)) {
            result.hiddenCount += 1;
        }
    }

    function scanToggleDom(doc, result, seen, hiddenContainers, shouldHide) {
        let nodes = [];
        try {
            nodes = doc === document ? Array.from(document.querySelectorAll('body *')) : Array.from(doc.querySelectorAll('body *'));
        } catch (_error) {
            return;
        }
        for (const node of nodes) {
            processToggleNode(node, doc, result, seen, hiddenContainers, shouldHide);
        }
    }

    function scanTogglePoints(doc, result, seen, hiddenContainers, shouldHide) {
        let onlyRootHits = true;
        for (let x = 0; x <= 100; x += 10) {
            for (let y = 120; y <= 380; y += 10) {
                let hit = null;
                try {
                    hit = doc.elementFromPoint(x, y);
                } catch (_error) {
                    continue;
                }
                if (!hit) continue;
                if (!['BODY', 'HTML', 'CANVAS'].includes(hit.tagName)) onlyRootHits = false;
                let current = hit;
                for (let depth = 0; depth < 7 && current && current.nodeType === 1; depth += 1) {
                    processToggleNode(current, doc, result, seen, hiddenContainers, shouldHide);
                    if (!current.parentElement || current.parentElement === doc.body || current.parentElement === doc.documentElement) {
                        break;
                    }
                    current = current.parentElement;
                }
            }
        }
        result.pointMissedDom = !result.hidden && result.candidates.length === 0 && onlyRootHits;
    }

    function collectToggleInDocument(doc, shouldHide) {
        const result = { hidden: false, hiddenCount: 0, candidates: [], pointMissedDom: false };
        if (!doc || !doc.body) return result;
        const seen = new Set();
        const hiddenContainers = new Set();
        scanToggleDom(doc, result, seen, hiddenContainers, shouldHide);
        scanTogglePoints(doc, result, seen, hiddenContainers, shouldHide);
        result.hidden = result.hiddenCount > 0;
        return result;
    }

    function hideToggleInDocument(doc) {
        return collectToggleInDocument(doc, true);
    }

    function diagnoseToggleInDocument(doc) {
        return collectToggleInDocument(doc, false);
    }

    function scanRoot(root, source, candidates, seen) {
        if (!root || !root.querySelectorAll) return;
        let nodes = [];
        try {
            nodes = root.body ? Array.from(root.querySelectorAll('body *')) : Array.from(root.querySelectorAll('*'));
        } catch (_error) {
            return;
        }
        for (const node of nodes) {
            if (!node || seen.has(node)) continue;
            seen.add(node);
            if (!isProtectedNode(node) && looksLikeSpeedText(nodeText(node))) {
                candidates.push(nodeSummary(node, source));
            }
            try {
                if (node.shadowRoot) {
                    scanRoot(node.shadowRoot, "shadowRoot", candidates, seen);
                }
            } catch (_error) {}
        }
    }

    function diagnoseDocument(doc, source) {
        const result = { candidates: [], crossOriginIframe: false };
        try {
            scanRoot(doc, source || 'document', result.candidates, new Set());
        } catch (_error) {}
        try {
            const iframes = Array.from(doc.querySelectorAll('iframe'));
            for (const iframe of iframes) {
                try {
                    if (!iframe.contentDocument) {
                        result.crossOriginIframe = true;
                        continue;
                    }
                    const child = diagnoseDocument(iframe.contentDocument, 'iframe');
                    result.candidates.push(...child.candidates);
                    result.crossOriginIframe = result.crossOriginIframe || child.crossOriginIframe;
                } catch (_iframeError) {
                    result.crossOriginIframe = true;
                }
            }
        } catch (_error) {}
        return result;
    }

    function viewportSize(doc) {
        const view = doc && doc.defaultView || window;
        return {
            width: Number(view.innerWidth || document.documentElement.clientWidth || 0),
            height: Number(view.innerHeight || document.documentElement.clientHeight || 0)
        };
    }

    function isReasonableOverlayRect(node, doc) {
        const rect = rectInfo(node);
        const viewport = viewportSize(doc);
        if (rect.width < 80 || rect.width > 700) return false;
        if (rect.height < 40 || rect.height > 500) return false;
        if (rect.left > viewport.width || rect.top > viewport.height) return false;
        if (rect.left + rect.width < 0 || rect.top + rect.height < 0) return false;
        if (rect.width > Math.max(760, viewport.width * 0.85) && rect.height > Math.max(500, viewport.height * 0.70)) return false;
        return true;
    }

    function containerScore(node, doc, requirePosition) {
        if (isProtectedNode(node)) return -1000;
        if (node.querySelector && node.querySelector('canvas')) return -1000;
        const text = nodeText(node);
        if (!looksLikeSpeedText(text)) return -1000;
        if (!isReasonableOverlayRect(node, doc)) return -1000;
        if (text.length > 600) return -1000;

        const style = computedInfo(node);
        const position = style.position || '';
        const zIndex = parseInt(style.zIndex || '0', 10) || 0;
        if (requirePosition && !['fixed', 'absolute', 'sticky'].includes(position)) return -1000;
        let score = 0;
        if (position === 'fixed' || position === 'absolute' || position === 'sticky') score += 7;
        if (position === 'fixed') score += 3;
        if (zIndex >= 10) score += 2;
        if (zIndex >= 1000) score += 2;
        if (isReasonableOverlayRect(node, doc)) score += 4;
        const normalized = normalizeText(text);
        if (normalized.includes(normalizeText("请选择加速倍率"))) score += 5;
        if (normalized.includes(normalizeText("加速倍率")) || normalized.includes(normalizeText("倍率"))) score += 4;
        if (normalized.includes(normalizeText("重置"))) score += 3;
        if (normalized.includes(normalizeText("+3"))) score += 3;
        if (findKeywordMatches(text).length >= 2) score += 2;
        return score;
    }

    function findContainer(node, doc) {
        let best = null;
        let bestScore = -1000;
        let current = node;
        for (let depth = 0; depth < 8 && current; depth += 1) {
            const score = containerScore(current, doc, true);
            if (score > bestScore) {
                best = current;
                bestScore = score;
            }
            if (!current.parentElement || current.parentElement === doc.body || current.parentElement === doc.documentElement) {
                break;
            }
            current = current.parentElement;
        }
        if (bestScore >= 8) return best;

        best = null;
        bestScore = -1000;
        current = node;
        for (let depth = 0; depth < 8 && current; depth += 1) {
            const score = containerScore(current, doc, false);
            if (score > bestScore) {
                best = current;
                bestScore = score;
            }
            if (!current.parentElement || current.parentElement === doc.body || current.parentElement === doc.documentElement) {
                break;
            }
            current = current.parentElement;
        }
        return bestScore >= 6 ? best : null;
    }

    function hideNode(node, confirmedContainer) {
        if (isProtectedNode(node)) return false;
        node.style.setProperty('display', 'none', 'important');
        node.style.setProperty('visibility', 'hidden', 'important');
        node.style.setProperty('opacity', '0', 'important');
        node.style.setProperty('pointer-events', 'none', 'important');
        if (confirmedContainer) {
            node.style.setProperty('width', '0px', 'important');
            node.style.setProperty('height', '0px', 'important');
        }
        node.setAttribute('data-h5-original-speed-hidden', '1');
        return true;
    }

    function collectCandidateNodesFromRoot(root, seen, output) {
        if (!root || !root.querySelectorAll) return;
        let nodes = [];
        try {
            nodes = root.body ? Array.from(root.querySelectorAll('body *')) : Array.from(root.querySelectorAll('*'));
        } catch (_error) {
            return;
        }
        for (const node of nodes) {
            if (!node || seen.has(node)) continue;
            seen.add(node);
            if (!isProtectedNode(node) && looksLikeSpeedText(nodeText(node))) {
                output.push(node);
            }
            try {
                if (node.shadowRoot) collectCandidateNodesFromRoot(node.shadowRoot, seen, output);
            } catch (_error) {}
        }
    }

    function pointDiagnoseDocument(doc) {
        const result = { candidates: [], nodes: [] };
        const seen = new Set();
        const xs = [];
        const ys = [];
        for (let x = 0; x <= 350; x += 30) xs.push(x);
        for (let y = 0; y <= 250; y += 30) ys.push(y);
        xs.push(Math.round((doc.defaultView && doc.defaultView.innerWidth || window.innerWidth || 0) / 2));
        for (const x of xs) {
            for (const y of ys) {
                try {
                    let current = doc.elementFromPoint(x, y);
                    for (let depth = 0; depth < 8 && current && current.nodeType === 1; depth += 1) {
                        if (!seen.has(current)) {
                            seen.add(current);
                            if (!isProtectedNode(current) && looksLikeSpeedText(nodeText(current))) {
                                result.nodes.push(current);
                                result.candidates.push(nodeSummary(current, 'elementFromPoint'));
                            }
                        }
                        current = current.parentElement;
                    }
                } catch (_error) {}
            }
        }
        return result;
    }

    function hideInDocument(doc) {
        const result = { hiddenCount: 0, hiddenPaths: [], candidates: [], crossOriginIframe: false };
        if (!doc || !doc.body) return result;
        const hiddenContainers = new Set();
        const nodes = [];
        collectCandidateNodesFromRoot(doc, new Set(), nodes);
        const point = pointDiagnoseDocument(doc);
        nodes.push(...point.nodes);
        result.candidates.push(...point.candidates);

        for (const node of nodes) {
            const container = findContainer(node, doc);
            if (!container || hiddenContainers.has(container)) continue;
            if (hideNode(container, true)) {
                hiddenContainers.add(container);
                result.hiddenCount += 1;
                result.hiddenPaths.push(cssPath(container));
            }
        }
        return result;
    }

    function mergeHideResult(target, source) {
        target.hiddenCount += source.hiddenCount || 0;
        target.hiddenPaths.push(...(source.hiddenPaths || []));
        target.candidates.push(...(source.candidates || []));
        target.crossOriginIframe = target.crossOriginIframe || !!source.crossOriginIframe;
    }

    function mergeToggleResult(target, source) {
        target.toggleHiddenCount += source.hiddenCount || 0;
        target.toggleCandidates.push(...(source.candidates || []));
        target.togglePointMissedDom = target.togglePointMissedDom || !!source.pointMissedDom;
    }

    function mergeToggleDiagnosis(target, source) {
        target.togglePreClickCandidates.push(...(source.candidates || []));
        target.togglePointMissedDom = target.togglePointMissedDom || !!source.pointMissedDom;
    }

    window.__H5_SPEED_PANEL_DIAGNOSE__ = function() {
        const result = { candidates: [], crossOriginIframe: false };
        try {
            const main = diagnoseDocument(document, 'document');
            result.candidates.push(...main.candidates);
            result.crossOriginIframe = result.crossOriginIframe || main.crossOriginIframe;
        } catch (_error) {}
        return result;
    };

    window.__H5_SPEED_PANEL_POINT_DIAGNOSE__ = function() {
        const result = { candidates: [], crossOriginIframe: false };
        try {
            const point = pointDiagnoseDocument(document);
            result.candidates.push(...point.candidates);
        } catch (_error) {}
        try {
            const iframes = Array.from(document.querySelectorAll('iframe'));
            for (const iframe of iframes) {
                try {
                    if (!iframe.contentDocument) {
                        result.crossOriginIframe = true;
                        continue;
                    }
                    const point = pointDiagnoseDocument(iframe.contentDocument);
                    result.candidates.push(...point.candidates);
                } catch (_iframeError) {
                    result.crossOriginIframe = true;
                }
            }
        } catch (_error) {}
        return result;
    };

    window.__H5_SPEED_TOGGLE_DIAGNOSE__ = function() {
        const result = { togglePreClickCandidates: [], togglePointMissedDom: false, crossOriginIframe: false };
        try {
            mergeToggleDiagnosis(result, diagnoseToggleInDocument(document));
        } catch (_error) {}
        try {
            const iframes = Array.from(document.querySelectorAll('iframe'));
            for (const iframe of iframes) {
                try {
                    if (!iframe.contentDocument) {
                        result.crossOriginIframe = true;
                        continue;
                    }
                    mergeToggleDiagnosis(result, diagnoseToggleInDocument(iframe.contentDocument));
                } catch (_iframeError) {
                    result.crossOriginIframe = true;
                }
            }
        } catch (_error) {}
        return result;
    };

    window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__ = function() {
        const result = { hidden: false, hiddenCount: 0, hiddenPaths: [], candidates: [], crossOriginIframe: false };
        try {
            mergeHideResult(result, hideInDocument(document));
        } catch (_error) {}
        try {
            const iframes = Array.from(document.querySelectorAll('iframe'));
            for (const iframe of iframes) {
                try {
                    if (!iframe.contentDocument) {
                        result.crossOriginIframe = true;
                        continue;
                    }
                    mergeHideResult(result, hideInDocument(iframe.contentDocument));
                } catch (_iframeError) {
                    result.crossOriginIframe = true;
                }
            }
        } catch (_error) {}
        result.hidden = result.hiddenCount > 0;
        return result;
    };

    window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__ = function() {
        const result = { toggleHidden: false, toggleHiddenCount: 0, toggleCandidates: [], togglePointMissedDom: false, crossOriginIframe: false };
        try {
            mergeToggleResult(result, hideToggleInDocument(document));
        } catch (_error) {}
        try {
            const iframes = Array.from(document.querySelectorAll('iframe'));
            for (const iframe of iframes) {
                try {
                    if (!iframe.contentDocument) {
                        result.crossOriginIframe = true;
                        continue;
                    }
                    mergeToggleResult(result, hideToggleInDocument(iframe.contentDocument));
                } catch (_iframeError) {
                    result.crossOriginIframe = true;
                }
            }
        } catch (_error) {}
        result.toggleHidden = result.toggleHiddenCount > 0;
        return result;
    };

    window.__H5_HIDE_ORIGINAL_SPEED_PANEL__ = function() {
        return window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();
    };

    const runToggleSuppression = function() {
        try {
            window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__();
        } catch (_error) {}
    };

    const diagnosis = window.__H5_SPEED_PANEL_DIAGNOSE__();
    const result = window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();
    const toggleDiagnosis = window.__H5_SPEED_TOGGLE_DIAGNOSE__();
    const toggleResult = window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__();
    let observerInstalled = false;

    if (!window.__H5_ORIGINAL_SPEED_HIDE_OBSERVER_INSTALLED__) {
        window.__H5_ORIGINAL_SPEED_HIDE_OBSERVER_INSTALLED__ = true;
        observerInstalled = true;
        let hideTimer = 0;
        const scheduleHide = function() {
            clearTimeout(hideTimer);
            hideTimer = setTimeout(function() {
                try {
                    window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();
                    window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__();
                } catch (_error) {}
            }, 80);
        };
        try {
            const observer = new MutationObserver(scheduleHide);
            observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
            window.__H5_ORIGINAL_SPEED_HIDE_OBSERVER__ = observer;
        } catch (_error) {}

        const startedAt = Date.now();
        const fastTimer = setInterval(function() {
            try {
                window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();
                window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__();
            } catch (_error) {}
            if (Date.now() - startedAt > 15000) {
                clearInterval(fastTimer);
            }
        }, 500);
        window.__H5_ORIGINAL_SPEED_HIDE_FAST_TIMER__ = fastTimer;

        window.__H5_ORIGINAL_SPEED_HIDE_SLOW_TIMER__ = setInterval(function() {
            try {
                window.__H5_HIDE_ORIGINAL_SPEED_PANEL_STRONG__();
                window.__H5_HIDE_ORIGINAL_SPEED_TOGGLE__();
            } catch (_error) {}
        }, 2000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', runToggleSuppression, { once: true });
    } else {
        setTimeout(runToggleSuppression, 0);
    }

    if (!window.__H5_ORIGINAL_SPEED_TOGGLE_SUPPRESSOR_INSTALLED__) {
        window.__H5_ORIGINAL_SPEED_TOGGLE_SUPPRESSOR_INSTALLED__ = true;
        let toggleTimer = 0;
        const scheduleToggleHide = function() {
            clearTimeout(toggleTimer);
            toggleTimer = setTimeout(runToggleSuppression, 60);
        };
        try {
            const toggleObserver = new MutationObserver(scheduleToggleHide);
            toggleObserver.observe(document.body || document.documentElement, { childList: true, subtree: true });
            window.__H5_ORIGINAL_SPEED_TOGGLE_SUPPRESSOR_OBSERVER__ = toggleObserver;
        } catch (_error) {}

        const toggleStartedAt = Date.now();
        const toggleFastTimer = setInterval(function() {
            runToggleSuppression();
            if (Date.now() - toggleStartedAt > 30000) {
                clearInterval(toggleFastTimer);
            }
        }, 300);
        window.__H5_ORIGINAL_SPEED_TOGGLE_FAST_TIMER__ = toggleFastTimer;

        window.__H5_ORIGINAL_SPEED_TOGGLE_SLOW_TIMER__ = setInterval(runToggleSuppression, 2000);
    }

    return {
        hidden: !!result.hidden,
        hiddenCount: result.hiddenCount || 0,
        hiddenPaths: result.hiddenPaths || [],
        candidates: diagnosis.candidates || result.candidates || [],
        toggleHidden: !!toggleResult.toggleHidden,
        toggleHiddenCount: toggleResult.toggleHiddenCount || 0,
        toggleCandidates: toggleResult.toggleCandidates || [],
        togglePreClickCandidates: toggleDiagnosis.togglePreClickCandidates || [],
        togglePointMissedDom: !!(toggleDiagnosis.togglePointMissedDom || toggleResult.togglePointMissedDom),
        crossOriginIframe: !!(diagnosis.crossOriginIframe || result.crossOriginIframe || toggleDiagnosis.crossOriginIframe || toggleResult.crossOriginIframe),
        observerInstalled
    };
})()""".replace("__H5_REMOVE_ORIGINAL_TOGGLE__", "true" if remove_original_toggle else "false")


def build_custom_speed_panel_script(config: ClientSpeedPanelConfig) -> str:
    payload = {
        "defaultRate": float(config.default_speed_rate or 1.0),
        "left": int(config.speed_panel_left),
        "top": int(config.speed_panel_top),
    }
    return TIMER_HOOK_SCRIPT.replace("__H5_SPEED_CONFIG_JSON__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _should_inject_timer_hook(config: ClientSpeedPanelConfig, trigger_stage: str) -> bool:
    configured = str(config.speed_hook_stage or SPEED_HOOK_STAGE_AFTER_GAME_READY).strip()
    stage = str(trigger_stage or "").strip()
    if configured == SPEED_HOOK_STAGE_AFTER_NAVIGATE:
        return stage in {SPEED_HOOK_STAGE_AFTER_NAVIGATE, SPEED_HOOK_STAGE_AFTER_GAME_READY}
    return stage == SPEED_HOOK_STAGE_AFTER_GAME_READY


def _format_rate(rate: object) -> str:
    try:
        number = float(rate or 1.0)
    except (TypeError, ValueError):
        number = 1.0
    return str(int(number)) if number.is_integer() else str(number)


def _log_hide_result(result: object, logger: LogFunc, *, debug: bool = False) -> None:
    if isinstance(result, dict) and result.get("hidden"):
        logger(f"[客户端直登] 原加速浮层隐藏：隐藏数量={int(result.get('hiddenCount') or 1)}")
    else:
        logger("[客户端直登] 原加速浮层隐藏：未发现候选")

    if isinstance(result, dict) and result.get("crossOriginIframe"):
        logger("[客户端直登] 发现跨域 iframe，无法直接隐藏 iframe 内部原加速浮层。")

    if isinstance(result, dict) and result.get("toggleHidden"):
        logger(f"[客户端直登] 已隐藏原加速器入口按钮，数量={int(result.get('toggleHiddenCount') or 1)}")
    elif isinstance(result, dict) and result.get("togglePointMissedDom"):
        logger("[客户端直登] 原加速器入口按钮未命中 DOM，可能是 canvas/native overlay。")
    else:
        logger("[客户端直登] 未发现原加速器入口按钮")

    if not debug or not isinstance(result, dict):
        return

    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    logger(f"[客户端直登] 原加速浮层诊断：候选数量={len(candidates)}")
    for index, candidate in enumerate(candidates[:5], start=1):
        if not isinstance(candidate, dict):
            continue
        path = _sanitize_diag_text(candidate.get("path") or "")
        text = _sanitize_diag_text(candidate.get("text") or candidate.get("innerText") or candidate.get("textContent") or "")
        rect = candidate.get("rect") if isinstance(candidate.get("rect"), dict) else {}
        rect_text = (
            f"{rect.get('left', 0)},{rect.get('top', 0)},"
            f"{rect.get('width', 0)}x{rect.get('height', 0)}"
        )
        logger(f"[客户端直登] 候选{index} path={path[:160]} text={text[:120]} rect={rect_text}")

    pre_click_candidates = result.get("togglePreClickCandidates")
    if not isinstance(pre_click_candidates, list):
        pre_click_candidates = []
    logger(f"[客户端直登] 火箭入口点击前诊断：候选数量={len(pre_click_candidates)}")
    for index, candidate in enumerate(pre_click_candidates[:5], start=1):
        if not isinstance(candidate, dict):
            continue
        path = _sanitize_diag_text(candidate.get("path") or "")
        class_name = _sanitize_diag_text(candidate.get("className") or "")
        bg = _sanitize_diag_text(candidate.get("backgroundImage") or candidate.get("src") or "")
        rect = candidate.get("rect") if isinstance(candidate.get("rect"), dict) else {}
        rect_text = (
            f"{rect.get('left', 0)},{rect.get('top', 0)},"
            f"{rect.get('width', 0)}x{rect.get('height', 0)}"
        )
        logger(f"[客户端直登] 候选{index} path={path[:160]} rect={rect_text} class={class_name[:80]} bg={bg[:120]}")

    toggle_candidates = result.get("toggleCandidates")
    if not isinstance(toggle_candidates, list):
        toggle_candidates = []
    for candidate in toggle_candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        path = _sanitize_diag_text(candidate.get("path") or "")
        class_name = _sanitize_diag_text(candidate.get("className") or "")
        src = _sanitize_diag_text(candidate.get("src") or candidate.get("backgroundImage") or "")
        rect = candidate.get("rect") if isinstance(candidate.get("rect"), dict) else {}
        rect_text = (
            f"{rect.get('left', 0)},{rect.get('top', 0)},"
            f"{rect.get('width', 0)}x{rect.get('height', 0)}"
        )
        logger(f"[客户端直登] 原加速器入口候选 path={path[:160]} rect={rect_text} class={class_name[:80]} src={src[:120]}")


def _sanitize_diag_text(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"https?://\S+", "<url>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)\b(token|sign|cookie|imei)\b\s*[:=]\s*[^&\s,;]+", r"\1=***", text)
    text = re.sub(r"(?i)\b(token|sign|cookie|imei)\b", "***", text)
    return " ".join(text.split())


TIMER_HOOK_SCRIPT = r"""(() => {
'use strict';

try {
    const CONFIG = __H5_SPEED_CONFIG_JSON__;
    const PANEL_ID = 'speed-hack-panel';
    const OLD_PANEL_ID = 'h5-custom-speed-panel';

    if (window.__H5_SPEED_HOOK_INSTALLED__) {
        const oldPanel = document.getElementById(OLD_PANEL_ID);
        if (oldPanel) oldPanel.style.display = 'none';
        if (typeof window.__H5_SPEED_ENSURE_PANEL__ === 'function') {
            window.__H5_SPEED_ENSURE_PANEL__();
        }
        return {
            ok: true,
            existed: true,
            engine: 'timer_hook',
            panel: PANEL_ID,
            current: typeof window.__H5_SPEED_GET__ === 'function' ? window.__H5_SPEED_GET__() : 1.0
        };
    }
    window.__H5_SPEED_HOOK_INSTALLED__ = true;

    const originalSetTimeout = window.__H5_SPEED_ORIGINALS__ && window.__H5_SPEED_ORIGINALS__.setTimeout
        ? window.__H5_SPEED_ORIGINALS__.setTimeout
        : window.setTimeout.bind(window);
    const originalSetInterval = window.__H5_SPEED_ORIGINALS__ && window.__H5_SPEED_ORIGINALS__.setInterval
        ? window.__H5_SPEED_ORIGINALS__.setInterval
        : window.setInterval.bind(window);
    const originalDateNow = window.__H5_SPEED_ORIGINALS__ && window.__H5_SPEED_ORIGINALS__.dateNow
        ? window.__H5_SPEED_ORIGINALS__.dateNow
        : Date.now.bind(Date);
    const originalPerformanceNow = window.__H5_SPEED_ORIGINALS__ && window.__H5_SPEED_ORIGINALS__.performanceNow
        ? window.__H5_SPEED_ORIGINALS__.performanceNow
        : performance.now.bind(performance);
    const originalRequestAnimationFrame = window.__H5_SPEED_ORIGINALS__ && window.__H5_SPEED_ORIGINALS__.requestAnimationFrame
        ? window.__H5_SPEED_ORIGINALS__.requestAnimationFrame
        : window.requestAnimationFrame.bind(window);

    if (!window.__H5_SPEED_ORIGINALS__) {
        window.__H5_SPEED_ORIGINALS__ = {
            setTimeout: originalSetTimeout,
            setInterval: originalSetInterval,
            dateNow: originalDateNow,
            performanceNow: originalPerformanceNow,
            requestAnimationFrame: originalRequestAnimationFrame
        };
    }

    let speedMultiplier = Number(CONFIG.defaultRate);
    if (!Number.isFinite(speedMultiplier) || speedMultiplier <= 0) {
        speedMultiplier = 1.0;
    }

    let baseRealTimeDate = originalDateNow();
    let baseFakeTimeDate = originalDateNow();
    let baseRealTimePerf = originalPerformanceNow();
    let baseFakeTimePerf = originalPerformanceNow();

    function updateBaseTimes() {
        const currentRealDate = originalDateNow();
        baseFakeTimeDate += (currentRealDate - baseRealTimeDate) * speedMultiplier;
        baseRealTimeDate = currentRealDate;

        const currentRealPerf = originalPerformanceNow();
        baseFakeTimePerf += (currentRealPerf - baseRealTimePerf) * speedMultiplier;
        baseRealTimePerf = currentRealPerf;
    }

    Date.now = function() {
        const currentReal = originalDateNow();
        return Math.floor(baseFakeTimeDate + (currentReal - baseRealTimeDate) * speedMultiplier);
    };

    try {
        performance.now = function() {
            const currentReal = originalPerformanceNow();
            return baseFakeTimePerf + (currentReal - baseRealTimePerf) * speedMultiplier;
        };
    } catch (_error) {
        try {
            Object.defineProperty(performance, 'now', {
                configurable: true,
                value: function() {
                    const currentReal = originalPerformanceNow();
                    return baseFakeTimePerf + (currentReal - baseRealTimePerf) * speedMultiplier;
                }
            });
        } catch (_ignored) {}
    }

    window.setTimeout = function(func, delay, ...args) {
        const safeDelay = Number(delay);
        return originalSetTimeout(func, Number.isFinite(safeDelay) ? safeDelay / speedMultiplier : delay, ...args);
    };

    window.setInterval = function(func, delay, ...args) {
        const safeDelay = Number(delay);
        return originalSetInterval(func, Number.isFinite(safeDelay) ? safeDelay / speedMultiplier : delay, ...args);
    };

    window.requestAnimationFrame = function(callback) {
        return originalRequestAnimationFrame(function() {
            callback(performance.now());
        });
    };

    const PANEL_POS_KEY = 'speed-hack-panel-position';
    const PANEL_SIZE_KEY = 'speed-hack-panel-size';
    const PANEL_MINIMIZED_KEY = 'speed-hack-panel-minimized';
    const PANEL_HIDDEN_KEY = 'speed-hack-panel-hidden';

    const BASE_PANEL_WIDTH = 230;
    const DEFAULT_PANEL_SCALE = 0.5;
    const MIN_PANEL_SCALE = 0.35;
    const MAX_PANEL_SCALE = 2.2;
    const MIN_PANEL_WIDTH = 180;
    const MAX_PANEL_WIDTH = 460;

    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    function savePanelPosition(left, top) {
        try {
            localStorage.setItem(PANEL_POS_KEY, JSON.stringify({ left, top }));
        } catch (e) {
            console.warn('[SpeedHack] 保存面板位置失败', e);
        }
    }

    function loadPanelPosition() {
        try {
            const saved = localStorage.getItem(PANEL_POS_KEY);
            if (!saved) return { left: Number(CONFIG.left) || 12, top: Number(CONFIG.top) || 12 };
            const pos = JSON.parse(saved);
            return {
                left: typeof pos.left === 'number' ? pos.left : Number(CONFIG.left) || 12,
                top: typeof pos.top === 'number' ? pos.top : Number(CONFIG.top) || 12
            };
        } catch (e) {
            return { left: Number(CONFIG.left) || 12, top: Number(CONFIG.top) || 12 };
        }
    }

    function savePanelSize(width, scale) {
        try {
            localStorage.setItem(PANEL_SIZE_KEY, JSON.stringify({ width, scale }));
        } catch (e) {
            console.warn('[SpeedHack] 保存面板大小失败', e);
        }
    }

    function loadPanelSize() {
        try {
            const saved = localStorage.getItem(PANEL_SIZE_KEY);
            if (!saved) {
                return { width: BASE_PANEL_WIDTH, scale: DEFAULT_PANEL_SCALE };
            }
            const size = JSON.parse(saved);
            return {
                width: typeof size.width === 'number' ? clamp(size.width, MIN_PANEL_WIDTH, MAX_PANEL_WIDTH) : BASE_PANEL_WIDTH,
                scale: typeof size.scale === 'number' ? clamp(size.scale, MIN_PANEL_SCALE, MAX_PANEL_SCALE) : DEFAULT_PANEL_SCALE
            };
        } catch (e) {
            return { width: BASE_PANEL_WIDTH, scale: DEFAULT_PANEL_SCALE };
        }
    }

    function savePanelMinimized(minimized) {
        try {
            localStorage.setItem(PANEL_MINIMIZED_KEY, minimized ? '1' : '0');
        } catch (e) {
            console.warn('[SpeedHack] 保存最小化状态失败', e);
        }
    }

    function loadPanelMinimized() {
        try {
            return localStorage.getItem(PANEL_MINIMIZED_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function savePanelHidden(hidden) {
        try {
            localStorage.setItem(PANEL_HIDDEN_KEY, hidden ? '1' : '0');
        } catch (e) {
            console.warn('[SpeedHack] 保存隐藏状态失败', e);
        }
    }

    function loadPanelHidden() {
        try {
            return localStorage.getItem(PANEL_HIDDEN_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function setPanelOpacity(panel, visible) {
        panel.style.opacity = visible ? '1' : '0.35';
    }

    function ensurePanelInViewport(panel) {
        if (panel.style.display === 'none') return;
        const rect = panel.getBoundingClientRect();
        const maxLeft = Math.max(0, window.innerWidth - rect.width);
        const maxTop = Math.max(0, window.innerHeight - rect.height);
        const currentLeft = parseInt(panel.style.left, 10) || 0;
        const currentTop = parseInt(panel.style.top, 10) || 0;
        const newLeft = clamp(currentLeft, 0, maxLeft);
        const newTop = clamp(currentTop, 0, maxTop);
        panel.style.left = `${newLeft}px`;
        panel.style.top = `${newTop}px`;
        savePanelPosition(newLeft, newTop);
    }

    function applyPanelSize(panel, width, scale) {
        const safeWidth = clamp(width, MIN_PANEL_WIDTH, MAX_PANEL_WIDTH);
        const safeScale = clamp(scale, MIN_PANEL_SCALE, MAX_PANEL_SCALE);
        panel.dataset.panelWidth = String(safeWidth);
        panel.dataset.panelScale = String(safeScale);
        panel.style.width = `${safeWidth}px`;
        panel.style.minWidth = `${safeWidth}px`;
        panel.style.zoom = String(safeScale);
        savePanelSize(safeWidth, safeScale);
        requestAnimationFrame(() => ensurePanelInViewport(panel));
    }

    function setPanelMinimized(panel, minimized) {
        const body = panel.querySelector('#speed-panel-body');
        const resizeHandle = panel.querySelector('#speed-panel-resize-handle');
        const title = panel.querySelector('#speed-panel-title');
        panel.dataset.minimized = minimized ? '1' : '0';
        if (body) body.style.display = minimized ? 'none' : 'flex';
        if (resizeHandle) resizeHandle.style.display = minimized ? 'none' : 'block';
        if (title) title.textContent = minimized ? '⚡ 已最小化' : '⚡ 变速器';
        const width = parseFloat(panel.dataset.panelWidth || String(BASE_PANEL_WIDTH));
        panel.style.width = minimized ? `${Math.max(120, Math.round(width * 0.78))}px` : `${width}px`;
        savePanelMinimized(minimized);
        requestAnimationFrame(() => ensurePanelInViewport(panel));
    }

    function togglePanelMinimized(panel) {
        setPanelMinimized(panel, panel.dataset.minimized !== '1');
    }

    function setPanelHidden(panel, reopenBtn, hidden) {
        panel.style.display = hidden ? 'none' : 'block';
        reopenBtn.style.display = hidden ? 'flex' : 'none';
        savePanelHidden(hidden);
        if (!hidden) requestAnimationFrame(() => ensurePanelInViewport(panel));
    }

    function makePanelDraggable(panel, handle) {
        let isDragging = false;
        let offsetX = 0;
        let offsetY = 0;
        handle.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            if (e.detail > 1) return;
            if (e.target && e.target.closest('#speed-panel-close-btn')) return;
            isDragging = true;
            const rect = panel.getBoundingClientRect();
            offsetX = e.clientX - rect.left;
            offsetY = e.clientY - rect.top;
            setPanelOpacity(panel, true);
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const rect = panel.getBoundingClientRect();
            const maxLeft = window.innerWidth - rect.width;
            const maxTop = window.innerHeight - rect.height;
            panel.style.left = `${clamp(e.clientX - offsetX, 0, Math.max(0, maxLeft))}px`;
            panel.style.top = `${clamp(e.clientY - offsetY, 0, Math.max(0, maxTop))}px`;
        });
        document.addEventListener('mouseup', () => {
            if (!isDragging) return;
            isDragging = false;
            document.body.style.userSelect = '';
            savePanelPosition(parseInt(panel.style.left, 10) || 0, parseInt(panel.style.top, 10) || 0);
            setPanelOpacity(panel, panel.matches(':hover'));
        });
    }

    function makePanelResizable(panel, handle) {
        let isResizing = false;
        let startX = 0;
        let startY = 0;
        let startWidth = 0;
        let startScale = 1.0;
        handle.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            if (panel.dataset.minimized === '1') return;
            isResizing = true;
            startX = e.clientX;
            startY = e.clientY;
            startWidth = parseFloat(panel.dataset.panelWidth || String(BASE_PANEL_WIDTH));
            startScale = parseFloat(panel.dataset.panelScale || String(DEFAULT_PANEL_SCALE));
            setPanelOpacity(panel, true);
            document.body.style.userSelect = 'none';
            e.preventDefault();
            e.stopPropagation();
        });
        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            applyPanelSize(
                panel,
                startWidth + ((e.clientX - startX) / Math.max(startScale, 0.01)),
                startScale + ((e.clientY - startY) * 0.005)
            );
        });
        document.addEventListener('mouseup', () => {
            if (!isResizing) return;
            isResizing = false;
            document.body.style.userSelect = '';
            setPanelOpacity(panel, panel.matches(':hover'));
        });
    }

    function formatSpeed(val) {
        return Number.isInteger(val) ? String(val) : val.toFixed(1);
    }

    function applySpeed(val) {
        let num = parseFloat(val);
        if (isNaN(num) || num <= 0) num = 1.0;
        updateBaseTimes();
        speedMultiplier = num;
        const inputEl = document.querySelector('#speed-input-field');
        const display = document.querySelector('#speed-display-val');
        if (inputEl) inputEl.value = String(speedMultiplier);
        if (display) display.innerText = formatSpeed(speedMultiplier);
        console.log(`[客户端直登] 用户设置倍率=${speedMultiplier}`);
        console.log(`[SpeedHack] 已设为 ${speedMultiplier} 倍速`);
        return { ok: true, engine: 'timer_hook', panel: PANEL_ID, current: speedMultiplier };
    }

    window.__H5_SPEED_APPLY__ = function(rate) {
        return applySpeed(rate);
    };
    window.__H5_SPEED_GET__ = function() {
        return speedMultiplier;
    };

    function createPanel() {
        const oldPanel = document.getElementById(OLD_PANEL_ID);
        if (oldPanel) oldPanel.style.display = 'none';
        const oldStyle = document.getElementById('h5-custom-speed-panel-style');
        if (oldStyle) oldStyle.disabled = true;
        if (document.getElementById('speed-hack-panel')) return;
        if (!document.body) return;

        const savedPos = loadPanelPosition();
        const savedSize = loadPanelSize();
        const savedMinimized = loadPanelMinimized();
        const savedHidden = loadPanelHidden();

        const panel = document.createElement('div');
        panel.id = 'speed-hack-panel';
        panel.style.cssText = `
            position: fixed;
            top: ${savedPos.top}px;
            left: ${savedPos.left}px;
            z-index: 2147483647;
            background: rgba(0, 0, 0, 0.9);
            color: #00ff00;
            padding: 12px;
            border-radius: 10px;
            font-family: 'Segoe UI', Tahoma, sans-serif;
            font-size: 11.5px;
            box-shadow: 0 0 15px rgba(0,0,0,0.5);
            border: 1px solid #444;
            min-width: ${BASE_PANEL_WIDTH}px;
            width: ${BASE_PANEL_WIDTH}px;
            opacity: 0.35;
            transition: opacity 0.2s ease;
            box-sizing: border-box;
            transform-origin: top left;
        `;

        panel.innerHTML = `
            <style>
                #speed-hack-panel .speed-panel-input {
                    width: 100%;
                    box-sizing: border-box;
                    margin-top: 6px;
                    margin-bottom: 10px;
                }
                #speed-hack-panel .speed-panel-actions {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(64px, 1fr));
                    gap: 8px 10px;
                    margin-top: 8px;
                }
                #speed-hack-panel .speed-panel-actions button {
                    min-height: 28px;
                    padding: 6px 10px;
                    box-sizing: border-box;
                }
            </style>
            <div id="speed-panel-header" style="
                position: relative;
                margin: -12px -12px 8px -12px;
                padding: 9px 34px 9px 12px;
                font-weight: bold;
                color: #fff;
                text-align: center;
                cursor: move;
                background: rgba(255,255,255,0.06);
                border-bottom: 1px solid #333;
                border-radius: 10px 10px 0 0;
            ">
                <span id="speed-panel-title">⚡ 变速器</span>
                <button id="speed-panel-close-btn" style="
                    position: absolute;
                    top: 50%;
                    right: 7px;
                    transform: translateY(-50%);
                    width: 20px;
                    height: 20px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    background: #b02a37;
                    color: #fff;
                    font-weight: bold;
                    font-size: 13px;
                    line-height: 1;
                    padding: 0;
                ">×</button>
            </div>

            <div id="speed-panel-body" style="display: flex; flex-direction: column; gap: 7px;">
                <div id="speed-current-wrap" style="text-align: center; color: #fff; font-size: 10px; line-height: 1.1;">
                    当前:
                    <span id="speed-display-val" style="color: #00ff00; font-weight: bold; font-size: 12px;">${formatSpeed(speedMultiplier)}</span>
                </div>

                <input class="speed-panel-input" type="number" id="speed-input-field" value="${formatSpeed(speedMultiplier)}" step="1"
                    style="background: #222; color: #fff; border: 1px solid #555; text-align: center; border-radius: 4px;">

                <div class="speed-panel-actions">
                    <button id="speed-apply-btn" style="background: #28a745; color: white; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; line-height: 1.1;">应用</button>
                    <button id="speed-reset-btn" style="background: #6c757d; color: white; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; line-height: 1.1;">重置</button>
                    <button class="speed-preset-apply-btn" data-speed="50" style="width: 100%; min-width: 0; background: #0d6efd; color: white; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; line-height: 1.1;">50</button>
                    <button class="speed-preset-apply-btn" data-speed="500" style="width: 100%; min-width: 0; background: #0d6efd; color: white; border: none; cursor: pointer; border-radius: 3px; font-weight: bold; line-height: 1.1;">500</button>
                </div>
            </div>

            <div id="speed-panel-resize-handle" style="
                position: absolute;
                right: 3px;
                bottom: 3px;
                width: 16px;
                height: 16px;
                cursor: nwse-resize;
                border-right: 2px solid rgba(255,255,255,0.55);
                border-bottom: 2px solid rgba(255,255,255,0.55);
                box-sizing: border-box;
            "></div>
        `;

        const reopenBtn = document.createElement('div');
        reopenBtn.id = 'speed-panel-reopen-btn';
        reopenBtn.textContent = '⚡';
        reopenBtn.style.cssText = `
            position: fixed;
            left: 12px;
            bottom: 12px;
            z-index: 2147483647;
            width: 24px;
            height: 24px;
            display: none;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: rgba(0, 0, 0, 0.78);
            color: #00ff00;
            border: 1px solid #444;
            box-shadow: 0 0 8px rgba(0,0,0,0.4);
            cursor: pointer;
            font-size: 12px;
            opacity: 0.25;
            transition: opacity 0.2s ease, transform 0.2s ease;
            user-select: none;
        `;
        reopenBtn.title = '打开变速控制器';

        document.body.appendChild(panel);
        document.body.appendChild(reopenBtn);

        const header = panel.querySelector('#speed-panel-header');
        const closeBtn = panel.querySelector('#speed-panel-close-btn');
        const inputEl = panel.querySelector('#speed-input-field');
        const btnApply = panel.querySelector('#speed-apply-btn');
        const btnReset = panel.querySelector('#speed-reset-btn');
        const resizeHandle = panel.querySelector('#speed-panel-resize-handle');
        const presetButtons = panel.querySelectorAll('.speed-preset-apply-btn');

        makePanelDraggable(panel, header);
        makePanelResizable(panel, resizeHandle);

        header.addEventListener('dblclick', (e) => {
            if (e.target && e.target.closest('#speed-panel-close-btn')) return;
            e.preventDefault();
            togglePanelMinimized(panel);
        });
        closeBtn.addEventListener('mousedown', (e) => e.stopPropagation());
        closeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            setPanelHidden(panel, reopenBtn, true);
        });
        reopenBtn.addEventListener('mouseenter', () => {
            reopenBtn.style.opacity = '1';
            reopenBtn.style.transform = 'scale(1.06)';
        });
        reopenBtn.addEventListener('mouseleave', () => {
            reopenBtn.style.opacity = '0.25';
            reopenBtn.style.transform = 'scale(1)';
        });
        reopenBtn.addEventListener('click', () => {
            setPanelHidden(panel, reopenBtn, false);
            setPanelOpacity(panel, true);
        });
        panel.addEventListener('mouseenter', () => setPanelOpacity(panel, true));
        panel.addEventListener('mouseleave', () => setPanelOpacity(panel, false));
        btnApply.addEventListener('click', () => {
            applySpeed(inputEl.value);
            inputEl.blur();
        });
        btnReset.addEventListener('click', () => {
            applySpeed(1.0);
            inputEl.blur();
        });
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                applySpeed(inputEl.value);
                inputEl.blur();
            }
        });
        presetButtons.forEach((btn) => {
            btn.addEventListener('click', () => applySpeed(btn.dataset.speed));
        });

        applyPanelSize(panel, savedSize.width, savedSize.scale);
        setPanelMinimized(panel, savedMinimized);
        setPanelHidden(panel, reopenBtn, savedHidden);
        requestAnimationFrame(() => ensurePanelInViewport(panel));

        originalSetInterval(() => {
            const display = panel.querySelector('#speed-display-val');
            const currentDisplay = formatSpeed(speedMultiplier);
            if (display && display.innerText !== currentDisplay) {
                display.innerText = currentDisplay;
            }
        }, 500);
        window.addEventListener('resize', () => ensurePanelInViewport(panel));
    }

    window.__H5_SPEED_ENSURE_PANEL__ = createPanel;

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', createPanel);
    } else {
        createPanel();
    }

    originalSetInterval(() => {
        if (!document.getElementById('speed-hack-panel') && document.body) {
            createPanel();
        }
    }, 2000);

    return { ok: true, engine: 'timer_hook', panel: PANEL_ID, current: speedMultiplier };
} catch (error) {
    return { ok: false, engine: 'timer_hook', panel: 'speed-hack-panel', reason: String(error && error.message || error) };
}
})()"""
