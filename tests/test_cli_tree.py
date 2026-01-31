import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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

    def test_cli_tree_auto_kb_root_and_error_json(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            kb_dir = kb_root / "kb"
            (kb_dir / "root.md").write_text("# Root\n", encoding="utf-8")

            buf = io.StringIO()
            with patch("pathlib.Path.cwd", return_value=(kb_root / "kb")), redirect_stdout(buf):
                main(["tree", "--depth", "0"])
            self.assertIn("root.md", buf.getvalue())

        with tempfile.TemporaryDirectory() as td:
            not_a_repo = Path(td)
            buf = io.StringIO()
            with patch("pathlib.Path.cwd", return_value=not_a_repo), redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main(["tree", "--depth", "0", "--json"])
            self.assertEqual(cm.exception.code, 1)
            payload = json.loads(buf.getvalue())
            self.assertIn("未指定 --kb-root", payload["error"])


if __name__ == "__main__":
    unittest.main()
