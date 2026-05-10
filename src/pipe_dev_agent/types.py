"""Core types for pipe-dev-agent."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from langchain_core.messages import BaseMessage
from typing_extensions import Annotated, TypedDict


HandoffStatus = Literal["complete", "context_exhausted", "blocked"]
HandoffTo = Literal["next_dev", "qa_deploy", "supervisor_reroute"]


@dataclass
class HandoffPayload:
    """Structured data passed to the handoff callback when an agent exits."""

    status: HandoffStatus
    files_touched: list[str]
    files_written: list[str]
    state_notes: list[str]
    done: list[dict[str, Any]]
    next_actions: list[str]
    context_used: int
    errors_encountered: list[str]
    tests_run: list[str]
    typechecks: list[str]
    discoveries: list[str]


# Callback types
HandoffCallback = Callable[[HandoffPayload], dict[str, Any]]
HeartbeatCallback = Callable[[], None]
ModelFactory = Callable[[], Any]


class DevState(TypedDict):
    """Internal state of the developer ReAct graph."""

    messages: Annotated[list[BaseMessage], lambda old, new: new]
    task: str
    handoff_in: dict[str, Any] | None
    handoff_count: int  # 0 = first dev (scout), 1+ = subsequent (builder)
    budget_used: int
    budget_warned: bool
    status: str | None  # terminal status when graph ends
    turn_count: int
    recent_tool_calls: list[dict[str, Any]]
    compacted: bool  # compaction runs once per developer
    exploration_turns: int  # turns spent on reads/greps/shell (no writes)


class DevResult(TypedDict):
    """Public result returned by run_developer()."""

    status: HandoffStatus
    messages: list[BaseMessage]
    files_touched: list[str]
    files_written: list[str]
    state_notes: list[str]
    done: list[dict[str, Any]]
    next_actions: list[str]
    handoff: dict[str, Any] | None  # the raw handoff record from the callback
    context_used: int
    turn_count: int
