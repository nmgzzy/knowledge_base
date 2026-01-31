from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config import load_config
from .openai_compat import OpenAICompatError, chat_completion, embed, from_config_dict
from .util import getenv_trim


def doctor_kb(
    kb_root: Path,
    *,
    check_chat: bool,
    check_embed: bool,
    text: str,
) -> dict[str, Any]:
    kb_root = kb_root.expanduser().resolve()
    cfg = load_config(kb_root)
    oa_cfg = from_config_dict(cfg.get("openai_compat", {}) if isinstance(cfg, dict) else {})

    if not (check_chat or check_embed):
        check_chat = True
        check_embed = True

    checks: dict[str, Any] = {}
    ok = True

    if check_embed:
        r = _check_embed(oa_cfg, text=text)
        checks["embed"] = r
        ok = ok and bool(r.get("ok"))
    if check_chat:
        r = _check_chat(oa_cfg, text=text)
        checks["chat"] = r
        ok = ok and bool(r.get("ok"))

    info = {
        "base_url": oa_cfg.base_url,
        "api_key_env": oa_cfg.api_key_env,
        "api_key_present": bool(getenv_trim(oa_cfg.api_key_env)),
        "model_chat": oa_cfg.model_chat,
        "model_embed": oa_cfg.model_embed,
        "timeout_s": oa_cfg.timeout_s,
        "max_retries": oa_cfg.max_retries,
    }
    return {"ok": ok, "kb_root": str(kb_root), "openai_compat": info, "checks": checks}


def _check_embed(oa_cfg, *, text: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        vecs = embed(oa_cfg, texts=[text])
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        dim = 0
        if vecs and isinstance(vecs[0], list):
            dim = len(vecs[0])
        return {"ok": True, "elapsed_ms": elapsed_ms, "result": {"vectors": len(vecs), "dim": dim}}
    except OpenAICompatError as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(e)}
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(e)}


def _check_chat(oa_cfg, *, text: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        out = chat_completion(oa_cfg, messages=[{"role": "user", "content": text}])
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        sample = out[:80]
        return {"ok": True, "elapsed_ms": elapsed_ms, "result": {"length": len(out), "sample": sample}}
    except OpenAICompatError as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(e)}
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(e)}
