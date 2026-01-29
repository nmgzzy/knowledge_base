from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import read_json, write_json_atomic


@dataclass(frozen=True)
class KBPaths:
    kb_dir: Path
    index_dir: Path
    vector_dir: Path
    config_path: Path


def default_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "paths": {"kb": "kb", "index": "kb_index", "vector": "kb_vector"},
        "meta_filename": "meta.json",
        "chunking": {"max_chars": 1200, "overlap_chars": 150, "min_chars": 20},
        "openai_compat": {
            "base_url": "",
            "api_key_env": "KB_OPENAI_API_KEY",
            "model_chat": "",
            "model_embed": "",
            "timeout_s": 60,
            "max_retries": 2,
            "extra_headers": {},
        },
    }


def resolve_paths(kb_root: Path) -> KBPaths:
    kb_root = kb_root.expanduser().resolve()
    config_path = kb_root / "kb_config.json"
    cfg = default_config()
    if config_path.exists():
        try:
            cfg = read_json(config_path)
        except Exception:
            cfg = default_config()
    paths_cfg = cfg.get("paths") if isinstance(cfg, dict) else None
    if not isinstance(paths_cfg, dict):
        paths_cfg = default_config()["paths"]
    kb_dir = kb_root / str(paths_cfg.get("kb", "kb"))
    index_dir = kb_root / str(paths_cfg.get("index", "kb_index"))
    vector_dir = kb_root / str(paths_cfg.get("vector", "kb_vector"))
    return KBPaths(kb_dir=kb_dir, index_dir=index_dir, vector_dir=vector_dir, config_path=config_path)


def load_config(kb_root: Path) -> dict[str, Any]:
    config_path = kb_root.expanduser().resolve() / "kb_config.json"
    if not config_path.exists():
        return default_config()
    cfg = read_json(config_path)
    if not isinstance(cfg, dict):
        return default_config()
    base = default_config()
    nested_keys = ("paths", "chunking", "openai_compat")

    for k, v in cfg.items():
        if k in nested_keys:
            continue
        base[k] = v

    for k in nested_keys:
        if isinstance(base.get(k), dict) and isinstance(cfg.get(k), dict):
            merged = dict(base[k])
            merged.update(cfg[k])
            base[k] = merged

    return base


def save_config(kb_root: Path, cfg: dict[str, Any]) -> None:
    kb_root = kb_root.expanduser().resolve()
    write_json_atomic(kb_root / "kb_config.json", cfg)
