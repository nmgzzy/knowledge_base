from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import default_config, load_config, resolve_paths, save_config
from .fs_ops import ensure_dir_meta


def init_kb(kb_root: Path, *, force: bool) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    kb_root.mkdir(parents=True, exist_ok=True)
    paths = resolve_paths(kb_root)
    paths.kb_dir.mkdir(parents=True, exist_ok=True)
    paths.index_dir.mkdir(parents=True, exist_ok=True)
    paths.vector_dir.mkdir(parents=True, exist_ok=True)

    if force or not paths.config_path.exists():
        save_config(kb_root, default_config())

    cfg = load_config(kb_root)
    meta_filename = str(cfg.get("meta_filename", "meta.json"))

    ensure_dir_meta(paths.kb_dir, meta_filename=meta_filename)
    return {
        "kb_root": str(kb_root),
        "kb_dir": str(paths.kb_dir),
        "index_dir": str(paths.index_dir),
        "vector_dir": str(paths.vector_dir),
        "config_path": str(paths.config_path),
    }
