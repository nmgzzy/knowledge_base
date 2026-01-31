from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

from .config import load_config, resolve_paths
from .fs_ops import ensure_dir_meta, read_dir_meta
from .markdown import chunk_markdown, extract_links, guess_title
from .openai_compat import OpenAICompatError, embed, from_config_dict
from .store_sqlite import (
    init_schema,
    log_action,
    open_db,
    upsert_dir_meta,
    upsert_doc_and_chunks,
    upsert_embeddings,
    delete_doc,
)
from .util import ensure_rel_under_base, now_iso, sha256_bytes, sha256_text

logger = logging.getLogger(__name__)


def index_kb(
    kb_root: Path,
    *,
    rebuild: bool,
    embed_chunks: bool,
    only_rel_paths: Optional[list[str]] = None,
) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    cfg = load_config(kb_root)
    paths = resolve_paths(kb_root)
    meta_filename = str(cfg.get("meta_filename", "meta.json"))
    db_path = paths.index_dir / "index.sqlite"

    logger.info(
        "index start kb_root=%s rebuild=%s embed=%s only=%s db=%s",
        str(kb_root),
        bool(rebuild),
        bool(embed_chunks),
        ",".join(only_rel_paths) if only_rel_paths else "",
        str(db_path),
    )

    if rebuild and db_path.exists():
        db_path.unlink()

    conn = open_db(db_path)
    try:
        init_schema(conn)

        conn.execute("BEGIN")
        _refresh_dir_meta_cache(conn, paths.kb_dir, meta_filename=meta_filename)
        conn.commit()

        existing = {
            r["rel_path"]: {
                "doc_id": r["doc_id"],
                "content_hash": r["content_hash"],
                "mtime_ns": int(r["mtime_ns"] or 0),
                "size": int(r["size"] or 0),
            }
            for r in conn.execute("SELECT doc_id, rel_path, content_hash, mtime_ns, size FROM docs")
        }

        cur_files = list(_scan_markdown_files(paths.kb_dir, meta_filename=meta_filename))
        if only_rel_paths:
            only = {ensure_rel_under_base(p) for p in only_rel_paths}
            cur_files = [p for p in cur_files if _rel_path(paths.kb_dir, p) in only]

        logger.info("scan markdown files=%d", len(cur_files))

        cur_rel_set = {_rel_path(paths.kb_dir, p) for p in cur_files}

        deleted = [v["doc_id"] for k, v in existing.items() if k not in cur_rel_set]
        changed: list[Path] = []
        unchanged = 0

        for abs_path in cur_files:
            rel_path = _rel_path(paths.kb_dir, abs_path)
            st = abs_path.stat()
            size = int(st.st_size)
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            raw = abs_path.read_bytes()
            content_hash = sha256_bytes(raw)
            prev = existing.get(rel_path)
            if prev and prev["content_hash"] == content_hash and prev["size"] == size and prev["mtime_ns"] == mtime_ns:
                unchanged += 1
                continue
            changed.append(abs_path)

        logger.info("diff deleted=%d changed=%d unchanged=%d", len(deleted), len(changed), unchanged)

        updated_docs = 0
        updated_chunks = 0
        embedded_chunks_n = 0

        conn.execute("BEGIN")
        for doc_id in deleted:
            delete_doc(conn, doc_id=doc_id)
        conn.commit()

        oa_cfg = from_config_dict(cfg.get("openai_compat", {}) if isinstance(cfg, dict) else {})
        can_embed = embed_chunks and bool(oa_cfg.base_url and oa_cfg.model_embed)
        if embed_chunks and not can_embed:
            logger.warning("embed requested but openai_compat.base_url/model_embed not configured")

        for i, abs_path in enumerate(changed, start=1):
            rel_path = _rel_path(paths.kb_dir, abs_path)
            logger.info("indexing %d/%d: %s", i, len(changed), rel_path)
            st = abs_path.stat()
            raw = abs_path.read_bytes()
            content_hash = sha256_bytes(raw)
            text = raw.decode("utf-8", errors="replace")

            fm, chunks = chunk_markdown(
                text,
                max_chars=int(cfg.get("chunking", {}).get("max_chars", 1200)),
                overlap_chars=int(cfg.get("chunking", {}).get("overlap_chars", 150)),
                min_chars=int(cfg.get("chunking", {}).get("min_chars", 80)),
            )

            title = str(fm.get("title") or "").strip() or guess_title(text, fallback=Path(rel_path).stem)
            tags = _as_str_list(fm.get("tags"))
            keywords = _as_str_list(fm.get("keywords"))
            summary = str(fm.get("summary") or "").strip()
            if not summary and chunks:
                summary = chunks[0].text.replace("\n", " ").strip()[:220]

            chunk_dicts: list[dict[str, Any]] = []
            for ch in chunks:
                chunk_id = sha256_text(f"{rel_path}#{ch.chunk_index}")
                chunk_dicts.append(
                    {
                        "chunk_id": chunk_id,
                        "chunk_index": ch.chunk_index,
                        "heading_path": ch.heading_path,
                        "start_line": ch.start_line,
                        "end_line": ch.end_line,
                        "text": ch.text,
                        "text_hash": ch.text_hash,
                    }
                )

            links = extract_links(text)
            doc_id = sha256_text(rel_path)
            conn = _transactional_upsert(
                conn,
                doc_id=doc_id,
                rel_path=rel_path,
                abs_path=str(abs_path),
                title=title,
                summary=summary,
                tags=tags,
                keywords=keywords,
                mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                size=int(st.st_size),
                content_hash=content_hash,
                chunk_dicts=chunk_dicts,
                links=links,
            )

            updated_docs += 1
            updated_chunks += len(chunk_dicts)

            if can_embed and chunk_dicts:
                try:
                    logger.info("embedding chunks=%d: %s", len(chunk_dicts), rel_path)
                    vecs = _embed_in_batches(oa_cfg, [c["text"] for c in chunk_dicts], batch_size=32)
                    conn.execute("BEGIN")
                    upsert_embeddings(conn, model=oa_cfg.model_embed, embeddings=list(zip([c["chunk_id"] for c in chunk_dicts], vecs)))
                    conn.commit()
                    embedded_chunks_n += len(chunk_dicts)
                except OpenAICompatError as e:
                    conn.rollback()
                    logger.warning("embedding failed, skip: %s (%s)", rel_path, str(e))

        conn.execute("BEGIN")
        log_action(
            conn,
            "index",
            {
                "ts": now_iso(),
                "rebuild": rebuild,
                "deleted_docs": len(deleted),
                "updated_docs": updated_docs,
                "updated_chunks": updated_chunks,
                "embedded_chunks": embedded_chunks_n,
                "unchanged_docs": unchanged,
            },
        )
        conn.commit()

        logger.info(
            "index done deleted=%d updated_docs=%d updated_chunks=%d embedded_chunks=%d unchanged=%d",
            len(deleted),
            updated_docs,
            updated_chunks,
            embedded_chunks_n,
            unchanged,
        )
        return {
            "deleted_docs": len(deleted),
            "updated_docs": updated_docs,
            "updated_chunks": updated_chunks,
            "embedded_chunks": embedded_chunks_n,
            "unchanged_docs": unchanged,
            "db_path": str(db_path),
        }
    finally:
        conn.close()


def _transactional_upsert(
    conn,
    *,
    doc_id: str,
    rel_path: str,
    abs_path: str,
    title: str,
    summary: str,
    tags: list[str],
    keywords: list[str],
    mtime_ns: int,
    size: int,
    content_hash: str,
    chunk_dicts: list[dict[str, Any]],
    links: list[dict[str, str]],
):
    conn.execute("BEGIN")
    upsert_doc_and_chunks(
        conn,
        doc_id=doc_id,
        rel_path=rel_path,
        abs_path=abs_path,
        title=title,
        summary=summary,
        tags=tags,
        keywords=keywords,
        mtime_ns=mtime_ns,
        size=size,
        content_hash=content_hash,
        chunks=chunk_dicts,
        links=links,
    )
    conn.commit()
    return conn


def _refresh_dir_meta_cache(conn, kb_dir: Path, *, meta_filename: str) -> None:
    ensure_dir_meta(kb_dir, meta_filename=meta_filename)
    for dirpath, dirnames, _ in os.walk(kb_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        dp = Path(dirpath)
        meta = read_dir_meta(dp, meta_filename=meta_filename)
        rel = _rel_dir(kb_dir, dp)
        upsert_dir_meta(conn, dir_rel_path=rel, meta=meta)


def _scan_markdown_files(kb_dir: Path, *, meta_filename: str) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(kb_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            if name == meta_filename:
                continue
            if not name.lower().endswith(".md"):
                continue
            yield Path(dirpath) / name


def _rel_path(kb_dir: Path, abs_path: Path) -> str:
    return abs_path.relative_to(kb_dir).as_posix()


def _rel_dir(kb_dir: Path, abs_dir: Path) -> str:
    rel = abs_dir.relative_to(kb_dir).as_posix()
    return rel if rel else "."


def _as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    if isinstance(v, list):
        out = []
        for x in v:
            if x is None:
                continue
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
        return out
    return []


def _embed_in_batches(oa_cfg, texts: list[str], *, batch_size: int) -> list[list[float]]:
    out: list[list[float]] = []
    i = 0
    while i < len(texts):
        batch = texts[i : i + batch_size]
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("embed batch %d-%d/%d", i + 1, min(i + len(batch), len(texts)), len(texts))
        out.extend(embed(oa_cfg, texts=batch))
        i += batch_size
    return out
