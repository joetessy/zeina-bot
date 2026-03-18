"""System tools — get_system_health, execute_shell."""
import subprocess
import os
import re
import pathlib
import difflib
import json
import datetime
import platform
import psutil
from .manager import tool_manager


@tool_manager.register(
    name="get_system_health",
    description=(
        "Get a real-time report of the computer's health and performance metrics. "
        "Use for ANY question about: disk/storage space, battery level, CPU usage, "
        "RAM/memory usage, network status, OS info, uptime, or general system health. "
        "NOT for weather or temperature — use get_weather for those."
    ),
    parameters={"type": "object", "properties": {}, "required": []}
)
def get_system_health() -> dict:
    """Gathers high-level system metrics using psutil and system commands."""
    try:
        cpu_usage = psutil.cpu_percent(interval=0.1)
        load_avg = [round(x, 2) for x in psutil.getloadavg()] if hasattr(psutil, "getloadavg") else None
        mem = psutil.virtual_memory()
        usage = psutil.disk_usage('/')
        battery = psutil.sensors_battery()

        try:
            uname_result = subprocess.run(["uname", "-a"], capture_output=True, text=True, timeout=5)
            system_info = uname_result.stdout.strip() if uname_result.returncode == 0 else platform.platform()
        except Exception:
            system_info = platform.platform()

        try:
            pwd_result = subprocess.run(["pwd"], capture_output=True, text=True, timeout=5)
            current_directory = pwd_result.stdout.strip() if pwd_result.returncode == 0 else os.getcwd()
        except Exception:
            current_directory = os.getcwd()

        try:
            uptime_result = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
            uptime_info = uptime_result.stdout.strip() if uptime_result.returncode == 0 else None
        except Exception:
            uptime_info = None

        report = {
            "timestamp": datetime.datetime.now().isoformat(),
            "system": {"os": platform.system(), "platform": system_info, "uptime": uptime_info},
            "current_directory": current_directory,
            "cpu": {"usage_percent": round(cpu_usage, 1), "load_average": load_avg},
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
            "network": "online"
        }
        return json.dumps(report, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to retrieve health data: {str(e)}"})


# ── Shell execution ──────────────────────────────────────────────────────────

def _resolve_app_name(app_name: str) -> str:
    """Find the best-matching installed .app bundle name for a user-supplied string."""
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

    for app in apps:
        if _norm(app) == query_norm:
            return app

    for app in apps:
        app_n = _norm(app)
        if query_norm in app_n or app_n in query_norm:
            return app

    norm_to_real = {_norm(a): a for a in apps}
    matches = difflib.get_close_matches(query_norm, list(norm_to_real.keys()), n=1, cutoff=0.5)
    if matches:
        return norm_to_real[matches[0]]

    return app_name


_SHELL_BLOCKED = [
    "rm -rf", "rm -fr", "sudo rm", "mkfs", "dd if=", ":(){", "> /dev",
    "chmod 777 /", "chown root", "curl | sh", "wget | sh", "curl | bash", "wget | bash",
]


@tool_manager.register(
    name="execute_shell",
    description=(
        "Execute a shell command on the system. Use ONLY when the user gives a DIRECT, "
        "IMPERATIVE command to perform an action RIGHT NOW — e.g. 'open Safari', "
        "'launch Spotify', 'kill Terminal', 'close Finder'. "
        "Requires an imperative verb (open/launch/run/start/kill/close) + specific target. "
        "NOT for questions, hypotheticals, or system metrics (use get_system_health for those)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The macOS/Linux shell command to execute. Rules: "
                    "Open apps: open -a \"AppName\" (always double-quote app names). "
                    "Open URLs: open -a \"Brave Browser\" \"https://url\". "
                    "YouTube search: open -a \"Brave Browser\" \"https://www.youtube.com/results?search_query=query+words\". "
                    "Web search: open -a \"Brave Browser\" \"https://duckduckgo.com/?q=query+words\". "
                    "Default browser is Brave Browser unless user specifies another. "
                    "Always include https:// for URLs. "
                    "Close/kill: pkill -x \"AppName\" or killall \"AppName\"."
                )
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

    open_a_match = re.match(
        r'^open\s+-a\s+([\"\'])(.+?)\1(\s+.+)?\s*$', command, re.IGNORECASE
    )
    if open_a_match:
        raw_app = open_a_match.group(2).strip()
        trailing = (open_a_match.group(3) or "").strip()
        resolved = _resolve_app_name(raw_app)
        if trailing:
            command = f"open -a '{resolved}' {trailing}"
        else:
            command = f"open -a '{resolved}'"

    cmd_lower = command.lower()
    for blocked in _SHELL_BLOCKED:
        if blocked.lower() in cmd_lower:
            return f"Refused: command contains blocked pattern '{blocked}'."

    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and re.match(r'^open\b', command, re.IGNORECASE):
            app_match = re.match(r"open\s+-a\s+['\"]?([^'\"]+)['\"]?", command, re.IGNORECASE)
            app_label = app_match.group(1).strip() if app_match else command
            return f"Launched '{app_label}' successfully."
        output = (result.stdout.strip() or result.stderr.strip() or "(no output)")
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return f"Exit {result.returncode}:\n{output}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Error executing command: {e}"
