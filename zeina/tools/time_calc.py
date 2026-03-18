"""Time and calculator tools."""
from .manager import tool_manager


@tool_manager.register(
    name="get_current_time",
    description="Get the current date and time. Use this when the user asks what time it is or what day it is.",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "Optional timezone (e.g., 'America/New_York'). Defaults to local time.",
                "default": "local"
            }
        },
        "required": []
    }
)
def get_current_time(timezone: str = "local") -> str:
    """Get current date and time."""
    try:
        from datetime import datetime
        import pytz

        if timezone == "local":
            now = datetime.now()
            return f"Current local time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"
        else:
            tz = pytz.timezone(timezone)
            now = datetime.now(tz)
            return f"Current time in {timezone}: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"

    except Exception as e:
        from datetime import datetime
        now = datetime.now()
        return f"Current local time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"


@tool_manager.register(
    name="calculate",
    description="Perform mathematical calculations. Supports basic arithmetic, trigonometry, and common math functions.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate (e.g., '2 + 2', 'sqrt(16)', 'sin(pi/2)')"
            }
        },
        "required": ["expression"]
    }
)
def calculate(expression: str) -> str:
    """Safely evaluate mathematical expressions."""
    import math
    import re

    safe_dict = {
        'abs': abs, 'round': round, 'min': min, 'max': max, 'sum': sum, 'pow': pow,
        'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
        'asin': math.asin, 'acos': math.acos, 'atan': math.atan,
        'log': math.log, 'log10': math.log10, 'exp': math.exp,
        'floor': math.floor, 'ceil': math.ceil,
        'pi': math.pi, 'e': math.e,
    }

    if not re.match(r'^[0-9+\-*/().,\s\w]+$', expression):
        return "Error: Invalid characters in expression"

    dangerous = ['__', 'import', 'exec', 'eval', 'compile', 'open', 'file']
    if any(d in expression.lower() for d in dangerous):
        return "Error: Unsafe expression"

    try:
        result = eval(expression, {"__builtins__": {}}, safe_dict)
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error calculating '{expression}': {str(e)}"
