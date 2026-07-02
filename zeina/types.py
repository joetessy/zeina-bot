"""Shared typed structures for Zeina.

These are the data shapes that flow between the assistant, the LLM seam
(zeina/llm.py), the tool framework, and the UI layer. Keeping them as
TypedDicts (rather than classes) preserves the JSON-serializable dict
representation the OpenAI protocol and the session files expect.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ChatMessage(TypedDict, total=False):
    """One OpenAI-style chat message.

    ``content`` is a plain string for normal turns, or a list of content
    parts (text + image_url) for vision calls. ``tool_calls`` and
    ``tool_call_id`` only appear on assistant tool-call messages and their
    matching tool-result messages.
    """
    role: str                      # "system" | "user" | "assistant" | "tool"
    content: str | list[dict[str, Any]]
    tool_calls: list[ToolCallPayload]
    tool_call_id: str


class ToolCallPayload(TypedDict):
    """Serialized tool call as stored in an assistant message (OpenAI shape)."""
    id: str
    type: str                      # always "function"
    function: ToolCallFunction


class ToolCallFunction(TypedDict):
    """The function part of a serialized tool call."""
    name: str
    arguments: str                 # raw JSON string, per the OpenAI protocol


class ToolCall(TypedDict):
    """A normalized, parsed tool call (see llm.parse_tool_calls)."""
    id: str
    name: str
    arguments: dict[str, Any]


class UIAction(TypedDict, total=False):
    """A control_self action matched by the Stage-0 patterns or the model."""
    action: str
    value: str


class ToolSchema(TypedDict):
    """An OpenAI function-calling tool schema entry."""
    type: str                      # always "function"
    function: dict[str, Any]
