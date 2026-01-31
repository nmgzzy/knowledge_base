import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kb.bootstrap import init_kb
from kb.cli import main
from kb.store_sqlite import init_schema, open_db, upsert_doc_and_chunks
from kb.util import sha256_text


class TestCliSearch(unittest.TestCase):
    def _make_min_index(self, kb_root: Path) -> None:
        db_path = (kb_root / "kb_index" / "index.sqlite").expanduser().resolve()
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

    def test_cli_search_text_output(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            self._make_min_index(kb_root)

            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["search", "离线优先", "--kb-root", str(kb_root), "--top", "3"])
            out = buf.getvalue()
            self.assertIn("Query: 离线优先", out)
            self.assertIn("Mode: fts", out)
            self.assertIn("Hits: 1", out)
            self.assertIn("[1] notes/a.md:L10-L12", out)
            self.assertIn("heading: H1", out)
            self.assertIn("source: fts", out)
            self.assertIn("离线优先 工具", out)

    def test_cli_search_json_output_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            self._make_min_index(kb_root)

            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["search", "离线优先", "--kb-root", str(kb_root), "--top", "3", "--json"])
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["query"], "离线优先")
            self.assertEqual(len(payload["results"]), 1)
            self.assertEqual(payload["results"][0]["path"], "notes/a.md")
            self.assertEqual(payload["results"][0]["line_range"], [10, 12])


if __name__ == "__main__":
    unittest.main()

