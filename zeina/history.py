"""Conversation-history utilities: LLM name extraction and summarization.

Both use the (cheap) router model. Pure functions over message lists — no
assistant state.
"""
from __future__ import annotations

from typing import Callable

from zeina import config, llm
from zeina.types import ChatMessage

#: Observability sink: (level, message) -> None
ObsFn = Callable[[str, str], None]


def extract_name(message: str) -> str:
    """Use the router model to pull a proper name out of a message."""
    try:
        msg = llm.chat(
            [{
                "role": "user",
                "content": (
                    "Extract the name from this message. Reply with ONLY the name, nothing else.\n"
                    "Examples:\n"
                    "  'change your name to Luna' → Luna\n"
                    "  'call me Yusuf from now on' → Yusuf\n"
                    "  'rename yourself Alex' → Alex\n\n"
                    f"Message: \"{message}\""
                ),
            }],
            model=config.ROUTER_MODEL,
            temperature=0,
        )
        return (msg.content or "").strip()
    except Exception:
        return ""


def summarize_history(
    history: list[ChatMessage], obs: ObsFn
) -> list[ChatMessage]:
    """Summarize old conversation turns when history grows too long.

    Returns the (possibly unchanged) history list. Falls back to simple
    truncation if the summarization call fails. Assumes ``history[0]`` is the
    system message.
    """
    if config.MAX_CONVERSATION_LENGTH <= 0:
        return history
    if len(history) <= config.MAX_CONVERSATION_LENGTH + 4:
        return history

    keep_recent = max(config.MAX_CONVERSATION_LENGTH // 2, 4)
    to_summarize = history[1:-keep_recent]
    recent = history[-keep_recent:]

    if not to_summarize:
        return history

    text = "\n".join(
        f"{m['role'].upper()}: {str(m.get('content', ''))[:300]}"
        for m in to_summarize
    )
    try:
        msg = llm.chat(
            [{
                "role": "user",
                "content": (
                    "Summarize this conversation in 2-3 sentences, preserving key facts, "
                    f"names, and any decisions made:\n\n{text}"
                ),
            }],
            model=config.ROUTER_MODEL,
            temperature=0,
        )
        summary = (msg.content or "").strip()
        if summary:
            summary_msg: ChatMessage = {
                "role": "assistant",
                "content": f"[Earlier conversation summary: {summary}]",
            }
            obs("lite", f"History summarized: {len(to_summarize)} msgs → 1 summary")
            return [history[0], summary_msg] + recent
    except Exception as e:
        obs("lite", f"Summarization failed ({e}), falling back to truncation")

    return [history[0]] + history[-config.MAX_CONVERSATION_LENGTH:]
