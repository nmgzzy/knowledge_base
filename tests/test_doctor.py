import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb.doctor import doctor_kb
from kb.util import write_json_atomic


class TestDoctor(unittest.TestCase):
    def test_doctor_runs_chat_and_embed(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            write_json_atomic(
                kb_root / "kb_config.json",
                {
                    "openai_compat": {
                        "base_url": "http://x",
                        "api_key_env": "KB_TEST_KEY",
                        "model_chat": "c",
                        "model_embed": "e",
                        "max_retries": 0,
                    }
                },
            )

            def fake_post_json(cfg, url, payload):
                if url.endswith("/v1/embeddings"):
                    return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
                if url.endswith("/v1/chat/completions"):
                    return {"choices": [{"message": {"content": "ok"}}]}
                raise AssertionError(url)

            with patch.dict(os.environ, {"KB_TEST_KEY": "secret"}):
                with patch("kb.openai_compat._post_json", side_effect=fake_post_json):
                    out = doctor_kb(kb_root, check_chat=False, check_embed=False, text="ping")

            self.assertTrue(out["ok"])
            self.assertTrue(out["openai_compat"]["api_key_present"])
            self.assertIn("embed", out["checks"])
            self.assertIn("chat", out["checks"])
            self.assertEqual(out["checks"]["embed"]["result"]["dim"], 2)
            self.assertEqual(out["checks"]["chat"]["result"]["length"], 2)

    def test_doctor_reports_not_configured(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            out = doctor_kb(kb_root, check_chat=False, check_embed=False, text="ping")
            self.assertFalse(out["ok"])
            self.assertFalse(out["checks"]["embed"]["ok"])
            self.assertFalse(out["checks"]["chat"]["ok"])

    def test_doctor_supports_single_check(self):
        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            write_json_atomic(
                kb_root / "kb_config.json",
                {
                    "openai_compat": {
                        "base_url": "http://x",
                        "model_chat": "c",
                        "model_embed": "e",
                        "max_retries": 0,
                    }
                },
            )

            with patch("kb.openai_compat._post_json", return_value={"choices": [{"message": {"content": "ok"}}]}):
                out = doctor_kb(kb_root, check_chat=True, check_embed=False, text="ping")
            self.assertIn("chat", out["checks"])
            self.assertNotIn("embed", out["checks"])


if __name__ == "__main__":
    unittest.main()
