from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from .importer import add_to_kb


def autoadd_inbox(
    kb_root: Path,
    *,
    inbox_dir: Optional[Path] = None,
    move: bool = True,
) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    inbox_dir = (inbox_dir or (kb_root / "_inbox")).expanduser().resolve()
    if not inbox_dir.exists():
        return {
            "kb_root": str(kb_root),
            "inbox_dir": str(inbox_dir),
            "processed": 0,
            "imported": [],
            "skipped": [],
            "errors": [],
        }

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    processed = 0

    for abs_path in _walk_inbox_files(inbox_dir):
        processed += 1
        try:
            rel = abs_path.relative_to(inbox_dir).as_posix()
        except Exception:
            rel = abs_path.as_posix()

        if _is_probably_binary(abs_path):
            skipped.append({"src": rel, "reason": "binary"})
            continue

        try:
            out = add_to_kb(kb_root, src=abs_path, dest_rel_dir=None, auto=True, move=move)
            imported.append({"src": rel, "result": out})
        except Exception as e:
            errors.append({"src": rel, "error": str(e)})

    return {
        "kb_root": str(kb_root),
        "inbox_dir": str(inbox_dir),
        "processed": processed,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def _walk_inbox_files(inbox_dir: Path):
    for dirpath, dirnames, filenames in os.walk(inbox_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            yield Path(dirpath) / name


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except Exception:
        return True
