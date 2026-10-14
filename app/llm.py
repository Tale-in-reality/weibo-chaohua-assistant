"""Ollama 调用封装。"""
import httpx

from . import db


def _base() -> str:
    return db.get_setting("ollama_url", "http://127.0.0.1:11434").rstrip("/")


def _model() -> str:
    return db.get_setting("model", "qwen2.5:7b-instruct")


def list_models() -> list:
    try:
        r = httpx.get(_base() + "/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def health() -> dict:
    models = list_models()
    model = _model()
    base_name = model.split(":")[0]
    return {
        "ok": bool(models),
        "url": _base(),
        "model": model,
        "models": models,
        "model_ready": any(base_name in m for m in models),
    }


def chat(messages: list, temperature: float = 0.85, max_tokens: int | None = None) -> str:
    payload = {
        "model": _model(),
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens
    r = httpx.post(_base() + "/api/chat", json=payload, timeout=600)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def generate(prompt: str, system: str | None = None,
             temperature: float = 0.85, max_tokens: int | None = None) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, temperature, max_tokens)
