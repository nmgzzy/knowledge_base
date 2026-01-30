from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .config import resolve_paths


def tree_kb(kb_root: Path, *, depth: Optional[int]) -> dict[str, Any]:
    paths = resolve_paths(kb_root)
    kb_dir = paths.kb_dir
    if not kb_dir.exists():
        raise FileNotFoundError(f"kb dir not found: {kb_dir}")

    docs = _collect_markdown_docs(kb_dir, depth=depth)
    return {
        "kb_root": str(kb_root),
        "kb_dir": str(kb_dir),
        "depth": depth,
        "count": len(docs),
        "docs": docs,
        "tree": _format_tree("kb", docs),
    }


def _collect_markdown_docs(kb_dir: Path, *, depth: Optional[int]) -> list[str]:
    docs: list[str] = []
    max_depth = None if depth is None else max(0, int(depth))

    stack: list[tuple[Path, int]] = [(kb_dir, 0)]
    while stack:
        cur, d = stack.pop()
        if max_depth is not None and d > max_depth:
            continue
        try:
            entries = list(cur.iterdir())
        except FileNotFoundError:
            continue
        entries.sort(key=lambda p: (not p.is_dir(), p.name))
        for p in entries:
            name = p.name
            if name.startswith(".") or name == "__pycache__":
                continue
            if p.is_dir():
                stack.append((p, d + 1))
                continue
            if p.suffix.lower() in {".md", ".markdown", ".mdown"}:
                rel = p.relative_to(kb_dir).as_posix()
                docs.append(rel)

    docs.sort()
    return docs


def _format_tree(root_label: str, rel_files: list[str]) -> str:
    root: dict[str, Any] = {"_files": [], "_dirs": {}}
    for rel in rel_files:
        parts = [p for p in rel.split("/") if p]
        if not parts:
            continue
        node = root
        for part in parts[:-1]:
            node = node["_dirs"].setdefault(part, {"_files": [], "_dirs": {}})
        node["_files"].append(parts[-1])

    def render(node: dict[str, Any], prefix: str) -> list[str]:
        out: list[str] = []
        dirnames = sorted(node["_dirs"].keys())
        filenames = sorted(node["_files"])
        entries: list[tuple[str, str]] = [("dir", n) for n in dirnames] + [("file", f) for f in filenames]
        for i, (kind, name) in enumerate(entries):
            is_last = i == len(entries) - 1
            branch = "└── " if is_last else "├── "
            out.append(prefix + branch + (name + "/" if kind == "dir" else name))
            if kind == "dir":
                child_prefix = prefix + ("    " if is_last else "│   ")
                out.extend(render(node["_dirs"][name], child_prefix))
        return out

    lines = [root_label + "/"]
    lines.extend(render(root, ""))
    return "\n".join(lines)

