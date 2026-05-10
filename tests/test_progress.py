"""Tests for progress extraction."""
from __future__ import annotations

from langchain_core.messages import ToolMessage

from pipe_dev_agent.progress import extract_progress


def test_extract_write_file():
    msgs = [
        ToolMessage(content="File written successfully to src/test.ts", name="write_file", tool_call_id="1"),
    ]
    result = extract_progress(msgs)
    assert result["files_touched"] == ["src/test.ts"]
    assert result["files_written"] == ["src/test.ts"]
    assert len(result["done_items"]) == 1
    assert result["done_items"][0]["type"] == "file"


def test_extract_edit_file():
    msgs = [
        ToolMessage(content="Successfully replaced text in src/test.ts (1 changes)", name="edit_file", tool_call_id="1"),
    ]
    result = extract_progress(msgs)
    assert result["files_touched"] == ["src/test.ts"]
    assert result["files_written"] == ["src/test.ts"]


def test_extract_grep():
    msgs = [
        ToolMessage(content="Found 3 matches for pattern 'foo'", name="grep", tool_call_id="1"),
    ]
    result = extract_progress(msgs)
    assert len(result["discoveries"]) == 1
    assert "Grep result" in result["discoveries"][0]


def test_extract_tests():
    msgs = [
        ToolMessage(content="Tests: 5 passed, 0 failed", name="run_tests", tool_call_id="1"),
    ]
    result = extract_progress(msgs)
    assert len(result["tests_run"]) == 1
    assert "passed" in result["tests_run"][0]


def test_dedupe():
    msgs = [
        ToolMessage(content="File written successfully to src/a.ts", name="write_file", tool_call_id="1"),
        ToolMessage(content="File written successfully to src/a.ts", name="write_file", tool_call_id="2"),
    ]
    result = extract_progress(msgs)
    assert result["files_touched"] == ["src/a.ts"]  # deduped
    assert len(result["done_items"]) == 2  # but done_items not deduped
