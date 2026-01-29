import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from kb.openai_compat import OpenAICompatError, chat_completion, embed, from_config_dict


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestOpenAICompatConfig(unittest.TestCase):
    def test_from_config_dict_normalizes_base_url_and_headers(self):
        """
        描述：from_config_dict 应规范化 base_url，并过滤/字符串化 extra_headers。
        前置条件：输入 dict 包含 base_url 末尾 '/' 与混合类型 headers。
        测试步骤：
          1) 调用 from_config_dict
        预期结果：
          - base_url 末尾 '/' 被去除
          - extra_headers 仅保留 key 非空且 value 非 None
        """
        cfg = from_config_dict(
            {
                "base_url": "http://x/y/",
                "api_key_env": "K",
                "model_chat": "c",
                "model_embed": "e",
                "timeout_s": 1,
                "max_retries": 0,
                "extra_headers": {"X-A": 1, "": "bad", "X-None": None},
            }
        )
        self.assertEqual(cfg.base_url, "http://x/y")
        self.assertEqual(cfg.extra_headers.get("X-A"), "1")
        self.assertNotIn("", cfg.extra_headers)
        self.assertNotIn("X-None", cfg.extra_headers)


class TestOpenAICompatAPI(unittest.TestCase):
    def test_chat_completion_requires_configuration(self):
        """
        描述：chat_completion 未配置 base_url/model_chat 时应抛 OpenAICompatError。
        前置条件：cfg.base_url 或 cfg.model_chat 为空。
        测试步骤：
          1) 调用 chat_completion
        预期结果：
          - 抛 OpenAICompatError
        """
        cfg = from_config_dict({"base_url": "", "model_chat": ""})
        with self.assertRaises(OpenAICompatError):
            chat_completion(cfg, messages=[])

    def test_embed_requires_configuration(self):
        """
        描述：embed 未配置 base_url/model_embed 时应抛 OpenAICompatError。
        前置条件：cfg.base_url 或 cfg.model_embed 为空。
        测试步骤：
          1) 调用 embed
        预期结果：
          - 抛 OpenAICompatError
        """
        cfg = from_config_dict({"base_url": "", "model_embed": ""})
        with self.assertRaises(OpenAICompatError):
            embed(cfg, texts=["q"])

    def test_chat_completion_parses_expected_response(self):
        """
        描述：chat_completion 应从 choices[0].message.content 提取文本。
        前置条件：_post_json 返回符合 schema 的对象。
        测试步骤：
          1) patch kb.openai_compat._post_json
          2) 调用 chat_completion
        预期结果：
          - 返回 content 字符串
        """
        cfg = from_config_dict({"base_url": "http://x", "model_chat": "m"})
        with patch("kb.openai_compat._post_json", return_value={"choices": [{"message": {"content": "hi"}}]}):
            out = chat_completion(cfg, messages=[{"role": "user", "content": "x"}])
        self.assertEqual(out, "hi")

    def test_embed_sorts_by_index(self):
        """
        描述：embed 应按 index 对返回 data 排序，并输出 embedding 列表。
        前置条件：_post_json 返回 data 列表乱序。
        测试步骤：
          1) patch kb.openai_compat._post_json 返回乱序 data
          2) 调用 embed
        预期结果：
          - embeddings 输出顺序与 index 升序一致
        """
        cfg = from_config_dict({"base_url": "http://x", "model_embed": "m"})
        payload = {"data": [{"index": 1, "embedding": [2]}, {"index": 0, "embedding": [1]}]}
        with patch("kb.openai_compat._post_json", return_value=payload):
            out = embed(cfg, texts=["a", "b"])
        self.assertEqual(out, [[1], [2]])

    def test_post_json_adds_auth_and_extra_headers(self):
        """
        描述：_post_json 应添加 Authorization（当 env 存在）与 extra_headers。
        前置条件：设置环境变量；urlopen 返回有效 JSON。
        测试步骤：
          1) patch urllib.request.urlopen 检查 Request headers
          2) 调用 chat_completion（触发 _post_json）
        预期结果：
          - Authorization: Bearer <key> 存在
          - extra_headers 被透传
        """
        cfg = from_config_dict(
            {"base_url": "http://x", "model_chat": "m", "api_key_env": "KB_TEST_KEY", "max_retries": 0, "extra_headers": {"X-Test": "1"}}
        )

        def fake_urlopen(req, timeout):
            self.assertEqual(req.get_method(), "POST")
            hdrs = {str(k).lower(): str(v) for k, v in getattr(req, "headers", {}).items()}
            self.assertEqual(hdrs.get("x-test"), "1")
            self.assertEqual(hdrs.get("authorization"), "Bearer secret")
            return _FakeHTTPResponse({"choices": [{"message": {"content": "ok"}}]})

        with patch.dict(os.environ, {"KB_TEST_KEY": "secret"}):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                out = chat_completion(cfg, messages=[{"role": "user", "content": "x"}])
        self.assertEqual(out, "ok")

    def test_post_json_retries_then_succeeds(self):
        """
        描述：_post_json 遇到网络错误时应按 max_retries 重试，最终成功返回 JSON。
        前置条件：第一次 urlopen 抛 URLError，第二次返回有效响应；sleep 被 patch 以免延迟。
        测试步骤：
          1) patch urllib.request.urlopen: raise -> success
          2) patch time.sleep
          3) 调用 embed（触发 _post_json）
        预期结果：
          - 成功返回 embedding 列表
          - urlopen 被调用至少 2 次
        """
        cfg = from_config_dict({"base_url": "http://x", "model_embed": "m", "max_retries": 1, "timeout_s": 1})
        calls = {"n": 0}

        def fake_urlopen(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("boom")
            return _FakeHTTPResponse({"data": [{"index": 0, "embedding": [1.0]}]})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("time.sleep", return_value=None):
                out = embed(cfg, texts=["q"])
        self.assertEqual(out, [[1.0]])
        self.assertGreaterEqual(calls["n"], 2)

    def test_chat_completion_raises_on_unexpected_response_shape(self):
        """
        描述：chat_completion 遇到非预期响应结构时应抛 OpenAICompatError（封装解析异常）。
        前置条件：_post_json 返回缺失 choices/message/content 的对象。
        测试步骤：
          1) patch kb.openai_compat._post_json 返回不完整结构
          2) 调用 chat_completion
        预期结果：
          - 抛 OpenAICompatError
        """
        cfg = from_config_dict({"base_url": "http://x", "model_chat": "m"})
        with patch("kb.openai_compat._post_json", return_value={"choices": []}):
            with self.assertRaises(OpenAICompatError):
                chat_completion(cfg, messages=[{"role": "user", "content": "x"}])

    def test_embed_raises_on_unexpected_response_shape(self):
        """
        描述：embed 遇到非预期响应结构时应抛 OpenAICompatError。
        前置条件：_post_json 返回缺失 embedding 的 data 项。
        测试步骤：
          1) patch kb.openai_compat._post_json
          2) 调用 embed
        预期结果：
          - 抛 OpenAICompatError
        """
        cfg = from_config_dict({"base_url": "http://x", "model_embed": "m"})
        with patch("kb.openai_compat._post_json", return_value={"data": [{"index": 0}]}):
            with self.assertRaises(OpenAICompatError):
                embed(cfg, texts=["q"])

    def test_post_json_raises_when_response_is_not_object(self):
        """
        描述：_post_json 解析到 JSON 但根对象不是 dict 时应抛 OpenAICompatError。
        前置条件：urlopen 返回 JSON 数组。
        测试步骤：
          1) patch urllib.request.urlopen 返回 \"[]\"
          2) 调用 chat_completion（触发 _post_json）
        预期结果：
          - 抛 OpenAICompatError
        """
        cfg = from_config_dict({"base_url": "http://x", "model_chat": "m", "max_retries": 0})

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"[]"

        with patch("urllib.request.urlopen", return_value=_Resp()):
            with self.assertRaises(OpenAICompatError):
                chat_completion(cfg, messages=[{"role": "user", "content": "x"}])

    def test_post_json_raises_on_invalid_json(self):
        """
        描述：_post_json 返回无法解析的 JSON 时，应在重试耗尽后抛 OpenAICompatError。
        前置条件：urlopen 返回非法 JSON；max_retries=0。
        测试步骤：
          1) patch urllib.request.urlopen 返回 'not json'
          2) 调用 embed
        预期结果：
          - 抛 OpenAICompatError
        """
        cfg = from_config_dict({"base_url": "http://x", "model_embed": "m", "max_retries": 0})

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"not json"

        with patch("urllib.request.urlopen", return_value=_Resp()):
            with self.assertRaises(OpenAICompatError):
                embed(cfg, texts=["q"])


if __name__ == "__main__":
    unittest.main()
