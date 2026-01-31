from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .util import now_iso, read_json, write_json_atomic


def ensure_dir_meta(dir_path: Path, *, meta_filename: str) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    meta_path = dir_path / meta_filename
    if meta_path.exists():
        return meta_path
    meta = {
        "schema_version": 1,
        "title": dir_path.name,
        "summary": "",
        "tags": [],
        "keywords": [],
        "dir_type": "",
        "rules": {},
        "updated_at": now_iso(),
    }
    write_json_atomic(meta_path, meta)
    return meta_path


def ensure_dir_meta_chain(base_dir: Path, *, rel_dir: str, meta_filename: str) -> list[Path]:
    base_dir = base_dir.expanduser().resolve()
    rel_dir = (rel_dir or "").replace("\\", "/").strip()
    created: list[Path] = []
    created.append(ensure_dir_meta(base_dir, meta_filename=meta_filename))
    if not rel_dir or rel_dir == ".":
        return created
    cur = base_dir
    for part in [p for p in rel_dir.split("/") if p and p != "."]:
        cur = cur / part
        created.append(ensure_dir_meta(cur, meta_filename=meta_filename))
    return created


def read_dir_meta(dir_path: Path, *, meta_filename: str) -> dict[str, Any]:
    meta_path = ensure_dir_meta(dir_path, meta_filename=meta_filename)
    meta = read_json(meta_path)
    if not isinstance(meta, dict):
        return {}
    return meta


def merge_meta(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    for k, v in patch.items():
        if v is None:
            continue
        if isinstance(v, list) and isinstance(out.get(k), list):
            merged = list(out[k])
            for item in v:
                if item not in merged:
                    merged.append(item)
            out[k] = merged
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
            continue
        if out.get(k) in (None, "", [], {}):
            out[k] = v
    out["updated_at"] = now_iso()
    return out


def copy_or_move(src: Path, dst: Path, *, move: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
