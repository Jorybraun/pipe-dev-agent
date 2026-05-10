"""File management tools for developer agents."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool


MAX_FILE_READ_BYTES = 64_000
MAX_FILE_WRITE_BYTES = 256_000


@tool
def read_file(file_path: str, line_offset: int = 1, n_lines: int = 500) -> str:
    """Read a file with line numbers and pagination.

    Args:
        file_path: Path to the file (absolute or relative to working_dir).
        line_offset: Line number to start from (1-indexed). Use -N to read last N lines.
        n_lines: Maximum lines to read (default 500, max 2000).
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: no such file {file_path}"
    if not path.is_file():
        return f"Error: not a file {file_path}"

    try:
        content = path.read_text()
    except Exception as e:
        return f"Error: failed to read {file_path}: {e}"

    lines = content.splitlines()

    if line_offset < 0:
        # Read last |line_offset| lines
        start = max(0, len(lines) + line_offset)
        end = len(lines)
    else:
        start = max(0, line_offset - 1)
        end = min(len(lines), start + n_lines)

    selected = lines[start:end]
    result = "\n".join(f"{i + start + 1}|{line}" for i, line in enumerate(selected))

    if len(result) > MAX_FILE_READ_BYTES:
        truncated = result[:MAX_FILE_READ_BYTES]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        result = truncated + f"\n... [{len(result) - len(truncated)} more chars]"

    return result


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        file_path: Path to write to.
        content: Full file content.
    """
    if len(content) > MAX_FILE_WRITE_BYTES:
        return (
            f"Error: content is {len(content)} bytes, exceeds limit {MAX_FILE_WRITE_BYTES}. "
            f"Write in chunks or use edit_file for targeted changes."
        )

    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"File written successfully to {file_path}"
    except Exception as e:
        return f"Error writing to {file_path}: {e}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace old_string with new_string in a file.

    Args:
        file_path: Path to the file.
        old_string: Text to find (must be unique in the file).
        new_string: Replacement text.
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: no such file {file_path}"

    try:
        content = path.read_text()
    except Exception as e:
        return f"Error reading {file_path}: {e}"

    if old_string not in content:
        return f"Error: old_string not found in {file_path}"

    if content.count(old_string) > 1:
        return (
            f"Error: old_string appears {content.count(old_string)} times in {file_path}. "
            f"Must be unique for safe replacement."
        )

    new_content = content.replace(old_string, new_string, 1)

    try:
        path.write_text(new_content)
        return f"Successfully replaced text in {file_path} (1 change)"
    except Exception as e:
        return f"Error writing to {file_path}: {e}"


# Bind tool names for progress extraction
read_file_tool = read_file
write_file_tool = write_file
edit_file_tool = edit_file
