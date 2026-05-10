"""Tool registry and default toolkit for developer agents."""
from __future__ import annotations

from typing import Any


class ToolRegistry:
    """Registry for LangChain-compatible tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, name: str, tool: Any) -> None:
        """Register a tool by name."""
        self._tools[name] = tool

    def get(self, name: str) -> Any | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def all(self) -> list[Any]:
        """Return all registered tools as a list."""
        return list(self._tools.values())

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def get_default_tools() -> ToolRegistry:
    """Return the standard developer toolkit.

    Includes: read_file, write_file, edit_file, shell, grep, search_files
    """
    from pipe_dev_agent.tools.file import read_file_tool, write_file_tool, edit_file_tool
    from pipe_dev_agent.tools.shell import shell_tool
    from pipe_dev_agent.tools.search import grep_tool, search_files_tool

    reg = ToolRegistry()
    reg.register("read_file", read_file_tool)
    reg.register("write_file", write_file_tool)
    reg.register("edit_file", edit_file_tool)
    reg.register("shell", shell_tool)
    reg.register("grep", grep_tool)
    reg.register("search_files", search_files_tool)
    return reg
