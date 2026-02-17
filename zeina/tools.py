"""
Tool framework for Zeina AI Assistant
Enables LLM to call external tools like web search, weather, calculator, etc.
"""
import subprocess
import os
import pathlib
import json
import datetime
from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass
import psutil
import platform
import socket

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
