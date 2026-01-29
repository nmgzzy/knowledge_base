import unittest

from kb.markdown import Chunk, chunk_markdown, extract_links, guess_title, parse_frontmatter


class TestMarkdownFrontmatter(unittest.TestCase):
    def test_parse_frontmatter_empty_or_missing(self):
        """
        描述：frontmatter 不存在时应返回空 meta 且 body_start=0。
        前置条件：无。
        测试步骤：
          1) 传入空行列表
          2) 传入首行不是 --- 的行列表
        预期结果：
          - 均返回 ({}, 0)
        """
        self.assertEqual(parse_frontmatter([]), ({}, 0))
        self.assertEqual(parse_frontmatter(["# Title"]), ({}, 0))

    def test_parse_frontmatter_missing_end_marker(self):
        """
        描述：frontmatter 未闭合（缺少结束 ---）时应视为不存在。
        前置条件：首行是 --- 但未出现结束 ---。
        测试步骤：
          1) 调用 parse_frontmatter
        预期结果：
          - 返回 ({}, 0)
        """
        lines = ["---", "title: x", "tags: [a,b]"]
        self.assertEqual(parse_frontmatter(lines), ({}, 0))

    def test_parse_frontmatter_simple_yaml(self):
        """
        描述：解析简化 YAML：标量/布尔/行内 list/多行 list。
        前置条件：文本包含成对 ---。
        测试步骤：
          1) 构造含 tags/keywords/flag 的 frontmatter
          2) 调用 parse_frontmatter
        预期结果：
          - meta 字段解析正确
          - body_start 指向正文起始行（0-based index）
        """
        lines = [
            "---",
            "title: Hello",
            "flag: true",
            "tags: [a, 'b', \"c\"]",
            "keywords:",
            "  - k1",
            "  - k2",
            "---",
            "# Body",
        ]
        meta, body_start = parse_frontmatter(lines)
        self.assertEqual(meta.get("title"), "Hello")
        self.assertEqual(meta.get("flag"), True)
        self.assertEqual(meta.get("tags"), ["a", "b", "c"])
        self.assertEqual(meta.get("keywords"), ["k1", "k2"])
        self.assertEqual(body_start, 8)


class TestMarkdownChunking(unittest.TestCase):
    def test_chunk_markdown_heading_paths_and_line_ranges(self):
        """
        描述：chunk_markdown 应按标题栈 + 段落切分，并记录 heading_path 与行号范围。
        前置条件：文本包含 frontmatter、H1/H2 标题与段落。
        测试步骤：
          1) 调用 chunk_markdown（max_chars 足够大以避免再切分）
        预期结果：
          - 返回 frontmatter meta
          - chunk 数量与段落数量一致
          - chunk.heading_path 符合 H1 > H2 栈
          - chunk.start_line/end_line 对应原文行号范围（1-based）
        """
        text = "\n".join(
            [
                "---",  # 1
                "title: Doc",  # 2
                "tags: [t1]",  # 3
                "---",  # 4
                "# H1",  # 5
                "",  # 6
                "para1 line",  # 7
                "",  # 8
                "## H2",  # 9
                "",  # 10
                "para2",  # 11
                "",  # 12
            ]
        )
        fm, chunks = chunk_markdown(text, max_chars=10_000, overlap_chars=0, min_chars=1)
        self.assertEqual(fm.get("title"), "Doc")
        self.assertEqual(fm.get("tags"), ["t1"])

        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(isinstance(c, Chunk) for c in chunks))

        c1, c2 = chunks
        self.assertEqual(c1.heading_path, "H1")
        self.assertEqual(c1.start_line, 7)
        self.assertEqual(c1.end_line, 8)
        self.assertIn("para1 line", c1.text)

        self.assertEqual(c2.heading_path, "H1 > H2")
        self.assertEqual(c2.start_line, 11)
        self.assertEqual(c2.end_line, 11)
        self.assertIn("para2", c2.text)

    def test_chunk_markdown_splits_with_overlap(self):
        """
        描述：chunk_markdown 内部切分应支持 overlap（用于长段落分片）。
        前置条件：存在超长段落，且 max_chars < 段落长度。
        测试步骤：
          1) 调用 chunk_markdown(max_chars=20, overlap_chars=5)
        预期结果：
          - 产生多个 chunk
          - 每个 chunk 长度 <= max_chars（去除首尾空白后）
          - 相邻 chunk 的前后存在重叠片段（弱断言：相邻文本不完全无关）
        """
        long_para = "0123456789" * 10  # 100 chars
        text = f"# H1\n\n{long_para}\n"
        _, chunks = chunk_markdown(text, max_chars=20, overlap_chars=5, min_chars=1)
        self.assertGreaterEqual(len(chunks), 4)
        for c in chunks:
            self.assertLessEqual(len(c.text.strip()), 20)

        a = chunks[0].text
        b = chunks[1].text
        self.assertNotEqual(a, b)
        self.assertTrue(a[-5:] in b or b[:5] in a)

    def test_guess_title_prefers_first_h1(self):
        """
        描述：guess_title 应优先返回首个 H1 标题文本。
        前置条件：文本包含 H2 与 H1（H1 在前）。
        测试步骤：
          1) 调用 guess_title
        预期结果：
          - 返回 H1 标题内容
        """
        text = "## Sub\n\n# Main Title\n\nBody"
        self.assertEqual(guess_title(text, fallback="x"), "Main Title")

    def test_guess_title_fallback_when_no_h1(self):
        """
        描述：没有 H1 时，guess_title 应返回 fallback。
        前置条件：文本仅包含 H2+。
        测试步骤：
          1) 调用 guess_title
        预期结果：
          - 返回 fallback
        """
        text = "## Sub\n\nBody"
        self.assertEqual(guess_title(text, fallback="fallback"), "fallback")


class TestMarkdownLinks(unittest.TestCase):
    def test_extract_links_md_and_wiki(self):
        """
        描述：extract_links 应同时解析 Markdown link 与 Wiki link。
        前置条件：文本包含两种链接格式。
        测试步骤：
          1) 调用 extract_links
        预期结果：
          - 返回包含 kind=md/wiki 的 target 列表
        """
        text = "See [Google](https://google.com) and [[My Page]] and [Rel](docs/a.md)."
        links = extract_links(text)
        kinds = [x["kind"] for x in links]
        targets = [x["target"] for x in links]
        self.assertIn("md", kinds)
        self.assertIn("wiki", kinds)
        self.assertIn("https://google.com", targets)
        self.assertIn("My Page", targets)
        self.assertIn("docs/a.md", targets)


if __name__ == "__main__":
    unittest.main()
