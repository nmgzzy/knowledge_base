import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def write_json_atomic(path: Path, obj: Any, *, indent: int = 2) -> None:
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=indent) + "\n")


def safe_relpath(path: Path) -> str:
    return path.as_posix().lstrip("/")


def ensure_rel_under_base(rel: str) -> str:
    rel = rel.replace("\\", "/").strip()
    rel = rel.lstrip("/")
    if rel in ("", "."):
        return ""
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("invalid relative path")
    return "/".join(parts)


def getenv_trim(name: str) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def json_dumps_compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
