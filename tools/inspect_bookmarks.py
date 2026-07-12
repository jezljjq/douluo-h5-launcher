from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def inspect_bookmarks(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    by_path: dict[str, list[dict[str, object]]] = defaultdict(list)

    def visit(node: object, parent: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        name = str(node.get("name") or "")
        current = (*parent, name) if name else parent
        if str(node.get("type") or "") == "url":
            by_path["/".join(current)].append({
                "parent_path": "/".join(parent),
                "name": name,
                "guid": str(node.get("guid") or ""),
                "id": str(node.get("id") or ""),
                "url": str(node.get("url") or ""),
                "source": str(node.get("source") or ""),
            })
        for child in node.get("children", []) if isinstance(node.get("children"), list) else []:
            visit(child, current)

    roots = payload.get("roots", {}) if isinstance(payload, dict) else {}
    if isinstance(roots, dict):
        for root_name, root in roots.items():
            visit(root, (f"roots/{root_name}",))
    duplicates = [
        {"path": path_key, "count": len(nodes), "nodes": nodes, "suggestion": "需用户核对后决定保留项"}
        for path_key, nodes in sorted(by_path.items()) if len(nodes) > 1
    ]
    return {
        "mode": "preview_only",
        "file": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duplicates": duplicates,
        "duplicate_paths": len(duplicates),
    }


def restore_bookmarks(current: Path, backup: Path, *, confirmed: bool) -> Path:
    if not confirmed:
        raise PermissionError("恢复需要显式 --confirm")
    json.loads(backup.read_text(encoding="utf-8-sig"))
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    safety_backup = current.parent / f"Bookmarks_before_restore_{stamp}.json"
    shutil.copy2(current, safety_backup)
    temp = current.with_name(current.name + ".restore.tmp")
    shutil.copy2(backup, temp)
    temp.replace(current)
    json.loads(current.read_text(encoding="utf-8-sig"))
    return safety_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Chromium 收藏夹检查/恢复工具（默认只读预览）")
    parser.add_argument("bookmarks", type=Path)
    parser.add_argument("--compare", type=Path, action="append", default=[])
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    reports = [inspect_bookmarks(args.bookmarks), *(inspect_bookmarks(path) for path in args.compare)]
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))
    if args.restore is not None:
        safety = restore_bookmarks(args.bookmarks, args.restore, confirmed=args.confirm)
        print(json.dumps({"restored": True, "safety_backup": str(safety)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
