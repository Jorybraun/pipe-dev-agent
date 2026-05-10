"""Handoff tool for developer agents.

This is a thin wrapper that calls the user's handoff_callback.
The agent calls this tool to signal completion / context exhaustion / blockage.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from pipe_dev_agent.types import HandoffPayload


def make_handoff_tool(callback: Any | None = None) -> Any:
    """Create a submit_handoff tool bound to a callback.

    If no callback is provided, handoffs are written to a local JSON file.
    """

    @tool
    def submit_handoff(
        status: str,
        state_notes: list[str] | None = None,
        files_touched: list[str] | None = None,
        done: list[dict] | None = None,
        next_actions: list[str] | None = None,
        handoff_to: str = "next_dev",
    ) -> str:
        """Submit a handoff to pass work to the next agent.

        Args:
            status: One of "complete", "context_exhausted", "blocked".
            state_notes: What the next agent needs to know.
            files_touched: Files that were read, written, or edited.
            done: Structured list of completed work items.
            next_actions: Concrete next steps for the next agent.
            handoff_to: Where to route next (default: "next_dev").
        """
        payload = HandoffPayload(
            status=status,  # type: ignore[arg-type]
            files_touched=files_touched or [],
            files_written=[],  # populated by progress extractor
            state_notes=state_notes or [],
            done=done or [],
            next_actions=next_actions or [],
            context_used=0,
            errors_encountered=[],
            tests_run=[],
            typechecks=[],
            discoveries=[],
        )

        if callback:
            record = callback(payload)
        else:
            record = _write_local_handoff(payload)

        return json.dumps({"submitted": record, "status": status})

    return submit_handoff


def _write_local_handoff(payload: HandoffPayload) -> dict[str, Any]:
    """Default handoff backend: write to local JSON file."""
    import time
    import uuid
    from pathlib import Path

    handoff_id = f"handoff-{uuid.uuid4().hex[:8]}"
    record = {
        "handoff_id": handoff_id,
        "status": payload.status,
        "files_touched": payload.files_touched,
        "state_notes": payload.state_notes,
        "done": payload.done,
        "next_actions": payload.next_actions,
        "created_at": time.time(),
    }

    path = Path(".handoffs.jsonl")
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")

    return record
