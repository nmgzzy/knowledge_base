from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from .auto_add import apply_auto_suggestion, default_filename, default_inbox_dir, suggest_destination_with_llm
from .config import load_config, resolve_paths
from .fs_ops import copy_or_move, ensure_dir_meta
from .markdown import guess_title
from .openai_compat import OpenAICompatError
from .util import ensure_rel_under_base


def add_to_kb(
    kb_root: Path,
    *,
    src: Path,
    dest_rel_dir: Optional[str],
    auto: bool,
    move: bool,
) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    cfg = load_config(kb_root)
    paths = resolve_paths(kb_root)
    meta_filename = str(cfg.get("meta_filename", "meta.json"))

    src = src.expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(str(src))

    imported: list[str] = []
    if src.is_dir():
        base_name = src.name
        root_rel = ensure_rel_under_base(dest_rel_dir) if dest_rel_dir else f"imports/{base_name}"
        for abs_path in _walk_markdown(src):
            rel_from_src = abs_path.relative_to(src).as_posix()
            target_rel = ensure_rel_under_base(f"{root_rel}/{rel_from_src}")
            dst = paths.kb_dir / target_rel
            ensure_dir_meta(dst.parent, meta_filename=meta_filename)
            copy_or_move(abs_path, dst, move=move)
            imported.append(target_rel)
        return {"imported": imported, "mode": "dir", "dest_rel_dir": root_rel}

    if dest_rel_dir:
        rel_dir = ensure_rel_under_base(dest_rel_dir)
        dst_dir = paths.kb_dir / rel_dir if rel_dir else paths.kb_dir
        ensure_dir_meta(dst_dir, meta_filename=meta_filename)
        title = guess_title(src.read_text(encoding="utf-8", errors="replace"), fallback=src.stem)
        filename = default_filename(src, title=title)
        dst = dst_dir / filename
        copy_or_move(src, dst, move=move)
        imported.append(dst.relative_to(paths.kb_dir).as_posix())
        return {"imported": imported, "mode": "manual", "dest_rel_dir": rel_dir}

    if auto:
        src_text = src.read_text(encoding="utf-8", errors="replace")
        try:
            suggestion = suggest_destination_with_llm(kb_root, src_text=src_text, src_name=src.name)
            rel_dir, filename, _ = apply_auto_suggestion(kb_root, suggestion=suggestion, meta_filename=meta_filename)
            title = str(suggestion.get("doc_title") or "").strip() or guess_title(src_text, fallback=src.stem)
            if not filename:
                filename = default_filename(src, title=title)
            dst_dir = paths.kb_dir / rel_dir if rel_dir else paths.kb_dir
            dst = dst_dir / filename
            copy_or_move(src, dst, move=move)
            imported.append(dst.relative_to(paths.kb_dir).as_posix())
            return {"imported": imported, "mode": "auto", "dest_rel_dir": rel_dir, "suggestion": suggestion}
        except OpenAICompatError as e:
            pass

    rel_dir = default_inbox_dir()
    rel_dir = ensure_rel_under_base(rel_dir)
    dst_dir = paths.kb_dir / rel_dir
    ensure_dir_meta(dst_dir, meta_filename=meta_filename)
    title = guess_title(src.read_text(encoding="utf-8", errors="replace"), fallback=src.stem)
    filename = default_filename(src, title=title)
    dst = dst_dir / filename
    copy_or_move(src, dst, move=move)
    imported.append(dst.relative_to(paths.kb_dir).as_posix())
    return {"imported": imported, "mode": "inbox", "dest_rel_dir": rel_dir}


def _walk_markdown(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            if name.lower().endswith(".md"):
                yield Path(dirpath) / name
