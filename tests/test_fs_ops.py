import json
import tempfile
import unittest
from pathlib import Path

from kb.fs_ops import copy_or_move, ensure_dir_meta, merge_meta, read_dir_meta


class TestDirMeta(unittest.TestCase):
    def test_ensure_dir_meta_creates_file_once(self):
        """
        描述：ensure_dir_meta 应创建目录并写入默认 meta.json（若不存在）。
        前置条件：目标目录不存在。
        测试步骤：
          1) 调用 ensure_dir_meta(dir_path, meta_filename="meta.json")
          2) 再次调用 ensure_dir_meta（覆盖场景）
        预期结果：
          - meta.json 被创建
          - 第二次调用不会改变已存在文件路径
          - meta 内容包含 schema_version/title/tags/keywords/updated_at
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dp = root / "a" / "b"
            meta_path = ensure_dir_meta(dp, meta_filename="meta.json")
            self.assertTrue(meta_path.exists())
            self.assertEqual(meta_path.name, "meta.json")

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta.get("schema_version"), 1)
            self.assertEqual(meta.get("title"), dp.name)
            self.assertIsInstance(meta.get("tags"), list)
            self.assertIsInstance(meta.get("keywords"), list)
            self.assertTrue(str(meta.get("updated_at", "")).endswith("Z"))

            meta_path2 = ensure_dir_meta(dp, meta_filename="meta.json")
            self.assertEqual(meta_path2, meta_path)

    def test_read_dir_meta_returns_empty_dict_for_non_dict_json(self):
        """
        描述：read_dir_meta 读取到非 dict JSON 时应返回 {}。
        前置条件：meta.json 存在但内容为 JSON 数组。
        测试步骤：
          1) 写入 [] 到 meta.json
          2) 调用 read_dir_meta()
        预期结果：
          - 返回 {}
        """
        with tempfile.TemporaryDirectory() as td:
            dp = Path(td) / "x"
            dp.mkdir(parents=True, exist_ok=True)
            (dp / "meta.json").write_text("[]", encoding="utf-8")
            meta = read_dir_meta(dp, meta_filename="meta.json")
            self.assertEqual(meta, {})

    def test_merge_meta_merges_lists_dicts_and_fills_only_empty_fields(self):
        """
        描述：merge_meta 应合并 list/dict，且只在 existing 为空值时覆盖标量字段。
        前置条件：existing/patc h 均为 dict。
        测试步骤：
          1) 对 tags/rules/summary/title 等字段合并
        预期结果：
          - tags 去重合并
          - rules 合并更新
          - summary/title 非空不被覆盖
          - updated_at 被刷新
        """
        existing = {"title": "T", "summary": "", "tags": ["a"], "keywords": [], "rules": {"x": 1}, "updated_at": "old"}
        patch = {"title": "T2", "summary": "S", "tags": ["a", "b"], "keywords": ["k"], "rules": {"y": 2}, "ignored": None}
        merged = merge_meta(existing, patch)
        self.assertEqual(merged["title"], "T")
        self.assertEqual(merged["summary"], "S")
        self.assertEqual(merged["tags"], ["a", "b"])
        self.assertEqual(merged["keywords"], ["k"])
        self.assertEqual(merged["rules"], {"x": 1, "y": 2})
        self.assertNotEqual(merged["updated_at"], "old")


class TestCopyOrMove(unittest.TestCase):
    def test_copy_or_move_copy(self):
        """
        描述：copy_or_move(move=False) 应复制文件并保留源文件。
        前置条件：存在源文件。
        测试步骤：
          1) copy_or_move(src, dst, move=False)
        预期结果：
          - dst 存在且内容相同
          - src 仍存在
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src.md"
            dst = root / "dst" / "copied.md"
            src.write_text("hello", encoding="utf-8")
            copy_or_move(src, dst, move=False)
            self.assertTrue(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), "hello")

    def test_copy_or_move_move(self):
        """
        描述：copy_or_move(move=True) 应移动文件（源文件消失）。
        前置条件：存在源文件。
        测试步骤：
          1) copy_or_move(src, dst, move=True)
        预期结果：
          - dst 存在且内容相同
          - src 不存在
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src.md"
            dst = root / "dst" / "moved.md"
            src.write_text("hello", encoding="utf-8")
            copy_or_move(src, dst, move=True)
            self.assertFalse(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_text(encoding="utf-8"), "hello")


if __name__ == "__main__":
    unittest.main()
