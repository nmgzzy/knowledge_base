import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb.auto_add import _extract_json_object, apply_auto_suggestion, default_filename, suggest_destination_with_llm
from kb.bootstrap import init_kb
from kb.openai_compat import OpenAICompatError


class TestAutoAddHelpers(unittest.TestCase):
    def test_default_filename_keeps_md_and_sanitizes_other_suffix(self):
        """
        描述：default_filename 对 .md 文件应保持原名；对非 .md 文件应基于 title/stem 生成安全文件名。
        前置条件：构造不同后缀的 Path。
        测试步骤：
          1) default_filename("x.md")
          2) default_filename("x.txt", title="含 空格/特殊*字符")
        预期结果：
          - .md 返回原文件名
          - .txt 生成以 .md 结尾、且不包含空格/非法符号的文件名
        """
        self.assertEqual(default_filename(Path("x.md"), title="t"), "x.md")
        name = default_filename(Path("x.txt"), title="含 空格/特殊*字符")
        self.assertTrue(name.endswith(".md"))
        self.assertNotIn(" ", name)
        self.assertNotIn("*", name)

    def test_extract_json_object_accepts_wrapped_json(self):
        """
        描述：_extract_json_object 应从纯 JSON 或包裹文本中提取 JSON 对象。
        前置条件：raw 包含 JSON 对象。
        测试步骤：
          1) 传入纯 JSON
          2) 传入包含前后缀文字的 JSON
        预期结果：
          - 返回 dict
        """
        self.assertEqual(_extract_json_object('{"a":1}'), {"a": 1})
        self.assertEqual(_extract_json_object("xxx\n{\"a\":1}\nyyy"), {"a": 1})
        self.assertIsNone(_extract_json_object("no json here"))


class TestApplyAutoSuggestion(unittest.TestCase):
    def test_apply_auto_suggestion_merges_meta_and_writes_file(self):
        """
        描述：apply_auto_suggestion 应确保目录存在、读取现有 meta.json、合并 patch 并写回。
        前置条件：已 init_kb；目标目录存在默认 meta.json。
        测试步骤：
          1) 调用 apply_auto_suggestion 写入 dir_meta patch
        预期结果：
          - 返回 rel_dir/filename/merged_meta
          - 目标目录 meta.json 被更新（包含 patch 字段）
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)

            suggestion = {
                "suggested_rel_dir": "notes",
                "suggested_filename": "demo.md",
                "dir_meta": {"summary": "S", "tags": ["t1"]},
            }
            rel_dir, filename, merged = apply_auto_suggestion(kb_root, suggestion=suggestion, meta_filename="meta.json")
            self.assertEqual(rel_dir, "notes")
            self.assertEqual(filename, "demo.md")
            self.assertEqual(merged.get("summary"), "S")
            self.assertIn("t1", merged.get("tags", []))

            meta_path = kb_root.expanduser().resolve() / "kb" / rel_dir / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta.get("summary"), "S")
            self.assertIn("t1", meta.get("tags", []))


class TestSuggestDestinationWithLLM(unittest.TestCase):
    def test_suggest_destination_with_llm_raises_on_invalid_json(self):
        """
        描述：模型返回无法解析为 JSON 对象时应抛 OpenAICompatError。
        前置条件：patch chat_completion 返回非 JSON 文本。
        测试步骤：
          1) 调用 suggest_destination_with_llm
        预期结果：
          - 抛 OpenAICompatError
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            with patch("kb.auto_add.chat_completion", return_value="not json"):
                with self.assertRaises(OpenAICompatError):
                    suggest_destination_with_llm(kb_root, src_text="x", src_name="x.md")

    def test_suggest_destination_with_llm_parses_valid_json(self):
        """
        描述：模型返回可解析 JSON 对象时，suggest_destination_with_llm 应直接返回该对象。
        前置条件：patch chat_completion 返回 JSON 字符串。
        测试步骤：
          1) 调用 suggest_destination_with_llm
        预期结果：
          - 返回 dict，包含 suggested_rel_dir 等字段
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            init_kb(kb_root, force=False)
            payload = {
                "doc_title": "T",
                "doc_summary": "S",
                "tags": ["t"],
                "keywords": ["k"],
                "suggested_rel_dir": "notes",
                "suggested_filename": "x.md",
                "dir_meta": {"summary": "D"},
            }
            with patch("kb.auto_add.chat_completion", return_value=json.dumps(payload, ensure_ascii=False)):
                out = suggest_destination_with_llm(kb_root, src_text="x", src_name="x.md")
            self.assertEqual(out["suggested_rel_dir"], "notes")
            self.assertEqual(out["suggested_filename"], "x.md")


if __name__ == "__main__":
    unittest.main()
