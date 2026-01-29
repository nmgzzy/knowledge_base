from __future__ import annotations

import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import load_config, resolve_paths
from .openai_compat import OpenAICompatError, embed, from_config_dict
from .store_sqlite import fetch_chunk_records, iter_embeddings, open_db, read_embedding, search_fts


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    rel_path: str
    title: str
    heading_path: str
    start_line: int
    end_line: int
    text: str
    score: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "path": self.rel_path,
            "title": self.title,
            "heading_path": self.heading_path,
            "line_range": [self.start_line, self.end_line],
            "score": self.score,
            "source": self.source,
            "text": self.text,
        }


def search_kb(
    kb_root: Path,
    *,
    query: str,
    top_k: int,
    semantic: bool,
    hybrid: bool,
    fts_k: Optional[int] = None,
    vec_k: Optional[int] = None,
) -> list[RetrievedChunk]:
    kb_root = kb_root.expanduser().resolve()
    cfg = load_config(kb_root)
    paths = resolve_paths(kb_root)
    db_path = paths.index_dir / "index.sqlite"
    if not db_path.exists():
        raise RuntimeError("index database not found, run: kb index")

    fts_k = fts_k or max(50, top_k * 5)
    vec_k = vec_k or max(50, top_k * 5)

    conn = open_db(db_path)
    try:
        fts_hits = search_fts(conn, query=query, limit=fts_k)
        fts_scores = {h.chunk_id: _fts_sim(h.score) for h in fts_hits}

        vec_scores: dict[str, float] = {}
        oa_cfg = from_config_dict(cfg.get("openai_compat", {}) if isinstance(cfg, dict) else {})
        if semantic or hybrid:
            vec_scores = _semantic_scores(conn, oa_cfg, query=query, top_k=vec_k)

        merged: dict[str, tuple[float, str]] = {}
        if hybrid and vec_scores:
            alpha = 0.6
            beta = 0.4
            for cid, s in fts_scores.items():
                merged[cid] = (alpha * s, "fts")
            for cid, s in vec_scores.items():
                prev = merged.get(cid)
                if prev is None:
                    merged[cid] = (beta * s, "vec")
                else:
                    merged[cid] = (prev[0] + beta * s, "hybrid")
        elif semantic and vec_scores:
            merged = {cid: (s, "vec") for cid, s in vec_scores.items()}
        else:
            merged = {cid: (s, "fts") for cid, s in fts_scores.items()}

        ranked = sorted(merged.items(), key=lambda x: x[1][0], reverse=True)[:top_k]
        chunk_ids = [cid for cid, _ in ranked]
        rows = fetch_chunk_records(conn, chunk_ids=chunk_ids)
        out: list[RetrievedChunk] = []
        for (cid, (score, source)), row in zip(ranked, rows):
            out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    rel_path=row["rel_path"],
                    title=row["title"] or "",
                    heading_path=row["heading_path"] or "",
                    start_line=int(row["start_line"] or 0),
                    end_line=int(row["end_line"] or 0),
                    text=row["text"] or "",
                    score=float(score),
                    source=source,
                )
            )
        return out
    finally:
        conn.close()


def _fts_sim(bm25_score: float) -> float:
    s = float(bm25_score)
    if s < 0:
        s = 0.0
    return 1.0 / (1.0 + s)


def _semantic_scores(conn, oa_cfg, *, query: str, top_k: int) -> dict[str, float]:
    if not (oa_cfg.base_url and oa_cfg.model_embed):
        raise OpenAICompatError("openai_compat.base_url/model_embed not configured")
    q = embed(oa_cfg, texts=[query])[0]
    qv = [float(x) for x in q]
    q_norm = _l2_norm_list(qv)
    if q_norm <= 0:
        return {}

    heap: list[tuple[float, str]] = []
    for chunk_id, dim, blob, norm in iter_embeddings(conn, model=oa_cfg.model_embed):
        if dim <= 0 or norm <= 0:
            continue
        v = read_embedding(blob)
        score = _dot_list_array(qv, v) / (q_norm * norm)
        if len(heap) < top_k:
            heapq.heappush(heap, (score, chunk_id))
        else:
            if score > heap[0][0]:
                heapq.heapreplace(heap, (score, chunk_id))

    best = sorted(heap, reverse=True)
    return {cid: float(max(0.0, s)) for s, cid in best}


def _dot_list_array(a: list[float], b) -> float:
    s = 0.0
    n = min(len(a), len(b))
    for i in range(n):
        s += float(a[i]) * float(b[i])
    return s


def _l2_norm_list(a: list[float]) -> float:
    s = 0.0
    for x in a:
        s += float(x) * float(x)
    return s**0.5
