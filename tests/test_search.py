import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb.bootstrap import init_kb
from kb.openai_compat import OpenAICompatError
from kb.search import RetrievedChunk, _fts_sim, search_kb
from kb.store_sqlite import init_schema, open_db, upsert_doc_and_chunks, upsert_embeddings
from kb.util import sha256_text


class TestSearchKB(unittest.TestCase):
    def test_search_raises_when_index_db_missing(self):
        """
        描述：索引库不存在时，search_kb 应抛出明确错误提示用户先 index。
        前置条件：仅 init_kb（不会创建 index.sqlite）。
        测试步骤：
          1) 调用 search_kb
        预期结果：
          - 抛 RuntimeError
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            with self.assertRaises(RuntimeError):
                search_kb(kb_root, query="x", top_k=5, semantic=False, hybrid=False)

    def test_search_fts_returns_retrieved_chunks(self):
        """
        描述：默认（fts）检索应返回 RetrievedChunk 列表并包含引用定位信息。
        前置条件：index.sqlite 已包含 docs/chunks/chunk_fts。
        测试步骤：
          1) 构造最小索引库（写入 1 doc + 1 chunk）
          2) 调用 search_kb(semantic=False, hybrid=False)
        预期结果：
          - 返回 list[RetrievedChunk]
          - source == 'fts'
          - line_range 信息正确（start_line/end_line > 0）
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            paths = (kb_root / "kb_index").expanduser().resolve()
            db_path = paths / "index.sqlite"

            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "notes/a.md"
                doc_id = sha256_text(rel_path)
                chunk_id = sha256_text(rel_path + "#0")
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
                    chunks=[
                        {
                            "chunk_id": chunk_id,
                            "chunk_index": 0,
                            "heading_path": "H1",
                            "start_line": 10,
                            "end_line": 12,
                            "text": "离线优先 工具",
                            "text_hash": sha256_text("离线优先 工具"),
                        }
                    ],
                    links=[],
                )
                conn.commit()
            finally:
                conn.close()

            hits = search_kb(kb_root, query="离线优先", top_k=3, semantic=False, hybrid=False)
            self.assertGreaterEqual(len(hits), 1)
            self.assertTrue(all(isinstance(h, RetrievedChunk) for h in hits))
            self.assertEqual(hits[0].source, "fts")
            self.assertGreater(hits[0].start_line, 0)
            self.assertGreaterEqual(hits[0].end_line, hits[0].start_line)

    def test_semantic_search_requires_embed_config(self):
        """
        描述：semantic/hybrid 模式下缺少 openai_compat.base_url/model_embed 时，应抛 OpenAICompatError。
        前置条件：索引库存在，但配置未设置 model_embed/base_url。
        测试步骤：
          1) 调用 search_kb(semantic=True)
        预期结果：
          - 抛 OpenAICompatError
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            db_path = (kb_root / "kb_index" / "index.sqlite").expanduser().resolve()
            conn = open_db(db_path)
            try:
                init_schema(conn)
                conn.commit()
            finally:
                conn.close()

            with self.assertRaises(OpenAICompatError):
                search_kb(kb_root, query="q", top_k=3, semantic=True, hybrid=False)

    def test_semantic_search_ranks_by_cosine_similarity(self):
        """
        描述：semantic 检索应基于 query embedding 与 chunk embeddings 的余弦相似度排序。
        前置条件：embeddings 表存在且包含同一 model 的向量；embed() 被 stub 返回 query 向量。
        测试步骤：
          1) 写入 2 个 chunk 的 embeddings（分别与 query 更相似/更不相似）
          2) patch kb.search.embed 返回 query=[1,0]
          3) 调用 search_kb(semantic=True)
        预期结果：
          - 第一个结果为更相似的 chunk
          - source == 'vec'
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            cfg_path = kb_root.expanduser().resolve() / "kb_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg.setdefault("openai_compat", {})
            cfg["openai_compat"].update({"base_url": "http://x", "model_embed": "m"})
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

            db_path = (kb_root / "kb_index" / "index.sqlite").expanduser().resolve()
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "d.md"
                doc_id = sha256_text(rel_path)
                c_good = sha256_text(rel_path + "#0")
                c_bad = sha256_text(rel_path + "#1")
                conn.execute("BEGIN")
                upsert_doc_and_chunks(
                    conn,
                    doc_id=doc_id,
                    rel_path=rel_path,
                    abs_path="/abs/d.md",
                    title="D",
                    summary="",
                    tags=[],
                    keywords=[],
                    mtime_ns=1,
                    size=1,
                    content_hash=sha256_text("doc"),
                    chunks=[
                        {"chunk_id": c_good, "chunk_index": 0, "heading_path": "", "start_line": 1, "end_line": 1, "text": "good", "text_hash": sha256_text("good")},
                        {"chunk_id": c_bad, "chunk_index": 1, "heading_path": "", "start_line": 2, "end_line": 2, "text": "bad", "text_hash": sha256_text("bad")},
                    ],
                    links=[],
                )
                upsert_embeddings(conn, model="m", embeddings=[(c_good, [1.0, 0.0]), (c_bad, [0.0, 1.0])])
                conn.commit()
            finally:
                conn.close()

            with patch("kb.search.embed", return_value=[[1.0, 0.0]]):
                hits = search_kb(kb_root, query="q", top_k=2, semantic=True, hybrid=False)
            self.assertEqual([h.chunk_id for h in hits], [c_good, c_bad])
            self.assertEqual(hits[0].source, "vec")

    def test_semantic_search_returns_empty_when_query_norm_is_zero(self):
        """
        描述：当 query embedding 的 L2 norm 为 0 时，semantic 检索应返回空结果（避免除零）。
        前置条件：embed() 返回全零向量；embeddings 表可以为空或任意。
        测试步骤：
          1) 配置 openai_compat.base_url/model_embed
          2) patch kb.search.embed 返回 [[0,0]]
          3) 调用 search_kb(semantic=True)
        预期结果：
          - 返回 []
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            cfg_path = kb_root.expanduser().resolve() / "kb_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg.setdefault("openai_compat", {})
            cfg["openai_compat"].update({"base_url": "http://x", "model_embed": "m"})
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

            db_path = (kb_root / "kb_index" / "index.sqlite").expanduser().resolve()
            conn = open_db(db_path)
            try:
                init_schema(conn)
                conn.commit()
            finally:
                conn.close()

            with patch("kb.search.embed", return_value=[[0.0, 0.0]]):
                hits = search_kb(kb_root, query="q", top_k=5, semantic=True, hybrid=False)
            self.assertEqual(hits, [])

    def test_hybrid_falls_back_to_fts_when_no_embeddings(self):
        """
        描述：hybrid 模式下若 vec_scores 为空，应回退到纯 FTS 合并逻辑。
        前置条件：db 存在但 embeddings 表为空；配置完整；embed() 返回任意向量。
        测试步骤：
          1) 写入 1 个可被 FTS 命中的 chunk
          2) 调用 search_kb(hybrid=True)
        预期结果：
          - source == 'fts'
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            cfg_path = kb_root.expanduser().resolve() / "kb_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg.setdefault("openai_compat", {})
            cfg["openai_compat"].update({"base_url": "http://x", "model_embed": "m"})
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

            db_path = (kb_root / "kb_index" / "index.sqlite").expanduser().resolve()
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "d.md"
                doc_id = sha256_text(rel_path)
                c0 = sha256_text(rel_path + "#0")
                conn.execute("BEGIN")
                upsert_doc_and_chunks(
                    conn,
                    doc_id=doc_id,
                    rel_path=rel_path,
                    abs_path="/abs/d.md",
                    title="D",
                    summary="",
                    tags=[],
                    keywords=[],
                    mtime_ns=1,
                    size=1,
                    content_hash=sha256_text("doc"),
                    chunks=[{"chunk_id": c0, "chunk_index": 0, "heading_path": "", "start_line": 1, "end_line": 1, "text": "离线优先", "text_hash": sha256_text("离线优先")}],
                    links=[],
                )
                conn.commit()
            finally:
                conn.close()

            with patch("kb.search.embed", return_value=[[1.0, 0.0]]):
                hits = search_kb(kb_root, query="离线优先", top_k=1, semantic=False, hybrid=True)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].source, "fts")

    def test_hybrid_marks_overlapping_candidates_as_hybrid_source(self):
        """
        描述：hybrid 模式下，当同一 chunk 同时出现在 fts 与 vec 中，应标记 source='hybrid'。
        前置条件：同一 chunk 既被 FTS 命中，也有 embedding；embed() 被 stub。
        测试步骤：
          1) 写入 1 个 chunk：文本含关键词，使其 FTS 命中
          2) 写入该 chunk 的 embedding
          3) 调用 search_kb(hybrid=True)
        预期结果：
          - 返回结果 source 为 'hybrid'（至少 top1）
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            cfg_path = kb_root.expanduser().resolve() / "kb_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg.setdefault("openai_compat", {})
            cfg["openai_compat"].update({"base_url": "http://x", "model_embed": "m"})
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

            db_path = (kb_root / "kb_index" / "index.sqlite").expanduser().resolve()
            conn = open_db(db_path)
            try:
                init_schema(conn)
                rel_path = "d.md"
                doc_id = sha256_text(rel_path)
                c0 = sha256_text(rel_path + "#0")
                conn.execute("BEGIN")
                upsert_doc_and_chunks(
                    conn,
                    doc_id=doc_id,
                    rel_path=rel_path,
                    abs_path="/abs/d.md",
                    title="D",
                    summary="",
                    tags=[],
                    keywords=[],
                    mtime_ns=1,
                    size=1,
                    content_hash=sha256_text("doc"),
                    chunks=[{"chunk_id": c0, "chunk_index": 0, "heading_path": "", "start_line": 1, "end_line": 1, "text": "离线优先", "text_hash": sha256_text("离线优先")}],
                    links=[],
                )
                upsert_embeddings(conn, model="m", embeddings=[(c0, [1.0, 0.0])])
                conn.commit()
            finally:
                conn.close()

            with patch("kb.search.embed", return_value=[[1.0, 0.0]]):
                hits = search_kb(kb_root, query="离线优先", top_k=1, semantic=False, hybrid=True)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].chunk_id, c0)
            self.assertEqual(hits[0].source, "hybrid")


class TestSearchHelpers(unittest.TestCase):
    def test_fts_sim_clamps_negative_scores(self):
        """
        描述：_fts_sim 应将负 bm25 分数归零并映射到 (0,1] 的相似度。
        前置条件：bm25_score < 0。
        测试步骤：
          1) 调用 _fts_sim(-1)
        预期结果：
          - 返回 1.0
        """
        self.assertEqual(_fts_sim(-1), 1.0)


if __name__ == "__main__":
    unittest.main()
