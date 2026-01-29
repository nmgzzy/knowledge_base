import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb.ask import _format_sources, ask_kb
from kb.search import RetrievedChunk


class TestAskFormatting(unittest.TestCase):
    def test_format_sources_includes_heading_and_line_range(self):
        """
        描述：_format_sources 应输出 [n] 标号、文件定位与 heading_path（若存在）。
        前置条件：提供包含 heading_path 与行号范围的 RetrievedChunk。
        测试步骤：
          1) 调用 _format_sources
        预期结果：
          - 输出包含 [1]、rel_path#start-end
          - 输出包含 heading_path
          - 输出包含 chunk 文本
        """
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                rel_path="a.md",
                title="A",
                heading_path="H1 > H2",
                start_line=3,
                end_line=9,
                text="hello",
                score=0.1,
                source="fts",
            )
        ]
        s = _format_sources(chunks)
        self.assertIn("[1] a.md#3-9", s)
        self.assertIn("H1 > H2", s)
        self.assertIn("hello", s)

    def test_format_sources_omits_heading_separator_when_empty(self):
        """
        描述：heading_path 为空时，_format_sources 不应输出 ' | ' 分隔符。
        前置条件：heading_path 为空字符串。
        测试步骤：
          1) 调用 _format_sources
        预期结果：
          - header 行不包含 ' | '
        """
        chunks = [
            RetrievedChunk(
                chunk_id="c1",
                rel_path="a.md",
                title="A",
                heading_path="",
                start_line=1,
                end_line=1,
                text="x",
                score=0.1,
                source="fts",
            )
        ]
        s = _format_sources(chunks)
        header = s.splitlines()[0]
        self.assertNotIn(" | ", header)


class TestAskKB(unittest.TestCase):
    def test_ask_kb_calls_search_and_chat_and_returns_sources(self):
        """
        描述：ask_kb 应先调用 search_kb 再调用 chat_completion，并返回 answer 与 sources。
        前置条件：对 search_kb/chat_completion 进行 stub。
        测试步骤：
          1) patch kb.ask.search_kb 返回固定 chunks
          2) patch kb.ask.chat_completion 返回固定 answer
          3) 调用 ask_kb
        预期结果：
          - 返回 dict 含 query/answer/sources
          - sources 数组元素包含 path/heading_path/line_range/text
        """
        fake_chunks = [
            RetrievedChunk(
                chunk_id="c1",
                rel_path="a.md",
                title="A",
                heading_path="",
                start_line=1,
                end_line=2,
                text="ctx",
                score=0.9,
                source="fts",
            )
        ]

        with tempfile.TemporaryDirectory() as td:
            kb_root = Path(td)
            with patch("kb.ask.search_kb", return_value=fake_chunks) as p_search:
                with patch("kb.ask.chat_completion", return_value="ANSWER") as p_chat:
                    out = ask_kb(kb_root, query="Q", top_context=1, semantic=False, hybrid=False)

        self.assertEqual(out["query"], "Q")
        self.assertEqual(out["answer"], "ANSWER")
        self.assertIsInstance(out["sources"], list)
        self.assertEqual(out["sources"][0]["path"], "a.md")
        self.assertEqual(out["sources"][0]["line_range"], [1, 2])
        self.assertEqual(out["sources"][0]["text"], "ctx")
        self.assertEqual(p_search.call_count, 1)
        self.assertEqual(p_chat.call_count, 1)


if __name__ == "__main__":
    unittest.main()
