"""Search tools for developer agents."""
from __future__ import annotations

import subprocess
from typing import Any

from langchain_core.tools import tool


@tool
def grep(pattern: str, path: str = ".", glob: str = "*") -> str:
    """Search file contents using ripgrep.

    Args:
        pattern: Regex pattern to search for.
        path: Directory or file to search in (default: current directory).
        glob: File glob pattern to filter by (default: all files).
    """
    try:
        cmd = ["rg", "-n", "--color=never", "-g", glob, pattern, path]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            if len(lines) > 200:
                return "\n".join(lines[:200]) + f"\n... [{len(lines) - 200} more matches]"
            return result.stdout
        if result.returncode == 1:
            return f"No matches for pattern '{pattern}' in {path}"
        return f"Error: {result.stderr}"
    except FileNotFoundError:
        # Fallback to grep if ripgrep not installed
        try:
            cmd = ["grep", "-r", "-n", "--include", glob, pattern, path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                lines = result.stdout.splitlines()
                if len(lines) > 200:
                    return "\n".join(lines[:200]) + f"\n... [{len(lines) - 200} more matches]"
                return result.stdout
            if result.returncode == 1:
                return f"No matches for pattern '{pattern}' in {path}"
            return f"Error: {result.stderr}"
        except Exception as e:
            return f"Error: neither rg nor grep available: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool
def search_files(pattern: str, path: str = ".", file_glob: str = "*") -> str:
    """Find files by name pattern.

    Args:
        pattern: Glob pattern for file names (e.g., '*.py', '*config*').
        path: Directory to search in.
        file_glob: Additional filter for file names.
    """
    try:
        cmd = ["find", path, "-type", "f", "-name", pattern]
        if file_glob != "*":
            # Use find with multiple -name conditions
            pass
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            if len(lines) > 200:
                return "\n".join(lines[:200]) + f"\n... [{len(lines) - 200} more files]"
            return result.stdout
        return f"Error: {result.stderr}"
    except Exception as e:
        return f"Error: {e}"


grep_tool = grep
search_files_tool = search_files
