"""Tool framework — Tool dataclass, ToolManager, and global instance."""
from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass


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
