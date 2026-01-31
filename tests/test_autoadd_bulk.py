import tempfile
import unittest
from pathlib import Path

from kb.autoadd_bulk import autoadd_inbox
from kb.bootstrap import init_kb


class TestAutoAddBulk(unittest.TestCase):
    def test_autoadd_moves_text_files_out_of_inbox_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            inbox_dir = kb_root / "_inbox"
            (inbox_dir / "a.md").write_text("# A\n\nhello\n", encoding="utf-8")
            (inbox_dir / "b.txt").write_text("plain text\n", encoding="utf-8")

            out = autoadd_inbox(kb_root)
            self.assertEqual(out["processed"], 2)
            self.assertEqual(len(out["errors"]), 0)
            self.assertEqual(len(out["skipped"]), 0)
            self.assertEqual(len(out["imported"]), 2)

            self.assertFalse((inbox_dir / "a.md").exists())
            self.assertFalse((inbox_dir / "b.txt").exists())

            for item in out["imported"]:
                imported = item["result"]["imported"][0]
                self.assertTrue(imported.startswith("inbox/"))
                self.assertTrue((kb_root / "kb" / imported).exists())

    def test_autoadd_skips_hidden_and_binary_files(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            inbox_dir = kb_root / "_inbox"
            (inbox_dir / ".hidden.md").write_text("# hidden\n", encoding="utf-8")
            (inbox_dir / "ok.md").write_text("# ok\n", encoding="utf-8")
            (inbox_dir / "bin.dat").write_bytes(b"\x00\x01\x02")

            out = autoadd_inbox(kb_root)
            self.assertEqual(out["processed"], 2)
            self.assertEqual(len(out["errors"]), 0)
            self.assertEqual(len(out["imported"]), 1)
            self.assertEqual(out["imported"][0]["src"], "ok.md")
            self.assertEqual(len(out["skipped"]), 1)
            self.assertEqual(out["skipped"][0]["src"], "bin.dat")
            self.assertEqual(out["skipped"][0]["reason"], "binary")


if __name__ == "__main__":
    unittest.main()
