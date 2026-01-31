from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from .auto_add import apply_auto_suggestion, default_filename, default_inbox_dir, suggest_destination_with_llm
from .config import load_config, resolve_paths
from .fs_ops import copy_or_move, ensure_dir_meta_chain
from .markdown import guess_title, upsert_frontmatter
from .openai_compat import OpenAICompatError
from .util import ensure_rel_under_base

logger = logging.getLogger(__name__)


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

    logger.info("add src=%s auto=%s move=%s dest=%s", str(src), bool(auto), bool(move), dest_rel_dir or "")

    imported: list[str] = []
    if src.is_dir():
        base_name = src.name
        root_rel = ensure_rel_under_base(dest_rel_dir) if dest_rel_dir else f"imports/{base_name}"
        files = list(_walk_markdown(src))
        logger.info("import directory files=%d dest_rel_dir=%s", len(files), root_rel)
        for i, abs_path in enumerate(files, start=1):
            rel_from_src = abs_path.relative_to(src).as_posix()
            target_rel = ensure_rel_under_base(f"{root_rel}/{rel_from_src}")
            dst = paths.kb_dir / target_rel
            parent_rel = dst.parent.relative_to(paths.kb_dir).as_posix()
            parent_rel = "" if parent_rel == "." else parent_rel
            ensure_dir_meta_chain(paths.kb_dir, rel_dir=parent_rel, meta_filename=meta_filename)
            copy_or_move(abs_path, dst, move=move)
            imported.append(target_rel)
            if i == 1 or i == len(files) or (i % 50 == 0):
                logger.info("import progress %d/%d -> %s", i, len(files), target_rel)
        return {"imported": imported, "mode": "dir", "dest_rel_dir": root_rel}

    if dest_rel_dir:
        rel_dir = ensure_rel_under_base(dest_rel_dir)
        dst_dir = paths.kb_dir / rel_dir if rel_dir else paths.kb_dir
        ensure_dir_meta_chain(paths.kb_dir, rel_dir=rel_dir, meta_filename=meta_filename)
        src_text = src.read_text(encoding="utf-8", errors="replace")
        title = guess_title(src_text, fallback=src.stem)
        filename = default_filename(src, title=title)
        dst = dst_dir / filename
        copy_or_move(src, dst, move=move)
        imported.append(dst.relative_to(paths.kb_dir).as_posix())
        logger.info("imported -> %s", imported[-1])
        return {"imported": imported, "mode": "manual", "dest_rel_dir": rel_dir}

    if auto:
        src_text = src.read_text(encoding="utf-8", errors="replace")
        try:
            logger.info("auto archive: call LLM for destination suggestion")
            suggestion = suggest_destination_with_llm(kb_root, src_text=src_text, src_name=src.name)
            rel_dir, filename, _ = apply_auto_suggestion(kb_root, suggestion=suggestion, meta_filename=meta_filename)
            title = str(suggestion.get("doc_title") or "").strip() or guess_title(src_text, fallback=src.stem)
            if not filename:
                filename = default_filename(src, title=title)
            dst_dir = paths.kb_dir / rel_dir if rel_dir else paths.kb_dir
            dst = dst_dir / filename
            copy_or_move(src, dst, move=move)
            doc_summary = str(suggestion.get("doc_summary") or "").strip()
            tags = suggestion.get("tags") if isinstance(suggestion.get("tags"), list) else []
            keywords = suggestion.get("keywords") if isinstance(suggestion.get("keywords"), list) else []
            try:
                dst_text = dst.read_text(encoding="utf-8", errors="replace")
                patched = upsert_frontmatter(
                    dst_text,
                    patch={"title": title, "summary": doc_summary, "tags": tags, "keywords": keywords},
                )
                if patched != dst_text:
                    dst.write_text(patched, encoding="utf-8")
            except Exception as e:
                logger.warning("frontmatter update skipped: %s", str(e))
            imported.append(dst.relative_to(paths.kb_dir).as_posix())
            logger.info("imported (auto) -> %s", imported[-1])
            return {"imported": imported, "mode": "auto", "dest_rel_dir": rel_dir, "suggestion": suggestion}
        except OpenAICompatError as e:
            logger.warning("auto archive failed, fallback to inbox: %s", str(e))

    rel_dir = default_inbox_dir()
    rel_dir = ensure_rel_under_base(rel_dir)
    dst_dir = paths.kb_dir / rel_dir
    ensure_dir_meta_chain(paths.kb_dir, rel_dir=rel_dir, meta_filename=meta_filename)
    src_text = src.read_text(encoding="utf-8", errors="replace")
    title = guess_title(src_text, fallback=src.stem)
    filename = default_filename(src, title=title)
    dst = dst_dir / filename
    copy_or_move(src, dst, move=move)
    imported.append(dst.relative_to(paths.kb_dir).as_posix())
    logger.info("imported (inbox) -> %s", imported[-1])
    return {"imported": imported, "mode": "inbox", "dest_rel_dir": rel_dir}


def _walk_markdown(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            if name.lower().endswith(".md"):
                yield Path(dirpath) / name
