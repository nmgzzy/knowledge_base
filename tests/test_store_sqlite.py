import sqlite3
import tempfile
import unittest
from pathlib import Path

from kb.store_sqlite import (
    delete_doc,
    fetch_chunk_records,
    init_schema,
    iter_embeddings,
    log_action,
    open_db,
    read_embedding,
    search_fts,
    upsert_doc_and_chunks,
    upsert_dir_meta,
    upsert_embeddings,
)
from kb.util import sha256_text


class TestSQLiteSchemaAndUpsert(unittest.TestCase):
    def test_init_schema_creates_expected_tables(self):
        """
        描述：init_schema 应创建第一版所需的核心表与 FTS5 虚表。
        前置条件：连接到新建的 SQLite 数据库。
        测试步骤：
          1) open_db + init_schema
          2) 查询 sqlite_master
        预期结果：
          - docs/chunks/embeddings/dirs/links/audit_log 存在
          - chunk_fts（FTS5）存在
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rows = conn.execute("SELECT name, type FROM sqlite_master").fetchall()
                names = {(r["name"], r["type"]) for r in rows}
                for t in ("docs", "chunks", "embeddings", "dirs", "links", "audit_log"):
                    self.assertIn((t, "table"), names)
                self.assertTrue(any(n == "chunk_fts" for n, _ in names))
            finally:
                conn.close()

    def test_log_action_inserts_audit_row(self):
        """
        描述：log_action 应向 audit_log 插入一条记录。
        前置条件：已 init_schema。
        测试步骤：
          1) 调用 log_action(conn, action, details)
          2) 查询 audit_log
        预期结果：
          - audit_log 行数增加
          - action 字段正确
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                conn.execute("BEGIN")
                log_action(conn, "index", {"x": 1})
                conn.commit()
                row = conn.execute("SELECT action, details_json FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
                self.assertEqual(row["action"], "index")
                self.assertIn('"x":1', row["details_json"])
            finally:
                conn.close()

    def test_upsert_dir_meta_is_idempotent(self):
        """
        描述：upsert_dir_meta 应支持重复写入同一路径并更新 meta_hash。
        前置条件：已 init_schema。
        测试步骤：
          1) upsert_dir_meta 写入 meta1
          2) upsert_dir_meta 写入 meta2（不同内容）
        预期结果：
          - dirs 表中仍只有 1 条记录
          - meta_hash 随 meta 变化而变化
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                conn.execute("BEGIN")
                upsert_dir_meta(conn, dir_rel_path="notes", meta={"title": "A"})
                conn.commit()
                row1 = conn.execute("SELECT meta_hash FROM dirs WHERE dir_rel_path='notes'").fetchone()

                conn.execute("BEGIN")
                upsert_dir_meta(conn, dir_rel_path="notes", meta={"title": "B"})
                conn.commit()
                row2 = conn.execute("SELECT meta_hash FROM dirs WHERE dir_rel_path='notes'").fetchone()

                self.assertNotEqual(row1["meta_hash"], row2["meta_hash"])
                n = int(conn.execute("SELECT COUNT(*) AS n FROM dirs WHERE dir_rel_path='notes'").fetchone()["n"])
                self.assertEqual(n, 1)
            finally:
                conn.close()

    def test_upsert_doc_and_chunks_then_search_and_fetch(self):
        """
        描述：upsert_doc_and_chunks 应写入 docs/chunks/chunk_fts/links，并可被 search_fts 与 fetch_chunk_records 使用。
        前置条件：已 init_schema。
        测试步骤：
          1) upsert_doc_and_chunks 写入 1 篇文档（含 2 个 chunk 与 2 个 link）
          2) search_fts 查询关键词
          3) fetch_chunk_records 拉取 chunk 详情
        预期结果：
          - search_fts 返回至少 1 个命中 chunk_id
          - fetch_chunk_records 返回的 rel_path/title/heading_path/text 等字段正确
          - links 表写入 2 条记录
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "notes/demo.md"
                doc_id = sha256_text(rel_path)
                chunks = [
                    {
                        "chunk_id": sha256_text(rel_path + "#0"),
                        "chunk_index": 0,
                        "heading_path": "H1",
                        "start_line": 1,
                        "end_line": 3,
                        "text": "离线优先 知识库 工具",
                        "text_hash": sha256_text("离线优先 知识库 工具"),
                    },
                    {
                        "chunk_id": sha256_text(rel_path + "#1"),
                        "chunk_index": 1,
                        "heading_path": "H1 > H2",
                        "start_line": 4,
                        "end_line": 7,
                        "text": "支持关键词检索与引用定位。",
                        "text_hash": sha256_text("支持关键词检索与引用定位。"),
                    },
                ]
                links = [{"kind": "md", "target": "https://example.com"}, {"kind": "wiki", "target": "Some Page"}]

                conn.execute("BEGIN")
                upsert_doc_and_chunks(
                    conn,
                    doc_id=doc_id,
                    rel_path=rel_path,
                    abs_path="/abs/demo.md",
                    title="Demo",
                    summary="S",
                    tags=["t1"],
                    keywords=["k1"],
                    mtime_ns=1,
                    size=2,
                    content_hash=sha256_text("doc"),
                    chunks=chunks,
                    links=links,
                )
                conn.commit()

                hits = search_fts(conn, query="离线优先", limit=10)
                self.assertGreaterEqual(len(hits), 1)
                chunk_ids = [h.chunk_id for h in hits]

                rows = fetch_chunk_records(conn, chunk_ids=chunk_ids[:1])
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["rel_path"], rel_path)
                self.assertEqual(row["title"], "Demo")
                self.assertTrue(row["text"])

                link_count = conn.execute("SELECT COUNT(*) AS n FROM links WHERE source_rel_path=?", (rel_path,)).fetchone()["n"]
                self.assertEqual(int(link_count), 2)
            finally:
                conn.close()

    def test_delete_doc_removes_chunks_fts_and_embeddings(self):
        """
        描述：delete_doc 应删除 docs 并级联清理 chunks，且主动清理 chunk_fts 与 embeddings。
        前置条件：已写入 1 篇文档 + 2 个 chunk + embeddings。
        测试步骤：
          1) upsert_doc_and_chunks 写入数据
          2) upsert_embeddings 写入向量
          3) delete_doc 删除 doc
        预期结果：
          - docs/chunks/embeddings/chunk_fts 均无该文档相关记录
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "notes/demo.md"
                doc_id = sha256_text(rel_path)
                c0 = sha256_text(rel_path + "#0")
                c1 = sha256_text(rel_path + "#1")
                chunks = [
                    {"chunk_id": c0, "chunk_index": 0, "heading_path": "", "start_line": 1, "end_line": 1, "text": "hello world", "text_hash": sha256_text("hello world")},
                    {"chunk_id": c1, "chunk_index": 1, "heading_path": "", "start_line": 2, "end_line": 2, "text": "another line", "text_hash": sha256_text("another line")},
                ]

                conn.execute("BEGIN")
                upsert_doc_and_chunks(
                    conn,
                    doc_id=doc_id,
                    rel_path=rel_path,
                    abs_path="/abs/demo.md",
                    title="Demo",
                    summary="",
                    tags=[],
                    keywords=[],
                    mtime_ns=1,
                    size=1,
                    content_hash=sha256_text("doc"),
                    chunks=chunks,
                    links=[],
                )
                upsert_embeddings(conn, model="m", embeddings=[(c0, [1.0, 0.0]), (c1, [0.0, 1.0])])
                conn.commit()

                self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"], 2)

                conn.execute("BEGIN")
                delete_doc(conn, doc_id=doc_id)
                conn.commit()

                self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM chunk_fts WHERE rel_path=?",(rel_path,)).fetchone()["n"], 0)
            finally:
                conn.close()


class TestEmbeddingsHelpers(unittest.TestCase):
    def test_upsert_embeddings_iter_and_read_embedding(self):
        """
        描述：upsert_embeddings 应写入 BLOB，并可被 iter_embeddings/read_embedding 读出。
        前置条件：已 init_schema。
        测试步骤：
          1) upsert_embeddings 写入向量
          2) iter_embeddings 迭代
          3) read_embedding 反序列化 BLOB
        预期结果：
          - dim 与输入一致
          - norm > 0
          - read_embedding 后的数值与输入近似相等
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                conn.execute("BEGIN")
                upsert_embeddings(conn, model="m", embeddings=[("c0", [3.0, 4.0])])
                conn.commit()

                items = list(iter_embeddings(conn, model="m"))
                self.assertEqual(len(items), 1)
                chunk_id, dim, blob, norm = items[0]
                self.assertEqual(chunk_id, "c0")
                self.assertEqual(dim, 2)
                self.assertAlmostEqual(norm, 5.0, places=5)

                arr = read_embedding(blob)
                self.assertEqual(len(arr), 2)
                self.assertAlmostEqual(float(arr[0]), 3.0, places=5)
                self.assertAlmostEqual(float(arr[1]), 4.0, places=5)
            finally:
                conn.close()

    def test_fetch_chunk_records_preserves_input_order(self):
        """
        描述：fetch_chunk_records 应按输入 chunk_ids 的顺序返回记录（便于上层保持 rank 顺序）。
        前置条件：已写入 2 个 chunk。
        测试步骤：
          1) 以倒序 chunk_ids 调用 fetch_chunk_records
        预期结果：
          - 返回 rows 的 chunk_id 顺序与输入一致
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "index.sqlite"
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "a.md"
                doc_id = sha256_text(rel_path)
                c0 = sha256_text(rel_path + "#0")
                c1 = sha256_text(rel_path + "#1")
                chunks = [
                    {"chunk_id": c0, "chunk_index": 0, "heading_path": "", "start_line": 1, "end_line": 1, "text": "x", "text_hash": sha256_text("x")},
                    {"chunk_id": c1, "chunk_index": 1, "heading_path": "", "start_line": 2, "end_line": 2, "text": "y", "text_hash": sha256_text("y")},
                ]
                conn.execute("BEGIN")
                upsert_doc_and_chunks(
                    conn,
                    doc_id=doc_id,
                    rel_path=rel_path,
                    abs_path="/abs/a.md",
                    title="A",
                    summary="",
                    tags=[],
                    keywords=[],
                    mtime_ns=1,
                    size=1,
                    content_hash=sha256_text("doc"),
                    chunks=chunks,
                    links=[],
                )
                conn.commit()

                rows = fetch_chunk_records(conn, chunk_ids=[c1, c0])
                self.assertEqual([r["chunk_id"] for r in rows], [c1, c0])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
