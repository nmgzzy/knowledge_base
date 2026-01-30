import tempfile
import unittest
from pathlib import Path

from kb.bootstrap import init_kb
from kb.tree import tree_kb


class TestTree(unittest.TestCase):
    def test_tree_depth_filtering(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            kb_dir = kb_root / "kb"
            (kb_dir / "c.md").write_text("# C\n", encoding="utf-8")
            (kb_dir / "notes").mkdir(parents=True, exist_ok=True)
            (kb_dir / "notes" / "a.md").write_text("# A\n", encoding="utf-8")
            (kb_dir / "notes" / "sub").mkdir(parents=True, exist_ok=True)
            (kb_dir / "notes" / "sub" / "b.md").write_text("# B\n", encoding="utf-8")
            (kb_dir / "notes" / "sub" / "x.txt").write_text("x", encoding="utf-8")

            out0 = tree_kb(kb_root, depth=0)
            self.assertEqual(out0["docs"], ["c.md"])

            out1 = tree_kb(kb_root, depth=1)
            self.assertEqual(out1["docs"], ["c.md", "notes/a.md"])

            out2 = tree_kb(kb_root, depth=2)
            self.assertEqual(out2["docs"], ["c.md", "notes/a.md", "notes/sub/b.md"])

            out_all = tree_kb(kb_root, depth=None)
            self.assertEqual(out_all["docs"], ["c.md", "notes/a.md", "notes/sub/b.md"])
            self.assertIn("kb/", out_all["tree"])
            self.assertIn("notes/", out_all["tree"])
            self.assertIn("a.md", out_all["tree"])


if __name__ == "__main__":
    unittest.main()

