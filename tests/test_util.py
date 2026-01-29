import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from kb.util import (
    ensure_rel_under_base,
    getenv_trim,
    json_dumps_compact,
    now_iso,
    read_json,
    safe_relpath,
    sha256_bytes,
    sha256_text,
    write_json_atomic,
    write_text_atomic,
)


class TestEnsureRelUnderBase(unittest.TestCase):
    def test_empty_and_dot_become_empty(self):
        """
        描述：空串与 '.' 应被规范化为 ''。
        前置条件：无。
        测试步骤：
          1) ensure_rel_under_base("")
          2) ensure_rel_under_base(".")
        预期结果：
          - 均返回 ""
        """
        self.assertEqual(ensure_rel_under_base(""), "")
        self.assertEqual(ensure_rel_under_base("."), "")

    def test_normalizes_slashes_and_strips_leading(self):
        """
        描述：应移除前导 '/'，并将 '\\\\' 归一为 '/'。
        前置条件：无。
        测试步骤：
          1) 传入包含前导 '/' 与 '\\\\' 的路径
        预期结果：
          - 返回无前导 '/' 且分隔符为 '/'
        """
        self.assertEqual(ensure_rel_under_base("/a/b"), "a/b")
        self.assertEqual(ensure_rel_under_base("\\a\\b\\c"), "a/b/c")

    def test_rejects_parent_directory(self):
        """
        描述：包含 '..' 的相对路径应抛 ValueError，防止目录穿越。
        前置条件：无。
        测试步骤：
          1) 传入 '../x'、'a/../b'
        预期结果：
          - 抛 ValueError
        """
        with self.assertRaises(ValueError):
            ensure_rel_under_base("../x")
        with self.assertRaises(ValueError):
            ensure_rel_under_base("a/../b")


class TestWriteTextAtomic(unittest.TestCase):
    def test_write_text_atomic_creates_parent_and_replaces(self):
        """
        描述：write_text_atomic 应创建父目录并通过临时文件原子替换写入。
        前置条件：目标文件不存在，父目录不存在。
        测试步骤：
          1) write_text_atomic(path, "v1")
          2) write_text_atomic(path, "v2")
        预期结果：
          - 文件内容最终为 v2
          - 不残留 .tmp 文件
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "a" / "b" / "c.txt"
            write_text_atomic(path, "v1")
            self.assertEqual(path.read_text(encoding="utf-8"), "v1")
            write_text_atomic(path, "v2")
            self.assertEqual(path.read_text(encoding="utf-8"), "v2")
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())


class TestJsonDumpsCompact(unittest.TestCase):
    def test_json_dumps_compact_is_valid_json_and_compact(self):
        """
        描述：json_dumps_compact 应生成可反序列化的紧凑 JSON。
        前置条件：无。
        测试步骤：
          1) 调用 json_dumps_compact
          2) json.loads 解析
        预期结果：
          - 解析回原对象
          - 分隔符为紧凑格式（包含 ':', ','，不强制包含空格）
        """
        obj = {"a": 1, "b": [1, 2], "c": {"x": "y"}}
        s = json_dumps_compact(obj)
        self.assertEqual(json.loads(s), obj)
        self.assertIn(":", s)
        self.assertIn(",", s)
        self.assertNotIn(": ", s)


class TestOtherUtils(unittest.TestCase):
    def test_now_iso_format(self):
        """
        描述：now_iso 应输出 UTC ISO8601 字符串并以 'Z' 结尾。
        前置条件：无。
        测试步骤：
          1) 调用 now_iso
        预期结果：
          - 结果为 str
          - 以 'Z' 结尾
        """
        s = now_iso()
        self.assertIsInstance(s, str)
        self.assertTrue(s.endswith("Z"))

    def test_sha256_text_and_bytes_consistency(self):
        """
        描述：sha256_text 应等价于对 UTF-8 bytes 做 sha256_bytes。
        前置条件：无。
        测试步骤：
          1) 分别调用 sha256_text/sha256_bytes
        预期结果：
          - 两者输出相同的 64 位 hex
        """
        t = "hello"
        self.assertEqual(sha256_text(t), sha256_bytes(t.encode("utf-8")))
        self.assertEqual(len(sha256_text(t)), 64)

    def test_write_json_atomic_and_read_json_round_trip(self):
        """
        描述：write_json_atomic 应原子写入 JSON，且可被 read_json 读取。
        前置条件：临时目录。
        测试步骤：
          1) write_json_atomic 写入对象
          2) read_json 读取
        预期结果：
          - 读取对象与写入一致
        """
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a" / "b.json"
            obj = {"x": 1, "y": ["a", "b"]}
            write_json_atomic(p, obj)
            self.assertEqual(read_json(p), obj)
            self.assertFalse(p.with_suffix(p.suffix + ".tmp").exists())

    def test_safe_relpath_strips_leading_slash(self):
        """
        描述：safe_relpath 应剥离前导 '/'，用于路径展示/存储。
        前置条件：无。
        测试步骤：
          1) 调用 safe_relpath
        预期结果：
          - 返回不以 '/' 开头的字符串
        """
        self.assertEqual(safe_relpath(Path("/a/b")), "a/b")

    def test_getenv_trim(self):
        """
        描述：getenv_trim 应对环境变量做 strip，并将空串视为 None。
        前置条件：设置临时环境变量。
        测试步骤：
          1) 设置 '  v  ' 与 '   '
          2) 调用 getenv_trim
        预期结果：
          - '  v  ' -> 'v'
          - '   ' -> None
        """
        with patch_env({"KB_T": "  v  ", "KB_EMPTY": "   "}):
            self.assertEqual(getenv_trim("KB_T"), "v")
            self.assertIsNone(getenv_trim("KB_EMPTY"))
            self.assertIsNone(getenv_trim("KB_MISSING"))


class patch_env:
    def __init__(self, values: dict[str, str]):
        self._values = values
        self._old: dict[str, Optional[str]] = {}

    def __enter__(self):
        for k, v in self._values.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, exc_type, exc, tb):
        for k, old in self._old.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        return False


if __name__ == "__main__":
    unittest.main()
