from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from .autoadd_bulk import autoadd_inbox
from .ask import ask_kb
from .bootstrap import init_kb
from .doctor import doctor_kb
from .indexer import index_kb
from .importer import add_to_kb
from .search import search_kb
from .tree import tree_kb


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_parser().parse_args(argv)
    try:
        if args.cmd == "init":
            out = init_kb(Path(args.kb_root), force=args.force)
            _emit(out, json_mode=args.json)
            return

        kb_root = Path(args.kb_root).expanduser().resolve()

        if args.cmd == "add":
            out = add_to_kb(
                kb_root,
                src=Path(args.path),
                dest_rel_dir=args.dest,
                auto=bool(args.auto),
                move=bool(args.move),
            )
            _emit(out, json_mode=args.json)
            return
        if args.cmd == "autoadd":
            inbox_dir = Path(args.inbox).expanduser().resolve() if args.inbox else (kb_root / "_inbox")
            move = True
            if getattr(args, "copy", False):
                move = False
            if getattr(args, "move", False):
                move = True
            out = autoadd_inbox(kb_root, inbox_dir=inbox_dir, move=move)
            _emit(out, json_mode=args.json)
            return

        if args.cmd == "index":
            out = index_kb(
                kb_root,
                rebuild=bool(args.rebuild),
                embed_chunks=bool(args.embed),
                only_rel_paths=args.only,
            )
            _emit(out, json_mode=args.json)
            return

        if args.cmd == "search":
            hits = search_kb(
                kb_root,
                query=args.query,
                top_k=int(args.top),
                semantic=bool(args.semantic),
                hybrid=bool(args.hybrid),
            )
            out = {"query": args.query, "results": [h.to_dict() for h in hits]}
            _emit(out, json_mode=args.json)
            return

        if args.cmd == "ask":
            out = ask_kb(
                kb_root,
                query=args.query,
                top_context=int(args.top_context),
                semantic=bool(args.semantic),
                hybrid=bool(args.hybrid),
            )
            _emit(out, json_mode=args.json)
            return

        if args.cmd == "repair":
            out = index_kb(kb_root, rebuild=True, embed_chunks=bool(args.embed), only_rel_paths=None)
            _emit(out, json_mode=args.json)
            return

        if args.cmd == "tree":
            out = tree_kb(kb_root, depth=args.depth)
            if args.json:
                _emit(out, json_mode=True)
            else:
                _emit(out["tree"], json_mode=False)
            return

        if args.cmd == "doctor":
            out = doctor_kb(
                kb_root,
                check_chat=bool(args.chat),
                check_embed=bool(args.embed),
                text=str(args.text),
            )
            _emit(out, json_mode=args.json)
            return

        raise SystemExit(2)
    except Exception as e:
        if getattr(args, "json", False):
            _emit({"error": str(e)}, json_mode=True)
        else:
            print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def _emit(obj: Any, *, json_mode: bool) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            sys.stdout.write(f"{k}: {v}\n")
        return
    sys.stdout.write(str(obj) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kb")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化知识库根目录结构")
    p_init.add_argument("kb_root", help="知识库根目录路径")
    p_init.add_argument("--force", action="store_true", help="覆盖已有配置文件")
    p_init.add_argument("--json", action="store_true", help="JSON 输出")

    def add_kb_root(sp):
        sp.add_argument("--kb-root", dest="kb_root", required=True, help="知识库根目录路径")
        sp.add_argument("--json", action="store_true", help="JSON 输出")

    p_add = sub.add_parser("add", help="导入文档到知识树")
    p_add.add_argument("path", help="文件或目录路径")
    add_kb_root(p_add)
    p_add.add_argument("--dest", default=None, help="目标目录（相对 kb/）")
    p_add.add_argument("--auto", action="store_true", help="启用 LLM 自动归档（若失败自动退化）")
    p_add.add_argument("--move", action="store_true", help="移动源文件（默认复制）")

    p_autoadd = sub.add_parser("autoadd", help="自动归档 _inbox 内的所有文件到知识树")
    add_kb_root(p_autoadd)
    p_autoadd.add_argument("--inbox", default=None, help="待归档目录路径（默认 <kb_root>/_inbox）")
    g_autoadd = p_autoadd.add_mutually_exclusive_group()
    g_autoadd.add_argument("--move", action="store_true", help="移动源文件（默认）")
    g_autoadd.add_argument("--copy", action="store_true", help="复制源文件（保留在 inbox）")

    p_index = sub.add_parser("index", help="构建或增量更新索引")
    add_kb_root(p_index)
    p_index.add_argument("--rebuild", action="store_true", help="重建索引数据库")
    p_index.add_argument("--embed", action="store_true", help="生成并写入 embedding（需要配置）")
    p_index.add_argument("--only", action="append", help="仅更新某些 rel_path（可重复）")

    p_search = sub.add_parser("search", help="混合检索（默认 FTS，可选语义/融合）")
    p_search.add_argument("query", help="查询文本")
    add_kb_root(p_search)
    p_search.add_argument("--top", type=int, default=10, help="返回条数")
    p_search.add_argument("--semantic", action="store_true", help="仅语义检索（需要 embedding）")
    p_search.add_argument("--hybrid", action="store_true", help="融合 FTS+向量（需要 embedding）")

    p_ask = sub.add_parser("ask", help="问答（强制带引用）")
    p_ask.add_argument("query", help="问题")
    add_kb_root(p_ask)
    p_ask.add_argument("--top-context", type=int, default=8, help="检索上下文条数")
    p_ask.add_argument("--semantic", action="store_true", help="仅语义检索（需要 embedding）")
    p_ask.add_argument("--hybrid", action="store_true", help="融合 FTS+向量（需要 embedding）")

    p_repair = sub.add_parser("repair", help="修复索引/向量一致性（第一版=重建索引）")
    add_kb_root(p_repair)
    p_repair.add_argument("--embed", action="store_true", help="重建时生成 embedding（需要配置）")

    p_tree = sub.add_parser("tree", help="列出知识树文档（支持深度）")
    add_kb_root(p_tree)
    p_tree.add_argument("--depth", type=int, default=None, help="最大目录深度（0=仅根目录）")

    p_doctor = sub.add_parser("doctor", help="检测 OpenAI-compatible 接口可用性（chat/embeddings）")
    add_kb_root(p_doctor)
    p_doctor.add_argument("--chat", action="store_true", help="仅检测 chat/completions")
    p_doctor.add_argument("--embed", action="store_true", help="仅检测 embeddings")
    p_doctor.add_argument("--text", default="ping", help="测试用输入文本")

    return p
