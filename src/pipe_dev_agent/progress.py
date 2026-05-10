"""Progress extraction from message history.

When a developer agent exits (context exhausted, loop detected, etc.),
we need to capture everything it learned — not just what it wrote.
This module extracts comprehensive progress from the message history.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def extract_progress(messages: list[BaseMessage]) -> dict[str, Any]:
    """Extract comprehensive progress from message history.

    Returns a dict with:
    - files_touched: all files read, written, or edited
    - files_written: files that were actually modified
    - discoveries: things learned (patterns, errors, architecture)
    - done_items: structured work completed
    - errors_encountered: errors and failures
    - tests_run: test results
    - typechecks: type check results
    - exploration_log: what was searched/read
    """
    files_touched: list[str] = []
    files_written: list[str] = []
    done_items: list[dict[str, Any]] = []
    discoveries: list[str] = []
    errors_encountered: list[str] = []
    tests_run: list[str] = []
    typechecks: list[str] = []
    exploration_log: list[str] = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = str(msg.content)
        name = msg.name or ""

        if name == "write_file":
            m = re.search(
                r"(?:written successfully to|Successfully wrote to|wrote to)\s+(.+?)(?:\n|$|\[WARNING)",
                content,
                re.IGNORECASE,
            )
            if m:
                path = m.group(1).strip().rstrip(".").strip()
                files_touched.append(path)
                files_written.append(path)
                done_items.append({"type": "file", "path": path, "summary": "File written"})
            else:
                m = re.search(r"([\w\-/]+\.[\w]+)", content)
                if m:
                    path = m.group(1)
                    files_touched.append(path)
                    files_written.append(path)
                    done_items.append({"type": "file", "path": path, "summary": "File written"})

        elif name == "edit_file":
            m = re.search(r"Successfully replaced text in\s+(.+?)\s*\(", content)
            if m:
                path = m.group(1).strip()
                files_touched.append(path)
                files_written.append(path)
                done_items.append({"type": "file", "path": path, "summary": "File edited"})

        elif name == "read_file":
            # Extract the file path from read results
            m = re.search(r"(?:Error: no such file|Error: not a file|Error: failed to read)\s+(.+)", content)
            if m:
                path = m.group(1).strip()
                files_touched.append(path)
                errors_encountered.append(f"Failed to read {path}")
            else:
                # Look back at the AIMessage that triggered this read
                for prev_msg in messages:
                    if isinstance(prev_msg, AIMessage) and prev_msg.tool_calls:
                        for tc in prev_msg.tool_calls:
                            if tc.get("name") == "read_file":
                                args = tc.get("args", tc.get("arguments", {}))
                                path = args.get("file_path", "")
                                if path and path not in files_touched:
                                    files_touched.append(path)
                                    exploration_log.append(f"Read {path}")

        elif name == "grep":
            if "matches" in content.lower() or "found" in content.lower():
                discoveries.append(f"Grep result: {content[:200]}")
            exploration_log.append(f"Grep: {content[:150]}")

        elif name == "search_files":
            exploration_log.append(f"Search: {content[:150]}")

        elif name == "shell":
            for line in content.splitlines():
                if line.startswith("git add "):
                    path = line.split()[-1]
                    if "." in path and path not in files_touched:
                        files_touched.append(path)
                if "error" in line.lower() or "fail" in line.lower():
                    errors_encountered.append(line[:200])
                if "passed" in line.lower() or "pass" in line.lower():
                    tests_run.append(line[:200])

        elif name == "run_tests":
            if "passed" in content.lower():
                tests_run.append(f"Tests passed: {content[:300]}")
            elif "failed" in content.lower():
                tests_run.append(f"Tests FAILED: {content[:300]}")
                errors_encountered.append(f"Test failure: {content[:300]}")
            else:
                tests_run.append(f"Tests: {content[:300]}")

        elif name == "check_types":
            if "passed" in content.lower() or "no errors" in content.lower():
                typechecks.append("Type check passed")
            else:
                typechecks.append(f"Type check issues: {content[:300]}")

        elif name == "submit_handoff":
            # Previous handoff in the chain — extract its content
            try:
                data = json.loads(content)
                submitted = data.get("submitted", {})
                if submitted:
                    prev_done = submitted.get("done", [])
                    for item in prev_done:
                        if isinstance(item, dict) and item not in done_items:
                            done_items.append(item)
                    prev_notes = submitted.get("state_notes", [])
                    for note in prev_notes:
                        if note not in discoveries:
                            discoveries.append(note)
                    prev_files = submitted.get("files_touched", [])
                    for f in prev_files:
                        if f not in files_touched:
                            files_touched.append(f)
            except (json.JSONDecodeError, AttributeError):
                pass

    # Deduplicate while preserving order
    def dedupe(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in lst:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    return {
        "files_touched": dedupe(files_touched),
        "files_written": dedupe(files_written),
        "discoveries": dedupe(discoveries),
        "done_items": done_items,
        "errors_encountered": dedupe(errors_encountered),
        "tests_run": dedupe(tests_run),
        "typechecks": dedupe(typechecks),
        "exploration_log": dedupe(exploration_log),
    }
