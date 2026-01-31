from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .openai_compat import OpenAICompatError, chat_completion, embed, from_config_dict
from .util import getenv_trim

logger = logging.getLogger(__name__)


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

    logger.info("doctor start chat=%s embed=%s base_url=%s", bool(check_chat), bool(check_embed), oa_cfg.base_url)
    checks: dict[str, Any] = {}
    ok = True

    if check_embed:
        r = _check_embed(oa_cfg, text=text)
        checks["embed"] = r
        ok = ok and bool(r.get("ok"))
        logger.info("doctor embed ok=%s elapsed_ms=%s", bool(r.get("ok")), r.get("elapsed_ms"))
    if check_chat:
        r = _check_chat(oa_cfg, text=text)
        checks["chat"] = r
        ok = ok and bool(r.get("ok"))
        logger.info("doctor chat ok=%s elapsed_ms=%s", bool(r.get("ok")), r.get("elapsed_ms"))

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


def format_doctor_report(out: dict[str, Any]) -> str:
    kb_root = str(out.get("kb_root", ""))
    ok = bool(out.get("ok"))
    oa = out.get("openai_compat") if isinstance(out.get("openai_compat"), dict) else {}
    checks = out.get("checks") if isinstance(out.get("checks"), dict) else {}

    base_url = str(oa.get("base_url", ""))
    model_chat = str(oa.get("model_chat", ""))
    model_embed = str(oa.get("model_embed", ""))
    api_key_env = str(oa.get("api_key_env", ""))
    api_key_present = bool(oa.get("api_key_present"))
    timeout_s = oa.get("timeout_s")
    max_retries = oa.get("max_retries")

    lines: list[str] = []
    lines.append(f"KB Doctor: {'OK' if ok else 'FAIL'}")
    if kb_root:
        lines.append(f"- kb_root: {kb_root}")
    lines.append(f"- base_url: {base_url or '(empty)'}")
    lines.append(f"- model_chat: {model_chat or '(empty)'}")
    lines.append(f"- model_embed: {model_embed or '(empty)'}")
    if api_key_env:
        lines.append(f"- api_key: {api_key_env} ({'present' if api_key_present else 'missing'})")
    if timeout_s is not None or max_retries is not None:
        lines.append(f"- http: timeout_s={timeout_s}, max_retries={max_retries}")

    if checks:
        lines.append("- checks:")
        for name in ("embed", "chat"):
            if name not in checks:
                continue
            c = checks.get(name)
            if not isinstance(c, dict):
                lines.append(f"  - {name}: FAIL (bad result shape)")
                continue
            c_ok = bool(c.get("ok"))
            elapsed = c.get("elapsed_ms")
            ms = f"{elapsed}ms" if isinstance(elapsed, int) else "n/a"
            if c_ok:
                result = c.get("result") if isinstance(c.get("result"), dict) else {}
                summary = _summarize_check_result(name, result)
                lines.append(f"  - {name}: OK ({summary}) [{ms}]")
            else:
                err = str(c.get("error", "")).strip()
                err = err or "unknown error"
                lines.append(f"  - {name}: FAIL [{ms}]")
                lines.append(f"    error: {err}")

    hints = _doctor_hints(oa, checks)
    if hints:
        lines.append("- hints:")
        for h in hints:
            lines.append(f"  - {h}")

    return "\n".join(lines) + "\n"


def _summarize_check_result(name: str, result: dict[str, Any]) -> str:
    if name == "embed":
        vectors = result.get("vectors")
        dim = result.get("dim")
        v = str(vectors) if isinstance(vectors, int) else "?"
        d = str(dim) if isinstance(dim, int) else "?"
        return f"vectors={v}, dim={d}"
    if name == "chat":
        length = result.get("length")
        sample = str(result.get("sample", ""))
        sample = sample.replace("\n", " ").strip()
        if len(sample) > 60:
            sample = sample[:60] + "…"
        l = str(length) if isinstance(length, int) else "?"
        return f"length={l}, sample={sample!r}"
    return "ok"


def _doctor_hints(openai_compat: dict[str, Any], checks: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    base_url = str(openai_compat.get("base_url", "")).strip()
    model_chat = str(openai_compat.get("model_chat", "")).strip()
    model_embed = str(openai_compat.get("model_embed", "")).strip()
    api_key_env = str(openai_compat.get("api_key_env", "")).strip()
    api_key_present = bool(openai_compat.get("api_key_present"))

    if not base_url:
        hints.append("请在 kb_config.json 配置 openai_compat.base_url")
    if "chat" in checks and not model_chat:
        hints.append("请在 kb_config.json 配置 openai_compat.model_chat（用于 chat/completions）")
    if "embed" in checks and not model_embed:
        hints.append("请在 kb_config.json 配置 openai_compat.model_embed（用于 embeddings）")
    if api_key_env and not api_key_present:
        hints.append(f"请设置环境变量 {api_key_env}（API Key）或在 extra_headers 中注入鉴权头")
    return hints


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
