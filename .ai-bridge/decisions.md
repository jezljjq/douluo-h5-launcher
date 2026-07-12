# Decisions

Updated: 2026-07-12

## Stable Project Decisions

1. Core stability comes before UI polish. v1.4.12 code changes are paused until live validation produces new evidence.
2. Client preparation success cannot be inferred from a display status or CDP availability alone. It requires a live process, valid HWND, HWND/PID match, usable Page target, and verified CDP ownership/endpoint.
3. Window arrangement preserves original slot indexes and uses the complete batch layout count. Missing windows leave holes and are not backfilled.
4. Login only operates on bindings that pass validation again immediately before navigation.
5. The self-developed speed feature keeps 1x, 2, 5, 50, and 500. Rates 50 and 500 do not require confirmation or warnings.
6. The compact speed UI is a left-edge tree panel. `＋/－` move through `1→2→5→50→500` without cycling at the boundaries.
7. The custom hotkey only expands/collapses the panel for the exact verified foreground binding. It does not change rate or target multiple windows.
8. `TIMER_HOOK_SCRIPT` remains unchanged unless a future task explicitly authorizes a core algorithm change.
9. ChangeSpeeder remains reference-only and must not be integrated.
10. No formal EXE is built until live acceptance passes.
11. Preserve the dirty workspace. Do not reset, checkout, bulk-delete, clean untracked files, or overwrite unrelated work.
12. ChatGPT/CodexPro cannot actually start or execute the Codex desktop agent. ChatGPT may only prepare plans, handoff files, review notes, and copyable prompts. The user starts Codex manually. Future replies must not claim “I started Codex” or “Codex is running” unless an external executor has independently written a real running-state file.
13. Automatic restoration of the speed panel after Reload/Back/Forward/BFCache is an accepted known limitation and is no longer developed or required for acceptance. Do not list it as a remaining test item. If the panel disappears after navigation, use “修复本批窗口” to revalidate CDP ownership and reinject it.
14. In frozen/packaged mode, migration must never discover user data by walking up from `sys.executable`, scanning the current working directory, or probing a development repository. Packaged migration sources must be limited to explicit locations inside the release directory or a user-specified data directory. Source mode may keep project-local migration behavior.
