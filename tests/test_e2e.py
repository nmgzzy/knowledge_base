import tempfile
import unittest
from pathlib import Path

from kb.bootstrap import init_kb
from kb.indexer import index_kb
from kb.importer import add_to_kb
from kb.search import search_kb


class TestE2E(unittest.TestCase):
    def test_init_add_index_search_and_delete(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            src_dir = kb_root / "_src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src = src_dir / "demo.md"
            src.write_text(
                "# 离线优先知识库\n\n这是一个离线优先的本地知识库工具。\n\n## 检索\n\n支持关键词检索与引用定位。\n",
                encoding="utf-8",
            )

            add_out = add_to_kb(kb_root, src=src, dest_rel_dir="notes", auto=False, move=False)
            self.assertEqual(add_out["mode"], "manual")
            self.assertEqual(len(add_out["imported"]), 1)

            idx_out = index_kb(kb_root, rebuild=False, embed_chunks=False)
            self.assertGreaterEqual(idx_out["updated_docs"], 1)

            hits = search_kb(kb_root, query="离线优先", top_k=5, semantic=False, hybrid=False)
            self.assertGreaterEqual(len(hits), 1)
            self.assertTrue(hits[0].rel_path.startswith("notes/"))
            self.assertGreater(hits[0].start_line, 0)
            self.assertGreaterEqual(hits[0].end_line, hits[0].start_line)

            kb_file = kb_root / "kb" / hits[0].rel_path
            kb_file.unlink()

            idx2 = index_kb(kb_root, rebuild=False, embed_chunks=False)
            self.assertGreaterEqual(idx2["deleted_docs"], 1)

            hits2 = search_kb(kb_root, query="离线优先", top_k=5, semantic=False, hybrid=False)
            self.assertEqual(len(hits2), 0)


if __name__ == "__main__":
    unittest.main()

