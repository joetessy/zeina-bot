"""OpenAI-compatible LLM client for Zeina.

This is the single seam through which every model call flows. It talks to any
OpenAI-compatible server selected by ``config.LLM_BASE_URL`` — llama.cpp /
llama-swap, Ollama (``/v1``), LM Studio, vLLM, or a cloud provider — so nothing
in the rest of the app is tied to a specific inference runtime.

Public surface:
    chat(messages, ...)        -> message object (non-stream) | token iterator (stream)
    parse_tool_calls(message)  -> [{"id", "name", "arguments": dict}, ...]
    assistant_tool_call_msg(m) -> history-serializable assistant message
    list_model_ids()           -> [str]
    health()                   -> (ok: bool, detail: str)
    image_data_uri(path)       -> "data:image/...;base64,..."
"""
from __future__ import annotations

import json
import threading
from typing import Any, Iterator, Optional

from openai import OpenAI

from zeina import config

_client: Optional[OpenAI] = None
_client_sig: Optional[tuple] = None
_lock = threading.Lock()


def _signature() -> tuple:
    return (config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_TIMEOUT, config.LLM_MAX_RETRIES)


def get_client() -> OpenAI:
    """Return a cached OpenAI client, rebuilding it if the config changed."""
    global _client, _client_sig
    with _lock:
        sig = _signature()
        if _client is None or _client_sig != sig:
            _client = OpenAI(
                base_url=config.LLM_BASE_URL,
                api_key=config.LLM_API_KEY or "local",
                timeout=config.LLM_TIMEOUT,
                max_retries=config.LLM_MAX_RETRIES,
            )
            _client_sig = sig
        return _client


def chat(
    messages: list[dict],
    *,
    model: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    stream: bool = False,
    temperature: Optional[float] = None,
    response_format: Optional[dict] = None,
):
    """Run a chat completion.

    Non-streaming: returns the response ``message`` object, which exposes
    ``.content`` (str | None) and ``.tool_calls`` (list | None).
    Streaming: returns an iterator yielding content-token strings.
    """
    client = get_client()
    kwargs: dict[str, Any] = {
        "model": model or config.CHAT_MODEL,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    if response_format is not None:
        kwargs["response_format"] = response_format

    if stream:
        return _stream_tokens(client, kwargs)

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message


def _stream_tokens(client: OpenAI, kwargs: dict) -> Iterator[str]:
    """Yield content tokens from a streamed completion."""
    kwargs = {**kwargs, "stream": True}
    for chunk in client.chat.completions.create(**kwargs):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        token = getattr(delta, "content", None)
        if token:
            yield token


def parse_tool_calls(message) -> list[dict]:
    """Normalize a message's tool_calls into [{"id", "name", "arguments": dict}]."""
    out: list[dict] = []
    for tc in (getattr(message, "tool_calls", None) or []):
        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            args = {}
        out.append({"id": tc.id, "name": tc.function.name, "arguments": args})
    return out


def assistant_tool_call_msg(message) -> dict:
    """Serialize an assistant message carrying tool_calls for conversation history.

    The OpenAI protocol requires this message to precede the matching ``tool``
    result messages, so it must be stored verbatim (ids included).
    """
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in (message.tool_calls or [])
        ],
    }


def list_model_ids() -> list[str]:
    """Return the model ids served by the backend (best-effort; [] on failure)."""
    try:
        return [m.id for m in get_client().models.list().data]
    except Exception:
        return []


def health(timeout: float = 8.0) -> tuple[bool, str]:
    """Cheap reachability check used at startup. Returns (ok, detail)."""
    try:
        client = get_client().with_options(timeout=timeout)
        ids = [m.id for m in client.models.list().data]
        return True, ", ".join(ids[:6]) if ids else "no models served"
    except Exception as e:
        return False, str(e)


def image_data_uri(path: str) -> str:
    """Read an image file and return a base64 ``data:`` URI for an image_url part."""
    import base64

    ext = path.lower().rsplit(".", 1)[-1] if "." in path else "png"
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"
