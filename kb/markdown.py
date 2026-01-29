from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .util import sha256_text


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    heading_path: str
    start_line: int
    end_line: int
    text: str
    text_hash: str


_re_heading = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_re_md_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_re_wiki_link = re.compile(r"\[\[([^\]]+)\]\]")


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines:
        return {}, 0
    if lines[0].strip() != "---":
        return {}, 0
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, 0
    raw = "\n".join(lines[1:end]).strip()
    meta = _parse_simple_yaml(raw)
    return meta, end + 1


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    cur_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if cur_list_key is not None and line.lstrip().startswith("- "):
            meta.setdefault(cur_list_key, [])
            meta[cur_list_key].append(line.lstrip()[2:].strip())
            continue
        cur_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value == "":
            cur_list_key = key
            meta[key] = []
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                meta[key] = []
            else:
                meta[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
            continue
        if value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
            continue
        meta[key] = value.strip("'\"")
    return meta


def extract_links(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _re_md_link.finditer(text):
        out.append({"kind": "md", "target": m.group(1).strip()})
    for m in _re_wiki_link.finditer(text):
        out.append({"kind": "wiki", "target": m.group(1).strip()})
    return out


def chunk_markdown(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
    min_chars: int,
) -> tuple[dict[str, Any], list[Chunk]]:
    lines = text.splitlines()
    fm, body_start = parse_frontmatter(lines)

    heading_stack: list[tuple[int, str]] = []
    chunks: list[Chunk] = []
    chunk_index = 0

    paragraph_lines: list[str] = []
    paragraph_start_line = body_start + 1
    cur_heading_path = ""

    def flush_paragraph(end_line: int) -> None:
        nonlocal chunk_index, paragraph_lines, paragraph_start_line
        raw = "\n".join(paragraph_lines).strip()
        paragraph_lines = []
        if not raw:
            return
        chunk_text = raw
        if cur_heading_path:
            chunk_text = f"{cur_heading_path}\n\n{raw}"
        for piece in _split_with_overlap(chunk_text, max_chars=max_chars, overlap_chars=overlap_chars, min_chars=min_chars):
            chunks.append(
                Chunk(
                    chunk_index=chunk_index,
                    heading_path=cur_heading_path,
                    start_line=paragraph_start_line,
                    end_line=end_line,
                    text=piece,
                    text_hash=sha256_text(piece),
                )
            )
            chunk_index += 1

    for i in range(body_start, len(lines)):
        line = lines[i]
        m = _re_heading.match(line)
        if m:
            flush_paragraph(i)
            level = len(m.group(1))
            title = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            cur_heading_path = " > ".join(h for _, h in heading_stack)
            paragraph_start_line = i + 2
            continue

        if not line.strip():
            flush_paragraph(i + 1)
            paragraph_start_line = i + 2
            continue

        paragraph_lines.append(line)

    flush_paragraph(len(lines))
    return fm, chunks


def guess_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        m = _re_heading.match(line)
        if m and len(m.group(1)) == 1:
            return m.group(2).strip()
    return fallback


def _split_with_overlap(text: str, *, max_chars: int, overlap_chars: int, min_chars: int) -> Iterable[str]:
    t = text.strip()
    if len(t) <= max_chars:
        if t:
            yield t
        return

    step = max(1, max_chars - max(0, overlap_chars))
    i = 0
    n = len(t)
    while i < n:
        piece = t[i : min(n, i + max_chars)].strip()
        is_last = i + max_chars >= n
        if piece and (len(piece) >= min_chars or is_last):
            yield piece
        if i + max_chars >= n:
            break
        i += step
