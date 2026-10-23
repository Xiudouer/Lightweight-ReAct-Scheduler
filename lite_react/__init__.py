"""A dependency-free, local-first ReAct scheduler inspired by WeKnora."""

from .core import Agent, AgentConfig, AgentResult
from .ollama import OllamaClient
from .tools import Tool, ToolRegistry, builtin_tools

__version__ = "1.0.0"
__all__ = ["Agent", "AgentConfig", "AgentResult", "OllamaClient", "Tool", "ToolRegistry", "builtin_tools"]
