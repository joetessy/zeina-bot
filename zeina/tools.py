"""
Tool framework for Zeina AI Assistant
Enables LLM to call external tools like web search, weather, calculator, etc.
"""
import subprocess
import os
import pathlib
import json
import datetime
import difflib
import re
from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass
import psutil
import platform
import socket

# ── Memory callback (set by assistant on init) ───────────────────────────────
_memory_callback = None


def set_memory_callback(cb) -> None:
    """Register a callback(fact: str) that saves a fact to the active profile."""
    global _memory_callback
    _memory_callback = cb


# ── UI control callback (set by app on init) ──────────────────────────────────
_ui_control_callback = None


def set_ui_control_callback(cb) -> None:
    """Register a callback(action: str, value: str) that controls the app UI."""
    global _ui_control_callback
    _ui_control_callback = cb

@dataclass
class Tool:
    """Represents a tool that the LLM can call"""
    name: str
    description: str
    function: Callable
    parameters: Dict[str, Any]

    def to_ollama_schema(self) -> Dict[str, Any]:
        """Convert tool to Ollama function calling schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

    def execute(self, **kwargs) -> str:
        """Execute the tool with given parameters"""
        try:
            result = self.function(**kwargs)
            return str(result)
        except Exception as e:
            return f"Error executing {self.name}: {str(e)}"


class ToolManager:
    """Manages registration and execution of tools"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: Dict[str, Any]):
        """Decorator to register a tool"""
        def decorator(func: Callable) -> Callable:
            tool = Tool(
                name=name,
                description=description,
                function=func,
                parameters=parameters
            )
            self.tools[name] = tool
            return func
        return decorator

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self.tools.get(name)

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool with given arguments"""
        tool = self.get_tool(name)
        if not tool:
            return f"Error: Tool '{name}' not found"
        return tool.execute(**arguments)

    def get_ollama_tools(self) -> List[Dict[str, Any]]:
        """Get all tools in Ollama function calling format"""
        return [tool.to_ollama_schema() for tool in self.tools.values()]

    def has_tools(self) -> bool:
        """Check if any tools are registered"""
        return len(self.tools) > 0


# Global tool manager instance
tool_manager = ToolManager()


# ============================================================================
# TOOL IMPLEMENTATIONS
# ============================================================================

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
                "description": "The fact to remember about the user, phrased as a short statement"
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


@tool_manager.register(
    name="web_search",
    description="Search the web. ONLY use this tool when the user explicitly asks to search or look something up online, or when the question requires very recent real-time information like today's news, live scores, or current prices. Do NOT use this for general knowledge, greetings, advice, or casual conversation.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query"
            }
        },
        "required": ["query"]
    }
)
def web_search(query: str) -> str:
    """
    Search the web using DuckDuckGo
    Returns a formatted string with search results
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return "Error: ddgs library not installed. Run: pip install ddgs"

    try:
        import logging
        for _noisy in ("ddgs", "curl_cffi", "httpx", "httpcore", "urllib3"):
            logging.getLogger(_noisy).setLevel(logging.ERROR)

        from ddgs.http_client import HttpClient
        HttpClient._impersonates = ("random",)
        results = DDGS().text(query, max_results=5)

        if not results:
            return f"No results found for: {query}"

        # Format results
        formatted = f"Search results for '{query}':\n\n"
        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            snippet = result.get('body', 'No description')
            url = result.get('href', '')

            formatted += f"{i}. {title}\n"
            formatted += f"   {snippet}\n"
            if url:
                formatted += f"   Source: {url}\n"
            formatted += "\n"

        return formatted.strip()

    except Exception as e:
        return f"Error performing web search: {str(e)}"


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
    """Get current date and time"""
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
        # Fallback if pytz not available
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
    """
    Safely evaluate mathematical expressions
    """
    import math
    import re

    # Define safe functions and constants
    safe_dict = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'pow': pow,
        # Math functions
        'sqrt': math.sqrt,
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'asin': math.asin,
        'acos': math.acos,
        'atan': math.atan,
        'log': math.log,
        'log10': math.log10,
        'exp': math.exp,
        'floor': math.floor,
        'ceil': math.ceil,
        # Constants
        'pi': math.pi,
        'e': math.e,
    }

    # Clean the expression (remove any potentially dangerous characters)
    # Only allow numbers, operators, parentheses, dots, and function names
    if not re.match(r'^[0-9+\-*/().,\s\w]+$', expression):
        return "Error: Invalid characters in expression"

    # Prevent dangerous operations
    dangerous = ['__', 'import', 'exec', 'eval', 'compile', 'open', 'file']
    if any(d in expression.lower() for d in dangerous):
        return "Error: Unsafe expression"

    try:
        # Evaluate the expression
        result = eval(expression, {"__builtins__": {}}, safe_dict)
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error calculating '{expression}': {str(e)}"


@tool_manager.register(
    name="get_weather",
    description="Get current weather for a location. Use this when the user asks about the weather, temperature, or forecast for a city or place.",
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name (e.g., 'London', 'New York', 'Tokyo')"
            }
        },
        "required": ["location"]
    }
)
def get_weather(location: str) -> str:
    """
    Get current weather using OpenWeatherMap API (free tier).
    Requires OPENWEATHERMAP_API_KEY environment variable.
    """
    import os

    api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
    if not api_key:
        return "Error: OPENWEATHERMAP_API_KEY environment variable not set. Get a free key at https://openweathermap.org/api"

    try:
        import requests
    except ImportError:
        return "Error: requests library not installed. Run: pip install requests"

    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": location,
            "appid": api_key,
            "units": "metric"
        }
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 404:
            return f"Could not find weather data for '{location}'. Please check the city name."
        elif response.status_code == 401:
            return "Invalid API key. Please check your OPENWEATHERMAP_API_KEY."

        response.raise_for_status()
        data = response.json()

        city = data.get("name", location)
        country = data.get("sys", {}).get("country", "")
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        humidity = data["main"]["humidity"]
        description = data["weather"][0]["description"]
        wind_speed = data["wind"]["speed"]

        result = f"Weather in {city}, {country}:\n"
        result += f"  Conditions: {description}\n"
        result += f"  Temperature: {temp:.1f}°C (feels like {feels_like:.1f}°C)\n"
        result += f"  Humidity: {humidity}%\n"
        result += f"  Wind: {wind_speed} m/s"

        return result

    except requests.exceptions.Timeout:
        return f"Weather request timed out for '{location}'. Please try again."
    except requests.exceptions.RequestException as e:
        return f"Error fetching weather for '{location}': {str(e)}"
    except (KeyError, IndexError) as e:
        return f"Error parsing weather data for '{location}': {str(e)}"


@tool_manager.register(
    name="get_location",
    description="Get the user's current location based on their IP address. Use this ONLY when the user asks where they are or their current location.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def get_location() -> str:
    """Get approximate location using IP-based geolocation."""
    try:
        import requests
    except ImportError:
        return "Error: requests library not installed. Run: pip install requests"

    try:
        response = requests.get("https://ipinfo.io/json", timeout=10)
        response.raise_for_status()
        data = response.json()

        city = data.get("city", "Unknown")
        region = data.get("region", "Unknown")
        country = data.get("country", "Unknown")
        loc = data.get("loc", "Unknown")

        result = f"Current location (approximate, based on IP):\n"
        result += f"  City: {city}\n"
        result += f"  Region: {region}\n"
        result += f"  Country: {country}\n"
        result += f"  Coordinates: {loc}"
        return result

    except Exception as e:
        return f"Error getting location: {str(e)}"


# ── File system tools ─────────────────────────────────────────────────────────

def _get_safe_roots():
    """Return allowed root paths (lazy so config is fully loaded)."""
    from zeina import config as _cfg
    return [pathlib.Path.home(), pathlib.Path(_cfg.PROJECT_ROOT)]


_MAX_FILE_SIZE = 10_000  # 10 KB


def _safe_path(raw: str):
    """Resolve path and verify it is within an allowed root. Returns Path or None."""
    p = pathlib.Path(raw).expanduser().resolve()
    for root in _get_safe_roots():
        if p == root or root in p.parents:
            return p
    return None


@tool_manager.register(
    name="read_file",
    description="Read the contents of a file. Only works for files inside the home directory or project folder.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or ~ path to the file to read"
            }
        },
        "required": ["path"]
    }
)
def read_file(path: str) -> str:
    """Read and return file contents (up to 10 KB)."""
    p = _safe_path(path)
    if p is None:
        return "Path is outside allowed directories (home or project root)."
    if not p.exists():
        return f"File not found: {path}"
    if not p.is_file():
        return f"Not a file: {path}"
    if p.stat().st_size > _MAX_FILE_SIZE:
        return "File too large to read (> 10 KB)."
    return p.read_text(errors="replace")


_MAX_DIR_ENTRIES = 100


@tool_manager.register(
    name="list_directory",
    description="List files and folders in a directory. Defaults to the home directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list (defaults to ~)"
            }
        },
        "required": []
    }
)
def list_directory(path: str = "~") -> str:
    """List directory contents, dirs first. Caps at 100 entries."""
    p = _safe_path(path or "~")
    if p is None:
        return "Path is outside allowed directories (home or project root)."
    if not p.exists():
        return f"Directory not found: {path}"
    if not p.is_dir():
        return f"Not a directory: {path}"
    try:
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        lines = [f"{'[DIR] ' if e.is_dir() else '      '}{e.name}" for e in entries[:_MAX_DIR_ENTRIES]]
        if len(entries) > _MAX_DIR_ENTRIES:
            lines.append(f"... ({len(entries) - _MAX_DIR_ENTRIES} more entries not shown)")
        return "\n".join(lines) or "Empty directory."
    except PermissionError:
        return f"Permission denied: {path}"

@tool_manager.register(
    name="get_system_health",
    description="Get a real-time report of the computer's health, including CPU, memory, disk, battery, working directory, and system information.",
    parameters={"type": "object", "properties": {}}
)
def get_system_health() -> dict:
    """Gathers high-level system metrics using psutil and system commands."""
    try:
        import json
        
        # CPU
        cpu_usage = psutil.cpu_percent(interval=0.1)
        load_avg = [round(x, 2) for x in psutil.getloadavg()] if hasattr(psutil, "getloadavg") else None
        
        # Memory
        mem = psutil.virtual_memory()
        
        # Storage (Root filesystem)
        usage = psutil.disk_usage('/')
        
        # Battery
        battery = psutil.sensors_battery()
        
        # System information
        try:
            uname_result = subprocess.run(["uname", "-a"], capture_output=True, text=True, timeout=5)
            system_info = uname_result.stdout.strip() if uname_result.returncode == 0 else platform.platform()
        except:
            system_info = platform.platform()
        
        # Current working directory
        try:
            pwd_result = subprocess.run(["pwd"], capture_output=True, text=True, timeout=5)
            current_directory = pwd_result.stdout.strip() if pwd_result.returncode == 0 else os.getcwd()
        except:
            current_directory = os.getcwd()
        
        # System uptime (if available)
        try:
            uptime_result = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
            uptime_info = uptime_result.stdout.strip() if uptime_result.returncode == 0 else None
        except:
            uptime_info = None
        
        # Network connectivity (basic check)
        network_status = "online"  # Assume online unless we can detect otherwise
        
        # Build structured report
        report = {
            "timestamp": datetime.datetime.now().isoformat(),
            "system": {
                "os": platform.system(),
                "platform": system_info,
                "uptime": uptime_info
            },
            "current_directory": current_directory,
            "cpu": {
                "usage_percent": round(cpu_usage, 1),
                "load_average": load_avg
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "used_percent": round(mem.percent, 1)
            },
            "storage": {
                "total_gb": round(usage.total / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "used_percent": round(usage.percent, 1)
            },
            "battery": {
                "percent": round(battery.percent, 1) if battery else None,
                "power_plugged": battery.power_plugged if battery else None
            } if battery else None,
            "network": network_status
        }
        
        # Return as JSON string for clean parsing by LLM
        return json.dumps(report, indent=2)
        
    except Exception as e:
        return json.dumps({"error": f"Failed to retrieve health data: {str(e)}"})


# ── Shell execution tool ──────────────────────────────────────────────────────

def _resolve_app_name(app_name: str) -> str:
    """Find the best-matching installed .app bundle name for a user-supplied string.

    Scans /Applications and ~/Applications, normalises both the query and each
    candidate (lowercase, strip spaces/hyphens/underscores/dots), then tries:
      1. Exact normalised match
      2. One string contains the other
      3. difflib close match (cutoff 0.5)
    Returns the original string unchanged if no good match is found.
    """
    search_dirs = [
        pathlib.Path("/Applications"),
        pathlib.Path("/System/Applications"),
        pathlib.Path("/System/Applications/Utilities"),
        pathlib.Path.home() / "Applications",
    ]
    apps: list[str] = []
    for d in search_dirs:
        if d.is_dir():
            try:
                for entry in d.iterdir():
                    if entry.suffix == ".app":
                        apps.append(entry.stem)
            except PermissionError:
                continue

    if not apps:
        return app_name

    def _norm(s: str) -> str:
        return re.sub(r'[\s\-_.]', '', s).lower()

    query_norm = _norm(app_name)

    # 1. Exact normalised match
    for app in apps:
        if _norm(app) == query_norm:
            return app

    # 2. One contains the other (normalised)
    for app in apps:
        app_n = _norm(app)
        if query_norm in app_n or app_n in query_norm:
            return app

    # 3. difflib fuzzy match on normalised names
    norm_to_real = {_norm(a): a for a in apps}
    matches = difflib.get_close_matches(query_norm, list(norm_to_real.keys()), n=1, cutoff=0.5)
    if matches:
        return norm_to_real[matches[0]]

    return app_name


# Commands containing these patterns are always refused.
_SHELL_BLOCKED = [
    "rm -rf", "rm -fr", "sudo rm", "mkfs", "dd if=", ":(){", "> /dev",
    "chmod 777 /", "chown root", "curl | sh", "wget | sh", "curl | bash", "wget | bash",
]


@tool_manager.register(
    name="execute_shell",
    description=(
        "Execute a shell command on the system. Use for opening apps, running scripts, "
        "listing processes, or performing system tasks the user requests."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute (e.g. 'open -a Calculator', 'ls -la ~')"
            }
        },
        "required": ["command"]
    }
)
def execute_shell(command: str) -> str:
    """Execute a shell command after safety checks."""
    command = command.strip()
    if not command:
        return "No command provided."

    # Resolve app name for 'open -a "AppName" [url]' commands.
    # Handles both: open -a "AppName"  and  open -a "AppName" "https://..."
    open_a_match = re.match(
        r'^open\s+-a\s+([\"\'])(.+?)\1(\s+.+)?\s*$', command, re.IGNORECASE
    )
    if open_a_match:
        raw_app  = open_a_match.group(2).strip()
        trailing = (open_a_match.group(3) or "").strip()
        resolved = _resolve_app_name(raw_app)
        if trailing:
            command = f"open -a '{resolved}' {trailing}"
        else:
            command = f"open -a '{resolved}'"

    # Block obviously dangerous patterns
    cmd_lower = command.lower()
    for blocked in _SHELL_BLOCKED:
        if blocked.lower() in cmd_lower:
            return f"Refused: command contains blocked pattern '{blocked}'."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # 'open' always exits 0 with no output on success; give the LLM a clear
        # signal so it doesn't hallucinate "already running" or "not found".
        if result.returncode == 0 and re.match(r'^open\b', command, re.IGNORECASE):
            app_match = re.match(r"open\s+-a\s+['\"]?([^'\"]+)['\"]?", command, re.IGNORECASE)
            app_label = app_match.group(1).strip() if app_match else command
            return f"Launched '{app_label}' successfully."
        output = (result.stdout.strip() or result.stderr.strip() or "(no output)")
        # Truncate very long output so LLM doesn't get flooded
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return f"Exit {result.returncode}:\n{output}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Error executing command: {e}"


# ── Clipboard tools ──────────────────────────────────────────────────────────

@tool_manager.register(
    name="read_clipboard",
    description="Read the current contents of the system clipboard.",
    parameters={"type": "object", "properties": {}, "required": []}
)
def read_clipboard() -> str:
    """Read text from the system clipboard."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            return result.stdout or "(clipboard is empty)"
        elif system == "Linux":
            for cmd in [["xclip", "-selection", "clipboard", "-o"],
                        ["xsel", "--clipboard", "--output"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return result.stdout or "(clipboard is empty)"
                except FileNotFoundError:
                    continue
            return "Error: install xclip or xsel to use clipboard on Linux (sudo apt install xclip)."
        else:
            return "Clipboard reading is not supported on this platform."
    except Exception as e:
        return f"Error reading clipboard: {e}"


@tool_manager.register(
    name="write_clipboard",
    description="Write text to the system clipboard so the user can paste it elsewhere.",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text to copy to the clipboard"
            }
        },
        "required": ["content"]
    }
)
def write_clipboard(content: str) -> str:
    """Write text to the system clipboard."""
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(
                ["pbcopy"], input=content, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                preview = content[:60] + "..." if len(content) > 60 else content
                return f"Copied to clipboard: {preview}"
            return f"Error copying to clipboard: {result.stderr}"
        elif system == "Linux":
            for cmd in [["xclip", "-selection", "clipboard"],
                        ["xsel", "--clipboard", "--input"]]:
                try:
                    result = subprocess.run(
                        cmd, input=content, capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        preview = content[:60] + "..." if len(content) > 60 else content
                        return f"Copied to clipboard: {preview}"
                except FileNotFoundError:
                    continue
            return "Error: install xclip or xsel to use clipboard on Linux (sudo apt install xclip)."
        else:
            return "Clipboard writing is not supported on this platform."
    except Exception as e:
        return f"Error writing to clipboard: {e}"


# ── Screenshot / vision tool ──────────────────────────────────────────────────

@tool_manager.register(
    name="take_screenshot",
    description="Capture the current screen for visual analysis.",
    parameters={"type": "object", "properties": {}, "required": []},
)
def take_screenshot() -> str:
    """Capture the full desktop, save to data/tmp/, return the file path."""
    import sys
    from datetime import datetime as _dt
    from zeina import config as _cfg
    path = os.path.join(_cfg.TMP_DIR, f"screenshot_{_dt.now().strftime('%Y%m%d_%H%M%S')}.png")
    os.makedirs(_cfg.TMP_DIR, exist_ok=True)

    if sys.platform == "darwin":
        # On macOS, mss only captures the Kivy app surface via SDL2.
        # Use the native screencapture command to get the full desktop.
        import subprocess
        result = subprocess.run(
            ["screencapture", "-x", "-t", "png", path],
            capture_output=True,
        )
        if result.returncode != 0 or not os.path.exists(path):
            return f"Error: screencapture failed — {result.stderr.decode().strip()}"
    else:
        try:
            import mss
            import mss.tools
        except ImportError:
            return "Error: mss library not installed. Run: pip install mss"
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            mss.tools.to_png(shot.rgb, shot.size, output=path)

    return path


# ── Self-control tool ─────────────────────────────────────────────────────────

@tool_manager.register(
    name="control_self",
    description=(
        "Control the app's own UI and settings. Use when the user asks to: "
        "switch color theme, change face animation style, toggle voice/chat mode, "
        "show/hide the status bar or chat feed, show/hide the menu button, "
        "mute/unmute TTS speech, clear conversation history, clear stored memories, "
        "change the bot name or user name, switch profile, "
        "or open the settings or diagnostics page."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "set_theme", "set_animation", "set_mode",
                    "set_status_bar", "set_chat_feed", "set_tts_mute",
                    "clear_history", "clear_memories",
                    "set_bot_name", "set_user_name",
                    "open_settings", "open_diagnostics",
                    "switch_profile", "set_menu_button",
                ],
                "description": "The UI action to perform",
            },
            "value": {
                "type": "string",
                "description": (
                    "The value for the action. "
                    "set_theme: default|midnight|terminal|sunset. "
                    "set_animation: vector|ascii. "
                    "set_mode: voice|chat. "
                    "set_status_bar / set_chat_feed / set_menu_button: show|hide. "
                    "set_tts_mute: mute|unmute. "
                    "set_bot_name / set_user_name: the new name. "
                    "switch_profile: the profile name. "
                    "Other actions: leave empty."
                ),
            },
        },
        "required": ["action"],
    },
)
def control_self(action: str, value: str = "") -> str:
    """Invoke the registered UI control callback to change app state."""
    if _ui_control_callback:
        try:
            return _ui_control_callback(action, value or "")
        except Exception as e:
            return f"UI control error: {e}"
    return "UI control not available in this mode."
