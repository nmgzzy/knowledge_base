import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb.bootstrap import init_kb
from kb.indexer import index_kb
from kb.openai_compat import OpenAICompatError
from kb.store_sqlite import open_db


class TestIndexerBasicFlow(unittest.TestCase):
    def test_index_is_incremental_and_detects_deletions(self):
        """
        描述：index_kb 应支持增量更新（未变更文档计入 unchanged_docs）并能识别删除。
        前置条件：已 init_kb；kb/ 下存在 1 个 Markdown 文档。
        测试步骤：
          1) 第一次 index_kb(rebuild=False)
          2) 第二次 index_kb(rebuild=False)（不修改文件）
          3) 删除该文件后再次 index_kb
        预期结果：
          - 第一次 updated_docs >= 1
          - 第二次 updated_docs == 0 且 unchanged_docs >= 1
          - 删除后 deleted_docs >= 1
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            kb_dir = (kb_root / "kb").expanduser().resolve()

            p = kb_dir / "notes"
            p.mkdir(parents=True, exist_ok=True)
            doc = p / "demo.md"
            doc.write_text("# 标题\n\n离线优先。\n", encoding="utf-8")

            out1 = index_kb(kb_root, rebuild=False, embed_chunks=False)
            self.assertGreaterEqual(out1["updated_docs"], 1)

            out2 = index_kb(kb_root, rebuild=False, embed_chunks=False)
            self.assertEqual(out2["updated_docs"], 0)
            self.assertGreaterEqual(out2["unchanged_docs"], 1)

            doc.unlink()
            out3 = index_kb(kb_root, rebuild=False, embed_chunks=False)
            self.assertGreaterEqual(out3["deleted_docs"], 1)

    def test_only_rel_paths_limits_index_scope(self):
        """
        描述：index_kb(only_rel_paths=...) 应仅处理指定的相对路径集合。
        前置条件：kb/ 下存在 2 个 Markdown 文档。
        测试步骤：
          1) index_kb(rebuild=True, only_rel_paths=[...])
        预期结果：
          - updated_docs == 1
          - docs 表中仅包含被选中文档
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            kb_dir = (kb_root / "kb").expanduser().resolve()

            (kb_dir / "a").mkdir(parents=True, exist_ok=True)
            (kb_dir / "b").mkdir(parents=True, exist_ok=True)
            (kb_dir / "a" / "one.md").write_text("# One\n\nA\n", encoding="utf-8")
            (kb_dir / "b" / "two.md").write_text("# Two\n\nB\n", encoding="utf-8")

            out = index_kb(kb_root, rebuild=True, embed_chunks=False, only_rel_paths=["a/one.md"])
            self.assertEqual(out["updated_docs"], 1)

            db_path = Path(out["db_path"])
            conn = open_db(db_path)
            try:
                rows = conn.execute("SELECT rel_path FROM docs").fetchall()
                rels = sorted([r["rel_path"] for r in rows])
                self.assertEqual(rels, ["a/one.md"])
            finally:
                conn.close()

    def test_rebuild_drops_previous_db_and_scan_ignores_non_md_and_hidden(self):
        """
        描述：rebuild=True 应删除旧数据库并重建；扫描时应忽略 meta.json、隐藏文件与非 .md。
        前置条件：已 init_kb；kb/ 下存在 .md/.txt/.hidden.md 与 meta.json。
        测试步骤：
          1) index_kb(rebuild=True)
          2) 删除 demo.md，新增 new.md
          3) index_kb(rebuild=True)
        预期结果：
          - 第一次 docs 表仅包含 demo.md
          - 第二次 docs 表仅包含 new.md，且 deleted_docs==0（因重建无历史）
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            kb_dir = (kb_root / "kb").expanduser().resolve()

            (kb_dir / "notes").mkdir(parents=True, exist_ok=True)
            (kb_dir / "notes" / "demo.md").write_text("# D\n\nx\n", encoding="utf-8")
            (kb_dir / "notes" / "note.txt").write_text("no", encoding="utf-8")
            (kb_dir / "notes" / ".hidden.md").write_text("# H\n", encoding="utf-8")

            out1 = index_kb(kb_root, rebuild=True, embed_chunks=False)
            conn = open_db(Path(out1["db_path"]))
            try:
                rels = sorted([r["rel_path"] for r in conn.execute("SELECT rel_path FROM docs").fetchall()])
                self.assertEqual(rels, ["notes/demo.md"])
            finally:
                conn.close()

            (kb_dir / "notes" / "demo.md").unlink()
            (kb_dir / "notes" / "new.md").write_text("# N\n\ny\n", encoding="utf-8")

            out2 = index_kb(kb_root, rebuild=True, embed_chunks=False)
            self.assertEqual(out2["deleted_docs"], 0)
            conn = open_db(Path(out2["db_path"]))
            try:
                rels = sorted([r["rel_path"] for r in conn.execute("SELECT rel_path FROM docs").fetchall()])
                self.assertEqual(rels, ["notes/new.md"])
            finally:
                conn.close()


class TestIndexerEmbeddings(unittest.TestCase):
    def _write_openai_embed_config(self, kb_root: Path) -> None:
        cfg_path = kb_root.expanduser().resolve() / "kb_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.setdefault("openai_compat", {})
        cfg["openai_compat"].update(
            {
                "base_url": "http://example.local",
                "model_embed": "embed-model",
            }
        )
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def test_embed_chunks_writes_embeddings_when_configured(self):
        """
        描述：embed_chunks=True 且配置完整时，index_kb 应写入 embeddings 表并统计 embedded_chunks。
        前置条件：已 init_kb，并写入 openai_compat.base_url/model_embed。
        测试步骤：
          1) patch kb.indexer.embed 返回固定向量
          2) index_kb(embed_chunks=True)
          3) 查询 embeddings 表行数
        预期结果：
          - embedded_chunks >= 1
          - embeddings 表行数与 embedded_chunks 一致
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            self._write_openai_embed_config(kb_root)

            kb_dir = (kb_root / "kb").expanduser().resolve()
            (kb_dir / "notes").mkdir(parents=True, exist_ok=True)
            (kb_dir / "notes" / "demo.md").write_text("# H1\n\nhello\n", encoding="utf-8")

            def fake_embed(_cfg, *, texts):
                return [[1.0, 0.0, 0.0] for _ in texts]

            with patch("kb.indexer.embed", side_effect=fake_embed):
                out = index_kb(kb_root, rebuild=True, embed_chunks=True)
            self.assertGreaterEqual(out["embedded_chunks"], 1)

            db_path = Path(out["db_path"])
            conn = open_db(db_path)
            try:
                n = int(conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"])
                self.assertEqual(n, int(out["embedded_chunks"]))
            finally:
                conn.close()

    def test_embed_failure_is_soft_and_does_not_break_index(self):
        """
        描述：embedding 调用失败（OpenAICompatError）时，index_kb 应回滚向量写入并继续索引流程。
        前置条件：embed_chunks=True 且配置完整。
        测试步骤：
          1) patch kb.indexer.embed 抛 OpenAICompatError
          2) index_kb(embed_chunks=True)
        预期结果：
          - 不抛异常
          - embedded_chunks == 0（或不增加）
          - docs/chunks 仍被写入
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            self._write_openai_embed_config(kb_root)

            kb_dir = (kb_root / "kb").expanduser().resolve()
            (kb_dir / "notes").mkdir(parents=True, exist_ok=True)
            (kb_dir / "notes" / "demo.md").write_text("# H1\n\nhello\n", encoding="utf-8")

            with patch("kb.indexer.embed", side_effect=OpenAICompatError("boom")):
                out = index_kb(kb_root, rebuild=True, embed_chunks=True)

            self.assertEqual(int(out["embedded_chunks"]), 0)
            db_path = Path(out["db_path"])
            conn = open_db(db_path)
            try:
                self.assertGreaterEqual(int(conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]), 1)
                self.assertGreaterEqual(int(conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]), 1)
                self.assertEqual(int(conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]), 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
