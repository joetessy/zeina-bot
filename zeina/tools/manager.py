"""Tool framework — Tool dataclass, ToolManager, and global instance."""
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Tool:
    """Represents a tool that the LLM can call"""
    name: str
    description: str
    function: Callable[..., Any]
    parameters: Dict[str, Any]

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert tool to the OpenAI function-calling schema (used by any
        OpenAI-compatible backend: llama.cpp, Ollama, etc.)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

    def execute(self, **kwargs: Any) -> str:
        """Execute the tool with given parameters"""
        try:
            result = self.function(**kwargs)
            return str(result)
        except Exception as e:
            return f"Error executing {self.name}: {str(e)}"


class ToolManager:
    """Manages registration and execution of tools"""

    def __init__(self) -> None:
        self.tools: Dict[str, Tool] = {}

    def register(
        self, name: str, description: str, parameters: Dict[str, Any]
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator to register a tool"""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
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

    def get_tool_schemas(self, exclude: Collection[str] = ()) -> List[Dict[str, Any]]:
        """Get all tools in OpenAI function-calling format, minus ``exclude``."""
        return [
            tool.to_openai_schema()
            for name, tool in self.tools.items()
            if name not in exclude
        ]

    def has_tools(self) -> bool:
        """Check if any tools are registered"""
        return len(self.tools) > 0


# Global tool manager instance
tool_manager = ToolManager()
