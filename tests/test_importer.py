import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb.bootstrap import init_kb
from kb.markdown import parse_frontmatter
from kb.importer import add_to_kb
from kb.openai_compat import OpenAICompatError


class TestImporter(unittest.TestCase):
    def test_add_to_kb_raises_when_source_missing(self):
        """
        描述：src 不存在时 add_to_kb 应抛 FileNotFoundError。
        前置条件：临时 kb_root，src 指向不存在路径。
        测试步骤：
          1) 调用 add_to_kb
        预期结果：
          - 抛 FileNotFoundError
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            with self.assertRaises(FileNotFoundError):
                add_to_kb(kb_root, src=kb_root / "nope.md", dest_rel_dir=None, auto=False, move=False)

    def test_add_to_kb_manual_dest_dir_copies_file_and_meta(self):
        """
        描述：指定 dest_rel_dir 时应走 manual 模式，复制文件到目标目录并确保 meta.json 存在。
        前置条件：已 init_kb；存在源文件。
        测试步骤：
          1) add_to_kb(dest_rel_dir="notes", auto=False)
        预期结果：
          - mode == 'manual'
          - imported 列表包含 'notes/...' 相对路径
          - 目标目录 meta.json 存在
          - 目标文件存在
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            src_dir = kb_root / "_src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src = src_dir / "demo.md"
            src.write_text("# T\n\nBody\n", encoding="utf-8")

            out = add_to_kb(kb_root, src=src, dest_rel_dir="notes", auto=False, move=False)
            self.assertEqual(out["mode"], "manual")
            self.assertEqual(out["dest_rel_dir"], "notes")
            self.assertEqual(len(out["imported"]), 1)
            rel = out["imported"][0]
            self.assertTrue(rel.startswith("notes/"))

            meta = kb_root.expanduser().resolve() / "kb" / "notes" / "meta.json"
            self.assertTrue(meta.exists())
            dst = kb_root.expanduser().resolve() / "kb" / rel
            self.assertTrue(dst.exists())

    def test_add_to_kb_auto_uses_suggestion_when_available(self):
        """
        描述：auto=True 且 LLM 返回建议时，应走 auto 模式，并将文件写入建议目录/文件名。
        前置条件：patch suggest_destination_with_llm/apply_auto_suggestion 返回固定目标。
        测试步骤：
          1) add_to_kb(auto=True, dest_rel_dir=None)
        预期结果：
          - mode == 'auto'
          - 文件存在于 kb/<rel_dir>/<filename>
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            src_dir = kb_root / "_src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src = src_dir / "demo.md"
            src.write_text("# T\n\nBody\n", encoding="utf-8")

            suggestion = {"suggested_rel_dir": "notes", "suggested_filename": "x.md", "doc_title": "X", "dir_meta": {}}
            with patch("kb.importer.suggest_destination_with_llm", return_value=suggestion):
                with patch("kb.importer.apply_auto_suggestion", return_value=("notes", "x.md", {})):
                    out = add_to_kb(kb_root, src=src, dest_rel_dir=None, auto=True, move=False)

            self.assertEqual(out["mode"], "auto")
            self.assertEqual(out["dest_rel_dir"], "notes")
            self.assertEqual(out["imported"], ["notes/x.md"])
            dst = kb_root.expanduser().resolve() / "kb" / "notes" / "x.md"
            self.assertTrue(dst.exists())
            meta, _ = parse_frontmatter(dst.read_text(encoding="utf-8").splitlines())
            self.assertEqual(meta.get("title"), "X")

    def test_add_to_kb_auto_falls_back_to_inbox_on_llm_error(self):
        """
        描述：auto=True 但 LLM 调用抛 OpenAICompatError 时，应自动降级到 inbox 模式。
        前置条件：patch suggest_destination_with_llm 抛 OpenAICompatError；patch default_inbox_dir 固定值。
        测试步骤：
          1) add_to_kb(auto=True, dest_rel_dir=None)
        预期结果：
          - mode == 'inbox'
          - dest_rel_dir 为 inbox/<YYYY-MM>（此处为 stub 值）
          - 文件存在于该目录下
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            src_dir = kb_root / "_src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src = src_dir / "demo.md"
            src.write_text("# T\n\nBody\n", encoding="utf-8")

            with patch("kb.importer.suggest_destination_with_llm", side_effect=OpenAICompatError("boom")):
                with patch("kb.importer.default_inbox_dir", return_value="inbox/2000-01"):
                    out = add_to_kb(kb_root, src=src, dest_rel_dir=None, auto=True, move=False)

            self.assertEqual(out["mode"], "inbox")
            self.assertEqual(out["dest_rel_dir"], "inbox/2000-01")
            rel = out["imported"][0]
            self.assertTrue(rel.startswith("inbox/2000-01/"))
            dst = kb_root.expanduser().resolve() / "kb" / rel
            self.assertTrue(dst.exists())

    def test_add_to_kb_imports_directory_tree(self):
        """
        描述：src 为目录时应递归导入其中的 Markdown 文件，忽略隐藏文件与非 .md。
        前置条件：存在包含 .md/.txt/.hidden.md 的目录树。
        测试步骤：
          1) add_to_kb(src=<dir>, dest_rel_dir=None, auto=False)
        预期结果：
          - mode == 'dir'
          - imported 仅包含 Markdown 文件的相对路径
          - 目标文件存在于 kb/imports/<src_name>/...
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            src_root = kb_root / "_src_dir"
            (src_root / "sub").mkdir(parents=True, exist_ok=True)
            (src_root / "a.md").write_text("# A\n", encoding="utf-8")
            (src_root / "sub" / "b.md").write_text("# B\n", encoding="utf-8")
            (src_root / "sub" / "c.txt").write_text("no", encoding="utf-8")
            (src_root / ".hidden.md").write_text("# H\n", encoding="utf-8")

            out = add_to_kb(kb_root, src=src_root, dest_rel_dir=None, auto=False, move=False)
            self.assertEqual(out["mode"], "dir")
            self.assertTrue(out["dest_rel_dir"].startswith("imports/"))
            imported = sorted(out["imported"])
            self.assertEqual(imported, [f"{out['dest_rel_dir']}/a.md", f"{out['dest_rel_dir']}/sub/b.md"])

            for rel in imported:
                self.assertTrue((kb_root.expanduser().resolve() / "kb" / rel).exists())

    def test_add_to_kb_rejects_invalid_dest_rel_dir(self):
        """
        描述：dest_rel_dir 试图目录穿越时应抛 ValueError。
        前置条件：src 为存在的文件，dest_rel_dir 含 '..'。
        测试步骤：
          1) add_to_kb(dest_rel_dir='../x')
        预期结果：
          - 抛 ValueError
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            src_dir = kb_root / "_src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src = src_dir / "demo.md"
            src.write_text("# T\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                add_to_kb(kb_root, src=src, dest_rel_dir="../x", auto=False, move=False)


if __name__ == "__main__":
    unittest.main()
