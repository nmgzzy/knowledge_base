from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import default_config, load_config, resolve_paths, save_config
from .fs_ops import ensure_dir_meta
from .util import write_text_atomic


def init_kb(kb_root: Path, *, force: bool) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    kb_root.mkdir(parents=True, exist_ok=True)
    (kb_root / "_inbox").mkdir(parents=True, exist_ok=True)
    paths = resolve_paths(kb_root)
    paths.kb_dir.mkdir(parents=True, exist_ok=True)
    paths.index_dir.mkdir(parents=True, exist_ok=True)
    paths.vector_dir.mkdir(parents=True, exist_ok=True)

    if force or not paths.config_path.exists():
        save_config(kb_root, default_config())

    cfg = load_config(kb_root)
    meta_filename = str(cfg.get("meta_filename", "meta.json"))

    ensure_dir_meta(paths.kb_dir, meta_filename=meta_filename)
    gitignore_path = kb_root / ".gitignore"
    if not gitignore_path.exists():
        write_text_atomic(
            gitignore_path,
            "\n".join(
                [
                    ".DS_Store",
                    "__pycache__/",
                    "*.py[cod]",
                    ".venv/",
                    "venv/",
                    "_inbox/",
                    f"{paths.index_dir.name}/",
                    f"{paths.vector_dir.name}/",
                    "",
                ]
            ),
        )
    skill_path = kb_root / "kb_agent_skill.md"
    if not skill_path.exists():
        write_text_atomic(
            skill_path,
            "\n".join(
                [
                    "# Knowledge Base Agent Skill",
                    "",
                    "你是本仓库知识库（kb_root）的操作代理，目标是在不丢失信息的前提下，把资料归档到 `kb/` 知识树中，并保持可检索与可追溯引用。",
                    "",
                    "## 工作边界",
                    "",
                    "- 只把长期内容写入 `kb/`（Markdown）与各目录的 `meta.json`",
                    "- 不要依赖 `kb_index/` 与 `kb_vector/` 的内容：它们可重建，默认不纳入版本管理",
                    "- 不要写入任何 API Key；OpenAI-compatible 配置只允许引用环境变量",
                    "",
                    "## 常用操作（优先用 CLI）",
                    "",
                    "- 初始化后导入资料：`kb add <path> --kb-root <kb_root>`",
                    "- 导入后更新索引：`kb index --kb-root <kb_root>`（必要时 `--rebuild`）",
                    "- 查看知识树：`kb tree --kb-root <kb_root>`",
                    "- 检索定位：`kb search \"<query>\" --kb-root <kb_root> --json`",
                    "- 带引用问答：`kb ask \"<query>\" --kb-root <kb_root> --json`（需配置 chat 模型）",
                    "",
                    "## 待归档文件夹",
                    "",
                    "- 待归档入口：把原始文件先丢进 `<kb_root>/_inbox/`",
                    "- 一键归档：`kb autoadd --kb-root <kb_root>`（默认移动源文件清空投递箱）",
                    "- 单文件归档：`kb add <file> --kb-root <kb_root> --auto --move`",
                    "",
                    "## 归档准则",
                    "",
                    "- 目录优先：先决定知识归属目录，再决定文件名（避免频繁移动）",
                    "- 文档结构：使用清晰标题层级；保持段落短小，便于 chunk 引用定位",
                    "- 目录元数据：必要时更新目录 `meta.json` 的 `title/summary/tags/keywords/rules`，用于后续结构召回/自动归档",
                    "",
                    "## 变更后的动作",
                    "",
                    "- 只要对 `kb/` 下 Markdown 或 `meta.json` 有增删改，执行一次 `kb index --kb-root <kb_root>` 以刷新检索与引用行号",
                    "",
                ]
            ),
        )
    return {
        "kb_root": str(kb_root),
        "kb_dir": str(paths.kb_dir),
        "index_dir": str(paths.index_dir),
        "vector_dir": str(paths.vector_dir),
        "config_path": str(paths.config_path),
    }
