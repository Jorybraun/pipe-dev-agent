"""Shell tool for developer agents."""
from __future__ import annotations

import subprocess
from typing import Any

from langchain_core.tools import tool

MAX_SHELL_OUTPUT = 32_000


@tool
def shell(commands: str) -> str:
    """Run a shell command in the working directory.

    Args:
        commands: Shell command(s) to execute. Can use pipes, redirects, etc.
    """
    try:
        result = subprocess.run(
            commands,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[Exit code: {result.returncode}]"

        if len(output) > MAX_SHELL_OUTPUT:
            truncated = output[:MAX_SHELL_OUTPUT]
            last_newline = truncated.rfind("\n")
            if last_newline > 0:
                truncated = truncated[:last_newline]
            output = truncated + f"\n... [{len(output) - len(truncated)} more chars]"

        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"
    except Exception as e:
        return f"Error: {e}"


shell_tool = shell
