"""Ephemeral developer agent — one task, then handoff.

This is the core ReAct loop. It:
1. Runs an LLM agent node (decides what to do)
2. Executes tools (file, shell, etc.)
3. Compacts context when it gets large
4. Tracks budget and forces handoff when exhausted
5. Produces a rich handoff document for the next agent
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from pipe_dev_agent.budget import FORCE_THRESHOLD
from pipe_dev_agent.checkpoint import get_ephemeral_checkpointer
from pipe_dev_agent.model import default_model_factory, default_summarizer_factory
from pipe_dev_agent.progress import extract_progress
from pipe_dev_agent.tools.handoff import make_handoff_tool
from pipe_dev_agent.tools import ToolRegistry
from pipe_dev_agent.types import (
    DevResult,
    DevState,
    HandoffCallback,
    HandoffPayload,
    HeartbeatCallback,
    ModelFactory,
)

MAX_TURNS_PER_DEV = 1000
DUPLICATE_TOOL_WINDOW = 5
PRUNE_KEEP_TURNS = 2
PRUNE_THRESHOLD_CHARS = 2_000
COMPACT_THRESHOLD_CHARS = 20_000
MAX_DEV_RUNTIME_SECONDS = 5 * 60


def _load_prompt() -> str:
    """Load the developer system prompt from the bundled prompts directory."""
    path = Path(__file__).parent / "prompts" / "developer.md"
    if path.exists():
        return path.read_text()
    return "# Developer Agent\nImplement the task and submit a Handoff."


def _build_system_message(
    state: DevState,
    working_dir: str | None = None,
) -> SystemMessage:
    """Build the system message with mode, context, and task."""
    base = _load_prompt()
    task = state.get("task", "")
    handoff = state.get("handoff_in")
    handoff_count = state.get("handoff_count", 0)
    exploration_turns = state.get("exploration_turns", 0)
    turn_count = state.get("turn_count", 0)

    mode = "BUILDER" if handoff_count > 0 else "SCOUT"

    parts = [base]
    parts.append(
        f"\n## Context\n"
        f"turn_count: {turn_count} / {MAX_TURNS_PER_DEV}\n"
        f"exploration_turns: {exploration_turns} / 3 (MAX)\n"
        f"MODE: {mode}\n"
        f"handoff_count: {handoff_count} (0 = scout, 1+ = builder)\n"
    )

    if working_dir:
        parts.append(f"working_dir: {working_dir}\n")

    if task:
        parts.append(f"\n## Task\n{task}")
    if handoff:
        parts.append(f"\n## Previous Handoff\n{json.dumps(handoff, indent=2, default=str)}")

    return SystemMessage(content="\n".join(parts))


def _hash_tool_call(tc: dict[str, Any]) -> str:
    """Stable hash for duplicate detection."""
    args = tc.get("args", tc.get("arguments", {}))
    return f"{tc.get('name')}:{json.dumps(args, sort_keys=True, default=str)}"


def _detect_tool_loop(recent: list[dict[str, Any]]) -> tuple[bool, str]:
    """Detect if the same tool+args has been called repeatedly."""
    if len(recent) < 3:
        return False, ""
    hashes = [_hash_tool_call(tc) for tc in recent]
    if len(hashes) >= 3 and hashes[-1] == hashes[-2] == hashes[-3]:
        return True, f"Tool loop detected: {hashes[-1]} called 3x in a row"
    from collections import Counter

    counts = Counter(hashes)
    most_common, count = counts.most_common(1)[0]
    if count >= 4 and len(hashes) >= DUPLICATE_TOOL_WINDOW:
        return True, f"Tool loop detected: {most_common} called {count}x in last {len(hashes)} turns"
    return False, ""


def _is_exploration_tool_call(tc: dict[str, Any]) -> bool:
    """Check if a tool call is exploratory (read/grep/shell) vs productive (write/edit)."""
    name = tc.get("name", "")
    return name in ("read_file", "grep", "search_files", "shell")


# ── Rolling Tool Output Pruning ────────────────────────────────────────────


def _prune_old_tool_results(
    messages: list[BaseMessage],
    keep_turns: int = PRUNE_KEEP_TURNS,
    prune_threshold: int = PRUNE_THRESHOLD_CHARS,
) -> list[BaseMessage]:
    """Replace old large ToolMessages with compact summaries.

    Keeps all messages from the last `keep_turns` agent turns untouched.
    """
    ai_indices = [
        i
        for i, m in enumerate(messages)
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
    ]

    if len(ai_indices) <= keep_turns:
        return messages

    cutoff_index = ai_indices[-keep_turns]

    result: list[BaseMessage] = []
    for i, msg in enumerate(messages):
        if i >= cutoff_index:
            result.append(msg)
            continue

        if (
            isinstance(msg, ToolMessage)
            and isinstance(msg.content, str)
            and len(msg.content) > prune_threshold
        ):
            name = msg.name or "unknown"
            if name == "submit_handoff":
                result.append(msg)
                continue

            preview = msg.content[:200].replace("\n", " ")
            summary = (
                f"[Earlier {name} result pruned — {len(msg.content)} chars. "
                f"Preview: {preview}...]"
            )
            result.append(
                ToolMessage(
                    content=summary,
                    tool_call_id=msg.tool_call_id,
                    name=name,
                )
            )
        else:
            result.append(msg)

    return result


# ── Agent Node ────────────────────────────────────────────────────────────


def _make_agent_node(
    model_factory: ModelFactory,
    tools: ToolRegistry,
):
    """Create the agent node function bound to a model and tools."""

    def agent_node(state: DevState, config: RunnableConfig) -> dict[str, Any]:
        """Call the LLM with the current message history."""
        model = model_factory()
        messages = list(state["messages"])
        handoff_count = state.get("handoff_count", 0)
        exploration_turns = state.get("exploration_turns", 0)
        working_dir = config.get("configurable", {}).get("working_dir")

        # Ensure system message is first
        if not messages or not isinstance(messages[0], SystemMessage):
            sys_msg = _build_system_message(state, working_dir)
            messages = [sys_msg] + messages

        # Scout/builder exploration enforcement
        if handoff_count == 0 and exploration_turns >= 3:
            messages = messages + [
                SystemMessage(
                    content="EXPLORATION BUDGET EXHAUSTED (3/3 turns used). "
                    "You are a SCOUT. Stop reading files immediately. "
                    "Write your implementation spec NOW and submit a handoff. "
                    "DO NOT call any more read_file, grep, or shell tools."
                )
            ]
        elif handoff_count > 0 and exploration_turns >= 2:
            messages = messages + [
                SystemMessage(
                    content="EXPLORATION BUDGET EXHAUSTED (2/2 turns used). "
                    "You are a BUILDER. Stop verifying and START IMPLEMENTING. "
                    "DO NOT call any more read_file, grep, or shell tools. "
                    "Write code, run tests, and submit your handoff."
                )
            ]

        # Token-aware trim: keep last ~120K tokens
        messages = trim_messages(
            messages,
            max_tokens=120000,
            token_counter="approximate",
            strategy="last",
            include_system=True,
        )

        # Bind tools
        model_with_tools = model.bind_tools(tools.all())
        response = model_with_tools.invoke(messages, config)

        # Count exploration turns
        new_exploration_turns = exploration_turns
        if isinstance(response, AIMessage) and response.tool_calls:
            if all(_is_exploration_tool_call(tc) for tc in response.tool_calls):
                new_exploration_turns = exploration_turns + 1

        return {
            "messages": messages + [response],
            "turn_count": state.get("turn_count", 0) + 1,
            "exploration_turns": new_exploration_turns,
        }

    return agent_node


# ── Budget Guard Node ─────────────────────────────────────────────────────


def budget_guard_node(state: DevState) -> dict[str, Any]:
    """Check token budget after an agent turn and hard-trim message state."""
    used = state.get("budget_used", 0)
    warned = state.get("budget_warned", False)

    # Count only the latest AIMessage's input tokens
    turn_tokens = 0
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage):
            meta = msg.usage_metadata or {}
            turn_tokens += meta.get("input_tokens", 0) or meta.get("prompt_tokens", 0)
            break
        elif isinstance(msg.content, str):
            turn_tokens += len(msg.content) // 4

    used += turn_tokens

    messages = list(state["messages"])
    updates: dict[str, Any] = {"budget_used": used, "messages": messages}

    if used >= FORCE_THRESHOLD and not warned:
        updates["budget_warned"] = True
        messages = messages + [
            SystemMessage(
                content=f"TOKEN WARNING: {used} / {FORCE_THRESHOLD} tokens used. "
                f"Start wrapping up and prepare your Handoff."
            )
        ]
        updates["messages"] = messages
    elif used >= FORCE_THRESHOLD:
        messages = messages + [
            SystemMessage(
                content=f"TOKEN LIMIT REACHED: {used} / {FORCE_THRESHOLD} tokens. "
                f"You MUST exit now via submit_handoff with status=context_exhausted."
            )
        ]
        updates["messages"] = messages
        updates["status"] = "context_exhausted"

    # Token-aware trim
    updates["messages"] = trim_messages(
        updates["messages"],
        max_tokens=120000,
        token_counter="approximate",
        strategy="last",
        include_system=True,
    )

    return updates


# ── Routing ───────────────────────────────────────────────────────────────


def should_continue(state: DevState) -> Literal["tools", "agent", "force_handoff", "__end__"]:
    """Route after the agent node."""
    last = state["messages"][-1]

    # If the last message is a tool result for submit_handoff, we're done
    if isinstance(last, ToolMessage) and last.name == "submit_handoff":
        return END

    # Hard turn cap
    turn_count = state.get("turn_count", 0)
    if turn_count >= MAX_TURNS_PER_DEV:
        return "force_handoff"

    # Duplicate tool call loop detection
    recent = state.get("recent_tool_calls", [])
    is_loop, _ = _detect_tool_loop(recent)
    if is_loop:
        return "force_handoff"

    # Budget exhausted
    if state.get("status") == "context_exhausted":
        if isinstance(last, ToolMessage) and last.name == "submit_handoff":
            return END
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "force_handoff"

    # Normal ReAct routing
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"

    return END


# ── Tools Node ────────────────────────────────────────────────────────────


def _make_tools_node(tools: ToolRegistry):
    """Create the tools node function bound to a tool registry."""

    def tools_node(state: DevState) -> dict[str, Any]:
        """Execute tool calls and merge results into the full message list."""
        tools_by_name = {t.name: t for t in tools.all()}
        messages = list(state.get("messages", []))
        recent = list(state.get("recent_tool_calls", []))

        # Find the last AIMessage with tool_calls
        last_ai = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                last_ai = msg
                break

        if last_ai:
            for tc in last_ai.tool_calls:
                tool_name = tc.get("name")
                tool = tools_by_name.get(tool_name)
                if tool:
                    try:
                        result = tool.invoke(tc)
                    except Exception as exc:
                        result = ToolMessage(
                            content=f"Error: {exc}",
                            name=tool_name,
                            tool_call_id=tc.get("id", ""),
                        )
                    messages.append(result)
                    recent.append({
                        "name": tool_name,
                        "args": tc.get("args", tc.get("arguments", {})),
                    })
                else:
                    messages.append(ToolMessage(
                        content=f"Error: tool '{tool_name}' not found",
                        name=tool_name,
                        tool_call_id=tc.get("id", ""),
                    ))

        recent = recent[-DUPLICATE_TOOL_WINDOW:]
        return {"messages": messages, "recent_tool_calls": recent}

    return tools_node


# ── Compaction Node ───────────────────────────────────────────────────────


def compact_node(state: DevState) -> dict[str, Any]:
    """Compact old messages using a summarizer LLM call.

    Runs ONCE per developer when context has grown large.
    Preserves the last 2 agent turns verbatim.
    """
    messages = list(state.get("messages", []))

    if state.get("compacted"):
        return {"messages": messages}

    ai_indices = [
        i
        for i, m in enumerate(messages)
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)
    ]
    if len(ai_indices) <= 2:
        return {"messages": messages}

    cutoff = ai_indices[-2]
    to_compact = messages[:cutoff]
    to_preserve = messages[cutoff:]

    total_old_chars = sum(
        len(m.content) if isinstance(m.content, str) else 0
        for m in to_compact
    )
    if total_old_chars < 30_000:
        return {"messages": messages}

    # Build compaction prompt
    parts = [
        "The following is a list of messages in an agent conversation. "
        "Compact this conversation context according to the priorities and rules below.",
        "",
        "**Compression Priorities (in order):**",
        "1. Current Task State: What is being worked on RIGHT NOW",
        "2. Errors & Solutions: All encountered errors and their resolutions",
        "3. Code Evolution: Final working versions only (remove intermediate attempts)",
        "4. System Context: Project structure, dependencies, environment setup",
        "5. Design Decisions: Architectural choices and their rationale",
        "6. TODO Items: Unfinished tasks and known issues",
        "",
        "**Compression Rules:**",
        "- MUST KEEP: Error messages, stack traces, working solutions, current task",
        "- MERGE: Similar discussions into single summary points",
        "- REMOVE: Redundant explanations, failed attempts (keep lessons learned), verbose comments",
        "- CONDENSE: Long code blocks → keep signatures + key logic only",
        "",
        "**Required Output Structure:**",
        "<current_focus>[What we're working on now]</current_focus>",
        "<completed_tasks>- [Task]: [Brief outcome]</completed_tasks>",
        "<active_issues>- [Issue]: [Status/Next steps]</active_issues>",
        "<important_context>[Any crucial information not covered above]</important_context>",
        "",
        "--- Messages to compact ---",
        "",
    ]

    for i, msg in enumerate(to_compact):
        role = type(msg).__name__.replace("Message", "").lower()
        if isinstance(msg, ToolMessage):
            name = msg.name or "unknown"
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 2000:
                content = content[:2000] + f"\n... [{len(content) - 2000} more chars]"
            parts.append(f"## Message {i + 1}\nRole: {role} (tool={name})\nContent:\n{content}\n")
        elif isinstance(msg.content, str):
            content = msg.content
            if len(content) > 2000:
                content = content[:2000] + f"\n... [{len(content) - 2000} more chars]"
            parts.append(f"## Message {i + 1}\nRole: {role}\nContent:\n{content}\n")
        else:
            parts.append(f"## Message {i + 1}\nRole: {role}\nContent: {str(msg.content)[:2000]}\n")

    try:
        summarizer = default_summarizer_factory()
        summary_response = summarizer.invoke([
            SystemMessage(content="You are a helpful assistant that compacts conversation context."),
            HumanMessage(content="\n".join(parts)),
        ])
    except Exception:
        return {"messages": _prune_old_tool_results(messages)}

    summary_text = (
        summary_response.content
        if isinstance(summary_response.content, str)
        else str(summary_response.content)
    )

    compacted: list[BaseMessage] = [
        SystemMessage(
            content="Previous context has been compacted. Here is the compaction output:\n\n"
            + summary_text
        )
    ]
    compacted.extend(to_preserve)

    return {"messages": compacted, "compacted": True}


# ── Force Handoff Node ──────────────────────────────────────────────────────


def _make_force_handoff_node(
    handoff_callback: HandoffCallback | None = None,
):
    """Create the force handoff node bound to a callback."""

    def force_handoff_node(state: DevState) -> dict[str, Any]:
        """Programmatically submit a handoff when the agent failed to do so."""
        handoff_count = state.get("handoff_count", 0)
        mode = "SCOUT" if handoff_count == 0 else "BUILDER"
        exploration_turns = state.get("exploration_turns", 0)
        turn_count = state.get("turn_count", 0)

        progress = extract_progress(state.get("messages", []))

        files_touched = progress["files_touched"]
        files_written = progress["files_written"]
        done_items = progress["done_items"]
        discoveries = progress["discoveries"]
        errors_encountered = progress["errors_encountered"]
        tests_run = progress["tests_run"]
        typechecks = progress["typechecks"]

        # Build rich state_notes
        state_notes: list[str] = []

        state_notes.append(
            f"## Session Summary\n"
            f"Mode: {mode}, Turns: {turn_count}, Exploration turns: {exploration_turns}\n"
            f"Files read: {len(files_touched)}, Files written: {len(files_written)}\n"
            f"Tests run: {len(tests_run)}, Type checks: {len(typechecks)}\n"
            f"Errors encountered: {len(errors_encountered)}"
        )

        if discoveries:
            state_notes.append("## Discoveries\n" + "\n".join(f"- {d}" for d in discoveries[-10:]))

        if files_touched:
            state_notes.append(
                "## Files Explored\n" +
                "\n".join(f"- {f}" for f in files_touched[-15:])
            )

        if done_items:
            state_notes.append(
                "## Work Completed\n" +
                "\n".join(
                    f"- {item.get('type', 'work')}: {item.get('path', 'unknown')} — {item.get('summary', '')}"
                    for item in done_items[-10:]
                )
            )

        if errors_encountered:
            state_notes.append(
                "## Errors Encountered\n" +
                "\n".join(f"- {e}" for e in errors_encountered[-5:])
            )

        if tests_run:
            state_notes.append(
                "## Test Results\n" +
                "\n".join(f"- {t}" for t in tests_run[-5:])
            )

        if typechecks:
            state_notes.append(
                "## Type Check Results\n" +
                "\n".join(f"- {t}" for t in typechecks[-3:])
            )

        # Build next_actions
        next_actions: list[str] = []

        if files_written and not tests_run:
            next_actions.append(f"Run tests for: {', '.join(files_written[-3:])}")

        if errors_encountered:
            next_actions.append("Fix errors encountered in previous session")

        if mode == "SCOUT" and files_touched and not files_written:
            next_actions.append("Implement based on discovered patterns (see Files Explored above)")
            next_actions.append("Write failing test first, then implement")

        if any("issues" in t or "FAIL" in t for t in typechecks):
            next_actions.append("Fix type check errors")

        if not next_actions:
            next_actions.append("Continue implementation from where previous developer left off")
            next_actions.append("Check state_notes above for context on what was discovered")

        payload = HandoffPayload(
            status="context_exhausted",
            files_touched=files_touched,
            files_written=files_written,
            state_notes=state_notes,
            done=done_items,
            next_actions=next_actions,
            context_used=state.get("budget_used", 0),
            errors_encountered=errors_encountered,
            tests_run=tests_run,
            typechecks=typechecks,
            discoveries=discoveries,
        )

        if handoff_callback:
            record = handoff_callback(payload)
        else:
            from pipe_dev_agent.tools.handoff import _write_local_handoff
            record = _write_local_handoff(payload)

        existing = list(state.get("messages", []))
        return {
            "messages": existing + [
                ToolMessage(
                    content=json.dumps({
                        "submitted": record,
                        "forced": True,
                        "mode": mode,
                        "progress_summary": {
                            "files_touched": len(files_touched),
                            "files_written": len(files_written),
                            "discoveries": len(discoveries),
                            "errors": len(errors_encountered),
                            "tests_run": len(tests_run),
                            "next_actions": len(next_actions),
                        }
                    }, indent=2),
                    name="submit_handoff",
                    tool_call_id="forced-handoff",
                )
            ],
            "status": "context_exhausted",
        }

    return force_handoff_node


# ── Graph Builder ─────────────────────────────────────────────────────────


def build_developer_graph(
    tools: ToolRegistry,
    model_factory: ModelFactory | None = None,
    handoff_callback: HandoffCallback | None = None,
    checkpointer: Any | None = None,
):
    """Build and compile the ephemeral developer ReAct graph."""
    model_factory = model_factory or default_model_factory

    agent_node = _make_agent_node(model_factory, tools)
    tools_node = _make_tools_node(tools)
    force_handoff = _make_force_handoff_node(handoff_callback)

    builder = StateGraph(DevState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)
    builder.add_node("compact", compact_node)
    builder.add_node("budget_guard", budget_guard_node)
    builder.add_node("force_handoff", force_handoff)

    builder.set_entry_point("agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "agent": "agent", "force_handoff": "force_handoff", END: END},
    )
    builder.add_edge("tools", "compact")
    builder.add_edge("compact", "budget_guard")
    builder.add_edge("budget_guard", "agent")
    builder.add_edge("force_handoff", END)

    return builder.compile(checkpointer=checkpointer)


# ── Public API ────────────────────────────────────────────────────────────


def run_developer(
    task: str,
    tools: ToolRegistry | None = None,
    handoff_in: dict[str, Any] | None = None,
    handoff_count: int = 0,
    working_dir: str | None = None,
    model_factory: ModelFactory | None = None,
    handoff_callback: HandoffCallback | None = None,
    heartbeat_callback: HeartbeatCallback | None = None,
    thread_id: str | None = None,
    checkpointer: Any | None = None,
) -> DevResult:
    """Run a single ephemeral developer to completion on one task.

    Args:
        task: The task description for this developer.
        tools: ToolRegistry with available tools. Defaults to get_default_tools().
        handoff_in: Previous handoff document (for builders continuing work).
        handoff_count: 0 = scout, 1+ = builder.
        working_dir: Working directory for file operations.
        model_factory: Factory function returning a ChatModel. Defaults to OpenAI/Kimi from env.
        handoff_callback: Callback for handoff events. Defaults to local JSON file.
        heartbeat_callback: Optional callback called every turn to signal liveness.
        thread_id: LangGraph thread ID for resumability.
        checkpointer: LangGraph checkpointer. Defaults to in-memory.

    Returns:
        DevResult with status, messages, files touched, and handoff record.
    """
    import time

    tools = tools or _default_tools_with_handoff(handoff_callback)

    cp = checkpointer or get_ephemeral_checkpointer()
    graph = build_developer_graph(
        tools=tools,
        model_factory=model_factory,
        handoff_callback=handoff_callback,
        checkpointer=cp,
    )

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id or str(uuid.uuid4()),
            "working_dir": working_dir,
        }
    }

    initial_state: DevState = {
        "messages": [],
        "task": task,
        "handoff_in": handoff_in,
        "handoff_count": handoff_count,
        "budget_used": 0,
        "budget_warned": False,
        "status": None,
        "turn_count": 0,
        "recent_tool_calls": [],
        "compacted": False,
        "exploration_turns": 0,
    }

    start_time = time.time()
    final_state: DevState | None = None

    for event in graph.stream(initial_state, config, stream_mode="values"):
        final_state = event
        if heartbeat_callback:
            heartbeat_callback()
        # Wall-clock safety valve
        if time.time() - start_time >= MAX_DEV_RUNTIME_SECONDS:
            break

    assert final_state is not None

    # Extract final progress
    progress = extract_progress(final_state.get("messages", []))

    # Find the handoff record
    handoff_record = None
    for msg in reversed(final_state.get("messages", [])):
        if isinstance(msg, ToolMessage) and msg.name == "submit_handoff":
            try:
                data = json.loads(msg.content)
                handoff_record = data.get("submitted")
            except (json.JSONDecodeError, AttributeError):
                pass
            break

    return {
        "status": final_state.get("status") or "complete",
        "messages": final_state.get("messages", []),
        "files_touched": progress["files_touched"],
        "files_written": progress["files_written"],
        "state_notes": progress["discoveries"],
        "done": progress["done_items"],
        "next_actions": [],  # populated from handoff_record if available
        "handoff": handoff_record,
        "context_used": final_state.get("budget_used", 0),
        "turn_count": final_state.get("turn_count", 0),
    }


def _default_tools_with_handoff(handoff_callback: HandoffCallback | None = None) -> ToolRegistry:
    """Get default tools plus a submit_handoff tool."""
    from pipe_dev_agent.tools import get_default_tools
    from pipe_dev_agent.tools.handoff import make_handoff_tool

    tools = get_default_tools()
    tools.register("submit_handoff", make_handoff_tool(handoff_callback))
    return tools
