from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_config
from .openai_compat import chat_completion, from_config_dict
from .search import RetrievedChunk, search_kb


def ask_kb(
    kb_root: Path,
    *,
    query: str,
    top_context: int,
    semantic: bool,
    hybrid: bool,
) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    cfg = load_config(kb_root)
    oa_cfg = from_config_dict(cfg.get("openai_compat", {}) if isinstance(cfg, dict) else {})

    chunks = search_kb(
        kb_root,
        query=query,
        top_k=top_context,
        semantic=semantic,
        hybrid=hybrid,
    )
    sources_text = _format_sources(chunks)
    messages = [
        {
            "role": "system",
            "content": "你是一个离线知识库问答助手。只能基于给定 Sources 回答；若信息不足，明确说明。回答中用 [n] 引用 Sources。",
        },
        {"role": "user", "content": f"Question:\n{query}\n\nSources:\n{sources_text}"},
    ]
    answer = chat_completion(oa_cfg, messages=messages)
    return {"query": query, "answer": answer, "sources": [c.to_dict() for c in chunks]}


def _format_sources(chunks: list[RetrievedChunk]) -> str:
    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        loc = f"{c.rel_path}#{c.start_line}-{c.end_line}"
        hp = c.heading_path
        header = f"[{i}] {loc}"
        if hp:
            header += f" | {hp}"
        parts.append(header + "\n" + c.text)
    return "\n\n".join(parts)
