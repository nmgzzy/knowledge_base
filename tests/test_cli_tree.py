import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kb.bootstrap import init_kb
from kb.cli import main


class TestCliTree(unittest.TestCase):
    def test_cli_tree_text_and_json(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            kb_dir = kb_root / "kb"
            (kb_dir / "root.md").write_text("# Root\n", encoding="utf-8")
            (kb_dir / "notes").mkdir(parents=True, exist_ok=True)
            (kb_dir / "notes" / "a.md").write_text("# A\n", encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["tree", "--kb-root", str(kb_root), "--depth", "0"])
            text_out = buf.getvalue()
            self.assertIn("kb/", text_out)
            self.assertIn("root.md", text_out)
            self.assertNotIn("notes/a.md", text_out)

            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["tree", "--kb-root", str(kb_root), "--depth", "1", "--json"])
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["depth"], 1)
            self.assertEqual(payload["docs"], ["notes/a.md", "root.md"])


if __name__ == "__main__":
    unittest.main()

