"""Background extraction of durable user facts from conversation turns.

Split out of the assistant orchestrator. Runs on a worker thread after each
non-tool turn, asks the (cheap) router model to pull self-disclosures from what
the user said, and appends them to the active profile's memory file.

Uses JSON-object response formatting for robustness, with a defensive fallback
for backends that ignore ``response_format``.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from zeina import config, llm

# Cheap first-person gate: a pure question/command with no "I/my/..." marker
# cannot contain a self-disclosure, so we skip the LLM call entirely.
_FIRST_PERSON = (" i ", " i'm ", " i've ", " i'd ", " i'll ", " my ", " mine ", " myself ")

_PROMPT = (
    "Decide whether the user's message contains a durable self-disclosure, then extract it.\n\n"
    "STEP 1 — Guard. Did the user make a direct statement about themselves — their preferences, "
    "life, identity, plans, or habits? If the message is a question, a request, a task, or a "
    "command, return no facts. If it is about someone or something else, return no facts.\n\n"
    "STEP 2 — Extract (only if STEP 1 passed). Pull out durable facts:\n"
    "  - Preferences & tastes (food, music, hobbies)\n"
    "  - Personal details (name, relationships, family, location)\n"
    "  - Plans & intentions (trips, goals, purchases)\n"
    "  - Routines, habits, lifestyle\n"
    "  - Work & education (role, company, skills)\n"
    "  - Beliefs, values, identity\n\n"
    "Rules:\n"
    "- Only extract what the user explicitly stated. No stereotypes or inferences.\n"
    "- NEVER start a fact with 'The user' or 'User'. Drop the subject: "
    "'likes cheese' (correct), 'The user likes cheese' (WRONG).\n"
    "- Skip how they communicate (tone/style); extract content only.\n"
    "- Skip one-off requests, fleeting tasks, and facts about other people.\n"
    "- Skip already-known facts listed below.\n\n"
    "{existing_block}"
    "USER MESSAGE: {user_message}\n\n"
    'Respond with ONLY a JSON object of the form {{"facts": ["fact one", "fact two"]}}. '
    'Use an empty list if nothing qualifies.'
)

_SUBJECT_PREFIXES = ("The user ", "the user ", "User ", "user ")


def _parse_facts(content: str) -> list[str]:
    """Extract the facts list from a model response, tolerating stray prose."""
    content = (content or "").strip()
    if not content:
        return []
    # Preferred path: a JSON object with a "facts" array.
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(content[start:end + 1])
            facts = obj.get("facts", []) if isinstance(obj, dict) else []
            if isinstance(facts, list):
                return [f for f in facts if isinstance(f, str)]
        except (json.JSONDecodeError, AttributeError):
            pass
    # Fallback: a bare JSON array.
    start, end = content.find("["), content.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            arr = json.loads(content[start:end + 1])
            if isinstance(arr, list):
                return [f for f in arr if isinstance(f, str)]
        except json.JSONDecodeError:
            pass
    return []


def _clean(facts: list[str]) -> list[str]:
    """Strip subjects and blanks the model may have left in despite instructions."""
    out: list[str] = []
    for entry in facts:
        fact = entry.strip()
        if not fact:
            continue
        for prefix in _SUBJECT_PREFIXES:
            if fact.startswith(prefix):
                fact = fact[len(prefix):]
                break
        if fact:
            out.append(fact)
    return out


def extract_memories(
    settings,
    user_message: str,
    *,
    obs: Optional[Callable[[str, str], None]] = None,
    on_saved: Optional[Callable[[], None]] = None,
) -> None:
    """Pull durable self-disclosures from ``user_message`` and persist them."""
    _obs = obs or (lambda level, msg: None)

    msg_lower = f" {user_message.lower()} "
    if not any(tok in msg_lower for tok in _FIRST_PERSON):
        return

    try:
        profile = settings.active_profile_name
        existing = settings.load_memories(profile)
        existing_block = ""
        if existing:
            existing_block = (
                "Already known facts:\n" + "\n".join(f"- {f}" for f in existing) + "\n\n"
            )

        prompt = _PROMPT.format(existing_block=existing_block, user_message=user_message)
        messages = [{"role": "user", "content": prompt}]
        try:
            message = llm.chat(
                messages, model=config.ROUTER_MODEL, temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Backend may not support response_format — retry plain.
            message = llm.chat(messages, model=config.ROUTER_MODEL, temperature=0)

        raw = message.content or ""
        _obs("verbose", f"Memory extraction raw: {raw[:120]}")
        clean_facts = _clean(_parse_facts(raw))
        if clean_facts:
            settings.append_memories(profile, clean_facts)
            _obs("lite", f"Memories stored: {clean_facts}")
            if on_saved:
                on_saved()
    except Exception as e:
        _obs("lite", f"Memory extraction error: {e}")
