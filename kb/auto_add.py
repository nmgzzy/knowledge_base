from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from .config import load_config, resolve_paths
from .fs_ops import ensure_dir_meta, merge_meta, read_dir_meta
from .openai_compat import OpenAICompatError, chat_completion, from_config_dict
from .util import ensure_rel_under_base, now_iso, write_json_atomic

logger = logging.getLogger(__name__)


_re_json_obj = re.compile(r"\{[\s\S]*\}")


def suggest_destination_with_llm(kb_root: Path, *, src_text: str, src_name: str) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    cfg = load_config(kb_root)
    oa_cfg = from_config_dict(cfg.get("openai_compat", {}) if isinstance(cfg, dict) else {})
    dirs = _collect_dir_summaries(resolve_paths(kb_root).kb_dir, meta_filename=str(cfg.get("meta_filename", "meta.json")))

    excerpt = src_text.strip()
    if len(excerpt) > 8000:
        excerpt = excerpt[:8000]

    logger.info("llm suggest src=%s excerpt_chars=%d dirs=%d", src_name, len(excerpt), len(dirs))
    messages = [
        {
            "role": "system",
            "content": "你是一个本地知识库的归档助手。根据目录元数据与文档内容，输出严格 JSON，不要输出多余文字。",
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "now": now_iso(),
                    "existing_dirs": dirs,
                    "document": {"filename": src_name, "excerpt": excerpt},
                    "required_json_schema": {
                        "doc_title": "string",
                        "doc_summary": "string",
                        "tags": ["string"],
                        "keywords": ["string"],
                        "suggested_rel_dir": "string",
                        "suggested_filename": "string",
                        "dir_meta": "object",
                    },
                    "constraints": [
                        "suggested_rel_dir 必须是 kb/ 下的相对路径，不能包含 .. 或绝对路径",
                        "suggested_filename 可选，若为空使用原文件名",
                        "dir_meta 仅在需要新建目录或补全目录元数据时给出",
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw = chat_completion(oa_cfg, messages=messages)
    obj = _extract_json_object(raw)
    if not isinstance(obj, dict):
        raise OpenAICompatError("invalid JSON from model")
    return obj


def apply_auto_suggestion(
    kb_root: Path,
    *,
    suggestion: dict[str, Any],
    meta_filename: str,
) -> tuple[str, str, dict[str, Any]]:
    rel_dir = ensure_rel_under_base(str(suggestion.get("suggested_rel_dir", "")).strip())
    filename = str(suggestion.get("suggested_filename", "")).strip()
    if filename:
        filename = filename.replace("\\", "/").split("/")[-1]
    dir_meta_patch = suggestion.get("dir_meta")
    if not isinstance(dir_meta_patch, dict):
        dir_meta_patch = {}

    paths = resolve_paths(kb_root)
    target_dir = paths.kb_dir / rel_dir if rel_dir else paths.kb_dir
    ensure_dir_meta(target_dir, meta_filename=meta_filename)
    existing = read_dir_meta(target_dir, meta_filename=meta_filename)
    merged = merge_meta(existing, dir_meta_patch)
    write_json_atomic(target_dir / meta_filename, merged)
    logger.info("apply suggestion rel_dir=%s filename=%s", rel_dir, filename)
    return rel_dir, filename, merged


def default_inbox_dir() -> str:
    return f"inbox/{now_iso()[:7]}"


def default_filename(src_path: Path, *, title: Optional[str] = None) -> str:
    name = src_path.name
    if name.lower().endswith(".md"):
        return name
    base = (title or src_path.stem).strip() or src_path.stem
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", base).strip("_")
    return f"{safe}.md" if safe else f"{src_path.stem}.md"


def _collect_dir_summaries(kb_dir: Path, *, meta_filename: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(kb_dir):
        rel = Path(dirpath).relative_to(kb_dir).as_posix() or "."
        depth = 0 if rel == "." else rel.count("/") + 1
        if depth > 4:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if meta_filename not in filenames:
            continue
        meta = read_dir_meta(Path(dirpath), meta_filename=meta_filename)
        out.append(
            {
                "rel_dir": rel,
                "title": str(meta.get("title", "")),
                "summary": str(meta.get("summary", "")),
                "tags": meta.get("tags", []),
                "keywords": meta.get("keywords", []),
                "dir_type": str(meta.get("dir_type", "")),
            }
        )
        if len(out) >= 200:
            break
    return out


def _extract_json_object(raw: str) -> Any:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = _re_json_obj.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None
