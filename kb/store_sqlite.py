from __future__ import annotations

import sqlite3
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .util import json_dumps_compact, now_iso, sha256_text


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    score: float


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS docs (
          doc_id TEXT PRIMARY KEY,
          rel_path TEXT UNIQUE NOT NULL,
          abs_path TEXT NOT NULL,
          title TEXT,
          summary TEXT,
          tags_json TEXT,
          keywords_json TEXT,
          mtime_ns INTEGER,
          size INTEGER,
          content_hash TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
          chunk_id TEXT PRIMARY KEY,
          doc_id TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          heading_path TEXT,
          start_line INTEGER,
          end_line INTEGER,
          text TEXT NOT NULL,
          text_hash TEXT NOT NULL,
          FOREIGN KEY(doc_id) REFERENCES docs(doc_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)")

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts
        USING fts5(chunk_id UNINDEXED, text, title, rel_path, heading_path, tokenize='unicode61')
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
          chunk_id TEXT PRIMARY KEY,
          model TEXT NOT NULL,
          dim INTEGER NOT NULL,
          embedding BLOB NOT NULL,
          norm REAL NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dirs (
          dir_rel_path TEXT PRIMARY KEY,
          meta_json TEXT NOT NULL,
          meta_hash TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_rel_path TEXT NOT NULL,
          target TEXT NOT NULL,
          kind TEXT NOT NULL,
          anchor TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          action TEXT NOT NULL,
          details_json TEXT
        )
        """
    )
    conn.commit()


def log_action(conn: sqlite3.Connection, action: str, details: Optional[dict[str, Any]] = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(ts, action, details_json) VALUES (?, ?, ?)",
        (now_iso(), action, json_dumps_compact(details) if details is not None else None),
    )


def upsert_dir_meta(conn: sqlite3.Connection, *, dir_rel_path: str, meta: dict[str, Any]) -> None:
    meta_json = json_dumps_compact(meta)
    meta_hash = sha256_text(meta_json)
    conn.execute(
        """
        INSERT INTO dirs(dir_rel_path, meta_json, meta_hash, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dir_rel_path) DO UPDATE SET
          meta_json=excluded.meta_json,
          meta_hash=excluded.meta_hash,
          updated_at=excluded.updated_at
        """,
        (dir_rel_path, meta_json, meta_hash, now_iso()),
    )


def delete_doc(conn: sqlite3.Connection, *, doc_id: str) -> None:
    row = conn.execute("SELECT rel_path FROM docs WHERE doc_id=?", (doc_id,)).fetchone()
    if row is None:
        return
    rel_path = row["rel_path"]
    chunk_ids = [r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks WHERE doc_id=?", (doc_id,))]
    if chunk_ids:
        conn.executemany("DELETE FROM embeddings WHERE chunk_id=?", [(cid,) for cid in chunk_ids])
    conn.execute("DELETE FROM chunk_fts WHERE rel_path=?", (rel_path,))
    conn.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))


def upsert_doc_and_chunks(
    conn: sqlite3.Connection,
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
    chunks: Iterable[dict[str, Any]],
    links: Iterable[dict[str, str]],
) -> None:
    conn.execute(
        """
        INSERT INTO docs(doc_id, rel_path, abs_path, title, summary, tags_json, keywords_json, mtime_ns, size, content_hash, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id) DO UPDATE SET
          rel_path=excluded.rel_path,
          abs_path=excluded.abs_path,
          title=excluded.title,
          summary=excluded.summary,
          tags_json=excluded.tags_json,
          keywords_json=excluded.keywords_json,
          mtime_ns=excluded.mtime_ns,
          size=excluded.size,
          content_hash=excluded.content_hash,
          updated_at=excluded.updated_at
        """,
        (
            doc_id,
            rel_path,
            abs_path,
            title,
            summary,
            json_dumps_compact(tags),
            json_dumps_compact(keywords),
            mtime_ns,
            size,
            content_hash,
            now_iso(),
        ),
    )

    old_chunk_ids = [r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks WHERE doc_id=?", (doc_id,))]
    if old_chunk_ids:
        conn.executemany("DELETE FROM embeddings WHERE chunk_id=?", [(cid,) for cid in old_chunk_ids])
    conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM chunk_fts WHERE rel_path=?", (rel_path,))
    conn.execute("DELETE FROM links WHERE source_rel_path=?", (rel_path,))

    chunk_rows: list[tuple[Any, ...]] = []
    fts_rows: list[tuple[Any, ...]] = []
    for ch in chunks:
        chunk_id = ch["chunk_id"]
        chunk_rows.append(
            (
                chunk_id,
                doc_id,
                int(ch["chunk_index"]),
                ch.get("heading_path") or "",
                int(ch.get("start_line") or 0),
                int(ch.get("end_line") or 0),
                ch["text"],
                ch["text_hash"],
            )
        )
        fts_rows.append(
            (
                chunk_id,
                _fts_text(ch["text"]),
                _fts_text(title),
                rel_path,
                _fts_text(ch.get("heading_path") or ""),
            )
        )

    if chunk_rows:
        conn.executemany(
            """
            INSERT INTO chunks(chunk_id, doc_id, chunk_index, heading_path, start_line, end_line, text, text_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            chunk_rows,
        )
        conn.executemany(
            "INSERT INTO chunk_fts(chunk_id, text, title, rel_path, heading_path) VALUES (?, ?, ?, ?, ?)",
            fts_rows,
        )

    link_rows = [(rel_path, lk.get("target", ""), lk.get("kind", "md"), lk.get("anchor")) for lk in links if lk.get("target")]
    if link_rows:
        conn.executemany(
            "INSERT INTO links(source_rel_path, target, kind, anchor) VALUES (?, ?, ?, ?)",
            link_rows,
        )


def upsert_embeddings(
    conn: sqlite3.Connection,
    *,
    model: str,
    embeddings: Iterable[tuple[str, list[float]]],
) -> None:
    rows: list[tuple[Any, ...]] = []
    for chunk_id, vec in embeddings:
        arr = array("f", [float(x) for x in vec])
        norm = _l2_norm(arr)
        rows.append((chunk_id, model, len(arr), arr.tobytes(), float(norm), now_iso()))
    if not rows:
        return
    conn.executemany(
        """
        INSERT INTO embeddings(chunk_id, model, dim, embedding, norm, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chunk_id) DO UPDATE SET
          model=excluded.model,
          dim=excluded.dim,
          embedding=excluded.embedding,
          norm=excluded.norm,
          created_at=excluded.created_at
        """,
        rows,
    )


def search_fts(conn: sqlite3.Connection, *, query: str, limit: int) -> list[SearchHit]:
    q = _fts_query(query)
    rows = conn.execute(
        """
        SELECT chunk_id, bm25(chunk_fts) AS score
        FROM chunk_fts
        WHERE chunk_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (q, limit),
    ).fetchall()
    return [SearchHit(chunk_id=r["chunk_id"], score=float(r["score"])) for r in rows]


def fetch_chunk_records(conn: sqlite3.Connection, *, chunk_ids: list[str]) -> list[sqlite3.Row]:
    if not chunk_ids:
        return []
    placeholders = ",".join(["?"] * len(chunk_ids))
    rows = conn.execute(
        f"""
        SELECT c.chunk_id, c.chunk_index, c.heading_path, c.start_line, c.end_line, c.text,
               d.rel_path, d.title
        FROM chunks c
        JOIN docs d ON d.doc_id = c.doc_id
        WHERE c.chunk_id IN ({placeholders})
        """,
        chunk_ids,
    ).fetchall()
    by_id = {r["chunk_id"]: r for r in rows}
    return [by_id[cid] for cid in chunk_ids if cid in by_id]


def iter_embeddings(conn: sqlite3.Connection, *, model: str) -> Iterable[tuple[str, int, bytes, float]]:
    cur = conn.execute("SELECT chunk_id, dim, embedding, norm FROM embeddings WHERE model=?", (model,))
    for r in cur:
        yield (r["chunk_id"], int(r["dim"]), bytes(r["embedding"]), float(r["norm"]))


def read_embedding(blob: bytes) -> array:
    arr = array("f")
    arr.frombytes(blob)
    return arr


def _l2_norm(arr: array) -> float:
    s = 0.0
    for x in arr:
        s += float(x) * float(x)
    return s ** 0.5


def _fts_text(text: str) -> str:
    return _cjk_space(text)


def _fts_query(query: str) -> str:
    q = query.strip()
    if not q:
        return q
    if " " in q or "\t" in q or "\n" in q:
        return q
    if _contains_cjk(q):
        phrase = _cjk_space(q).strip()
        phrase = phrase.replace('"', "")
        return f"\"{phrase}\""
    return q


def _contains_cjk(text: str) -> bool:
    for ch in text:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            return True
        if 0x3400 <= o <= 0x4DBF:
            return True
        if 0xF900 <= o <= 0xFAFF:
            return True
    return False


def _cjk_space(text: str) -> str:
    out: list[str] = []
    for ch in text:
        out.append(ch)
        if _contains_cjk(ch):
            out.append(" ")
    return "".join(out)
