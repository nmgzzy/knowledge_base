import json
import tempfile
import unittest
from pathlib import Path

from kb.config import default_config, load_config, resolve_paths, save_config


class TestConfig(unittest.TestCase):
    def test_default_config_shape(self):
        """
        描述：验证默认配置的结构与关键字段。
        前置条件：无。
        测试步骤：
          1) 调用 default_config()
        预期结果：
          - 返回 dict
          - 包含 schema_version/paths/meta_filename/chunking/openai_compat 等关键字段
          - paths 含 kb/index/vector 三个子路径键
        """
        cfg = default_config()
        self.assertIsInstance(cfg, dict)
        self.assertIn("schema_version", cfg)
        self.assertIn("paths", cfg)
        self.assertIn("meta_filename", cfg)
        self.assertIn("chunking", cfg)
        self.assertIn("openai_compat", cfg)

        self.assertIsInstance(cfg["paths"], dict)
        self.assertIn("kb", cfg["paths"])
        self.assertIn("index", cfg["paths"])
        self.assertIn("vector", cfg["paths"])

    def test_resolve_paths_uses_default_when_config_missing(self):
        """
        描述：未创建 kb_config.json 时，resolve_paths 应使用默认路径配置。
        前置条件：临时目录内不存在 kb_config.json。
        测试步骤：
          1) 在临时目录作为 kb_root 调用 resolve_paths()
        预期结果：
          - kb_dir/index_dir/vector_dir/config_path 均落在 kb_root 下
          - 子目录名为默认值 kb/kb_index/kb_vector
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            root = kb_root.expanduser().resolve()
            paths = resolve_paths(kb_root)
            self.assertEqual(paths.config_path, root / "kb_config.json")
            self.assertEqual(paths.kb_dir, root / "kb")
            self.assertEqual(paths.index_dir, root / "kb_index")
            self.assertEqual(paths.vector_dir, root / "kb_vector")

    def test_resolve_paths_applies_paths_override(self):
        """
        描述：resolve_paths 应读取 kb_config.json 中的 paths 覆盖项。
        前置条件：kb_root 下存在合法的 kb_config.json。
        测试步骤：
          1) 写入包含自定义 paths 的配置文件
          2) 调用 resolve_paths()
        预期结果：
          - kb_dir/index_dir/vector_dir 使用自定义值
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            root = kb_root.expanduser().resolve()
            cfg = default_config()
            cfg["paths"] = {"kb": "data", "index": "idx", "vector": "vec"}
            (kb_root / "kb_config.json").write_text(json.dumps(cfg), encoding="utf-8")

            paths = resolve_paths(kb_root)
            self.assertEqual(paths.kb_dir, root / "data")
            self.assertEqual(paths.index_dir, root / "idx")
            self.assertEqual(paths.vector_dir, root / "vec")

    def test_resolve_paths_falls_back_on_invalid_config_json(self):
        """
        描述：kb_config.json 非法 JSON 时，resolve_paths 应回退到默认配置而不抛异常。
        前置条件：kb_root 下存在格式损坏的 kb_config.json。
        测试步骤：
          1) 写入非法 JSON 到 kb_config.json
          2) 调用 resolve_paths()
        预期结果：
          - 不抛异常
          - 使用默认的 kb/kb_index/kb_vector
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            root = kb_root.expanduser().resolve()
            (kb_root / "kb_config.json").write_text("{not valid json", encoding="utf-8")
            paths = resolve_paths(kb_root)
            self.assertEqual(paths.kb_dir, root / "kb")
            self.assertEqual(paths.index_dir, root / "kb_index")
            self.assertEqual(paths.vector_dir, root / "kb_vector")

    def test_resolve_paths_falls_back_when_paths_is_not_dict(self):
        """
        描述：配置存在但 paths 字段非 dict 时，resolve_paths 应回退到默认 paths。
        前置条件：kb_config.json 合法 JSON，但 paths=[]。
        测试步骤：
          1) 写入 paths 非 dict 的配置
          2) 调用 resolve_paths
        预期结果：
          - 使用默认 kb/kb_index/kb_vector
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            root = kb_root.expanduser().resolve()
            (kb_root / "kb_config.json").write_text(json.dumps({"paths": []}), encoding="utf-8")
            paths = resolve_paths(kb_root)
            self.assertEqual(paths.kb_dir, root / "kb")
            self.assertEqual(paths.index_dir, root / "kb_index")
            self.assertEqual(paths.vector_dir, root / "kb_vector")

    def test_load_config_deep_merge_for_nested_dicts(self):
        """
        描述：load_config 应对 paths/chunking/openai_compat 做浅层 dict 合并（保留默认键）。
        前置条件：kb_root 下存在合法 kb_config.json，且仅覆写部分嵌套字段。
        测试步骤：
          1) 写入仅包含 chunking.max_chars 的配置
          2) 调用 load_config()
        预期结果：
          - chunking.max_chars 为覆盖值
          - chunking.overlap_chars/min_chars 保留默认值
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            partial = {"chunking": {"max_chars": 42}}
            (kb_root / "kb_config.json").write_text(json.dumps(partial), encoding="utf-8")
            cfg = load_config(kb_root)
            self.assertEqual(cfg["chunking"]["max_chars"], 42)
            self.assertEqual(cfg["chunking"]["overlap_chars"], default_config()["chunking"]["overlap_chars"])
            self.assertEqual(cfg["chunking"]["min_chars"], default_config()["chunking"]["min_chars"])

    def test_load_config_returns_default_when_root_has_non_dict_json(self):
        """
        描述：kb_config.json 的根对象不是 dict 时，load_config 应返回 default_config()。
        前置条件：kb_root 下存在 JSON 数组类型的 kb_config.json。
        测试步骤：
          1) 写入 [] 到 kb_config.json
          2) 调用 load_config()
        预期结果：
          - 返回值与 default_config() 的关键字段一致
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            (kb_root / "kb_config.json").write_text("[]", encoding="utf-8")
            cfg = load_config(kb_root)
            self.assertEqual(cfg["schema_version"], default_config()["schema_version"])
            self.assertEqual(cfg["paths"], default_config()["paths"])

    def test_load_config_raises_on_invalid_json(self):
        """
        描述：kb_config.json 语法损坏时，load_config 目前会抛出 JSONDecodeError（按现实现行为断言）。
        前置条件：kb_root 下存在非法 JSON 的 kb_config.json。
        测试步骤：
          1) 写入非法 JSON
          2) 调用 load_config()
        预期结果：
          - 抛出异常（json.JSONDecodeError）
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            (kb_root / "kb_config.json").write_text("{oops", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_config(kb_root)

    def test_save_config_round_trip(self):
        """
        描述：save_config 应将配置写入 kb_config.json，且可被 load_config 再读出。
        前置条件：临时目录作为 kb_root。
        测试步骤：
          1) 调用 save_config 写入自定义配置
          2) 调用 load_config 读取
        预期结果：
          - 读取结果包含写入的字段（并与默认配置合并）
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            cfg = default_config()
            cfg["meta_filename"] = "META.json"
            save_config(kb_root, cfg)
            loaded = load_config(kb_root)
            self.assertEqual(loaded["meta_filename"], "META.json")


if __name__ == "__main__":
    unittest.main()
