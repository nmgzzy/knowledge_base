import json
import tempfile
import unittest
from pathlib import Path

from kb.bootstrap import init_kb


class TestBootstrap(unittest.TestCase):
    def test_init_kb_force_overwrites_config(self):
        """
        描述：init_kb(force=True) 应覆盖写入默认配置到 kb_config.json。
        前置条件：kb_root 下已存在 kb_config.json，且内容非默认。
        测试步骤：
          1) 写入自定义 kb_config.json（schema_version=999）
          2) 调用 init_kb(force=True)
          3) 读取 kb_config.json
        预期结果：
          - schema_version 恢复为默认值（1）
          - kb/kb_index/kb_vector 目录均存在
        """
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            kb_root.mkdir(parents=True, exist_ok=True)
            (kb_root / "kb_config.json").write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

            out = init_kb(kb_root, force=True)
            cfg = json.loads((kb_root / "kb_config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg.get("schema_version"), 1)

            self.assertTrue(Path(out["kb_dir"]).exists())
            self.assertTrue(Path(out["index_dir"]).exists())
            self.assertTrue(Path(out["vector_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
