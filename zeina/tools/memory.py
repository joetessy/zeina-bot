"""Remember tool — saves user facts to long-term memory."""
from .manager import tool_manager

_memory_callback = None


def set_memory_callback(cb) -> None:
    """Register a callback(fact: str) that saves a fact to the active profile."""
    global _memory_callback
    _memory_callback = cb


@tool_manager.register(
    name="remember",
    description=(
        "Save a specific fact about the user to long-term memory. "
        "Use ONLY when the user explicitly says 'remember that...', 'don't forget...', "
        "or shares personal info they clearly want recalled in future conversations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": (
                    "The fact to remember, phrased as a short statement without a subject. "
                    "Example: 'likes pizza' not 'The user likes pizza'."
                )
            }
        },
        "required": ["fact"]
    }
)
def remember_fact(fact: str) -> str:
    """Save a fact about the user to the active profile's memory file."""
    fact = fact.strip()
    if not fact:
        return "Nothing to remember — fact was empty."
    if _memory_callback:
        try:
            _memory_callback(fact)
        except Exception as e:
            return f"Couldn't save memory: {e}"
    return f"Got it, I'll remember: {fact}"
