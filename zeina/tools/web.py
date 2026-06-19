"""Web tools — web_search, get_weather, get_location."""
import os
import logging
from .manager import tool_manager
from zeina import config

# Quiet the noisy HTTP libraries the search backends pull in.
for _noisy in ("ddgs", "curl_cffi", "httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)


def _format_results(query: str, items: list[dict]) -> str:
    """Render a list of {title, body, url} dicts into a compact text block."""
    if not items:
        return f"No results found for: {query}"
    out = f"Search results for '{query}':\n\n"
    for i, r in enumerate(items, 1):
        out += f"{i}. {r.get('title') or 'No title'}\n   {r.get('body') or 'No description'}\n"
        if r.get("url"):
            out += f"   Source: {r['url']}\n"
        out += "\n"
    return out.strip()


def _searxng_search(query: str, base_url: str, max_results: int = 5) -> list[dict]:
    """Query a self-hosted SearXNG instance's JSON API."""
    import requests

    base = base_url.rstrip("/")
    url = base if base.endswith("/search") else f"{base}/search"
    resp = requests.get(
        url,
        params={"q": query, "format": "json"},
        headers={"User-Agent": "Zeina/1.0"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": r.get("title"), "body": r.get("content"), "url": r.get("url")}
        for r in data.get("results", [])[:max_results]
    ]


def _ddgs_search(query: str, max_results: int = 5) -> list[dict]:
    """Query DuckDuckGo via the ddgs library (no API key, no extra service)."""
    from ddgs import DDGS

    results = DDGS().text(query, max_results=max_results)
    return [
        {"title": r.get("title"), "body": r.get("body"), "url": r.get("href")}
        for r in results
    ]


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
    """Search the web.

    Uses a self-hosted SearXNG instance when ``ZEINA_SEARXNG_URL`` is configured
    (private, no rate limits), otherwise DuckDuckGo via ddgs. If SearXNG is set
    but unreachable, falls back to ddgs so search keeps working.
    """
    searxng = getattr(config, "SEARXNG_URL", "")
    if searxng:
        try:
            return _format_results(query, _searxng_search(query, searxng))
        except Exception as e:
            # Don't fail the turn — fall back to the zero-dependency backend.
            pass

    try:
        return _format_results(query, _ddgs_search(query))
    except ImportError:
        return "Error: ddgs library not installed. Run: pip install ddgs"
    except Exception as e:
        return f"Error performing web search: {str(e)}"


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
    """Get current weather using OpenWeatherMap API (free tier)."""
    api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
    if not api_key:
        return "Error: OPENWEATHERMAP_API_KEY environment variable not set. Get a free key at https://openweathermap.org/api"

    try:
        import requests
    except ImportError:
        return "Error: requests library not installed. Run: pip install requests"

    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": location, "appid": api_key, "units": "metric"}
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

    except Exception as e:
        return f"Error fetching weather for '{location}': {str(e)}"


@tool_manager.register(
    name="get_location",
    description="Get the user's current location based on their IP address. Use this ONLY when the user asks where they are or their current location.",
    parameters={"type": "object", "properties": {}, "required": []}
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
