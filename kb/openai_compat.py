from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from .util import getenv_trim


@dataclass(frozen=True)
class OpenAICompatConfig:
    base_url: str
    api_key_env: str
    model_chat: str
    model_embed: str
    timeout_s: int
    max_retries: int
    extra_headers: dict[str, str]


def from_config_dict(cfg: dict[str, Any]) -> OpenAICompatConfig:
    base_url = str(cfg.get("base_url", "")).rstrip("/")
    api_key_env = str(cfg.get("api_key_env", "KB_OPENAI_API_KEY"))
    model_chat = str(cfg.get("model_chat", ""))
    model_embed = str(cfg.get("model_embed", ""))
    timeout_s = int(cfg.get("timeout_s", 60))
    max_retries = int(cfg.get("max_retries", 2))
    extra_headers_raw = cfg.get("extra_headers", {})
    extra_headers: dict[str, str] = {}
    if isinstance(extra_headers_raw, dict):
        for k, v in extra_headers_raw.items():
            if k and v is not None:
                extra_headers[str(k)] = str(v)
    return OpenAICompatConfig(
        base_url=base_url,
        api_key_env=api_key_env,
        model_chat=model_chat,
        model_embed=model_embed,
        timeout_s=timeout_s,
        max_retries=max_retries,
        extra_headers=extra_headers,
    )


class OpenAICompatError(RuntimeError):
    pass


def chat_completion(cfg: OpenAICompatConfig, *, messages: list[dict[str, Any]]) -> str:
    if not cfg.base_url or not cfg.model_chat:
        raise OpenAICompatError("openai_compat.base_url/model_chat not configured")
    payload = {"model": cfg.model_chat, "messages": messages, "stream": False}
    data = _post_json(cfg, f"{cfg.base_url}/v1/chat/completions", payload)
    try:
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        raise OpenAICompatError(f"unexpected chat response: {e}") from e


def embed(cfg: OpenAICompatConfig, *, texts: list[str]) -> list[list[float]]:
    if not cfg.base_url or not cfg.model_embed:
        raise OpenAICompatError("openai_compat.base_url/model_embed not configured")
    payload = {"model": cfg.model_embed, "input": texts}
    data = _post_json(cfg, f"{cfg.base_url}/v1/embeddings", payload)
    try:
        items = data["data"]
        items_sorted = sorted(items, key=lambda x: x.get("index", 0))
        return [it["embedding"] for it in items_sorted]
    except Exception as e:
        raise OpenAICompatError(f"unexpected embeddings response: {e}") from e


def _post_json(cfg: OpenAICompatConfig, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(cfg.extra_headers)
    api_key = getenv_trim(cfg.api_key_env)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_err: Optional[Exception] = None
    for attempt in range(cfg.max_retries + 1):
        try:
            req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
            out = json.loads(raw)
            if not isinstance(out, dict):
                raise OpenAICompatError("response is not a JSON object")
            return out
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            if attempt >= cfg.max_retries:
                break
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise OpenAICompatError(str(last_err) if last_err else "request failed")
