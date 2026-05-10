# API Reference

## `run_developer()`

Main entry point. Runs a single ephemeral developer to completion.

```python
from pipe_dev_agent import run_developer

result = run_developer(
    task="Add JWT auth to this FastAPI app",
    tools=get_default_tools(),
    handoff_in=None,
    handoff_count=0,
    working_dir="/path/to/project",
    model_factory=None,
    handoff_callback=None,
    heartbeat_callback=None,
    thread_id=None,
    checkpointer=None,
)
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `task` | `str` | required | The task description for this developer |
| `tools` | `ToolRegistry` | `get_default_tools()` | Available tools |
| `handoff_in` | `dict \| None` | `None` | Previous handoff document (for builders) |
| `handoff_count` | `int` | `0` | 0 = scout, 1+ = builder |
| `working_dir` | `str \| None` | `None` | Working directory for file operations |
| `model_factory` | `Callable \| None` | `default_model_factory` | Factory returning a ChatModel |
| `handoff_callback` | `Callable \| None` | local JSON | Callback for handoff events |
| `heartbeat_callback` | `Callable \| None` | `None` | Called every turn to signal liveness |
| `thread_id` | `str \| None` | auto | LangGraph thread ID for resumability |
| `checkpointer` | `Any \| None` | `MemorySaver` | LangGraph checkpointer |

### Returns

`DevResult` dict:

```python
{
    "status": "complete",           # or "context_exhausted", "blocked"
    "messages": [...],              # full message history
    "files_touched": ["src/a.py"],  # all files read/written/edited
    "files_written": ["src/a.py"],  # files actually modified
    "state_notes": [...],           # discoveries from message history
    "done": [{"type": "file", "path": "src/a.py", "summary": "..."}],
    "next_actions": [...],          # suggested next steps
    "handoff": {...},               # raw handoff record from callback
    "context_used": 50000,          # tokens consumed
    "turn_count": 12,               # agent turns executed
}
```

## `ToolRegistry`

Register and manage tools.

```python
from pipe_dev_agent.tools import ToolRegistry, get_default_tools

# Start with defaults
tools = get_default_tools()

# Add custom tool
tools.register("deploy", deploy_tool)

# Check if tool exists
assert "deploy" in tools

# Get all tools (for binding to LLM)
all_tools = tools.all()

# Get specific tool
deploy = tools.get("deploy")
```

## `HandoffPayload`

Dataclass passed to handoff callbacks.

```python
from pipe_dev_agent.types import HandoffPayload

@dataclass
class HandoffPayload:
    status: str                    # "complete", "context_exhausted", "blocked"
    files_touched: list[str]
    files_written: list[str]
    state_notes: list[str]
    done: list[dict]
    next_actions: list[str]
    context_used: int
    errors_encountered: list[str]
    tests_run: list[str]
    typechecks: list[str]
    discoveries: list[str]
```

## `extract_progress()`

Extract comprehensive progress from message history. Used internally by `force_handoff_node`, but exposed for testing/customization.

```python
from pipe_dev_agent.progress import extract_progress
from langchain_core.messages import ToolMessage

messages = [
    ToolMessage(content="File written to src/test.py", name="write_file", tool_call_id="1"),
]

progress = extract_progress(messages)
# {
#     "files_touched": ["src/test.py"],
#     "files_written": ["src/test.py"],
#     "discoveries": [],
#     "done_items": [{"type": "file", "path": "src/test.py", "summary": "File written"}],
#     "errors_encountered": [],
#     "tests_run": [],
#     "typechecks": [],
#     "exploration_log": [],
# }
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` or `KIMI_API_KEY` | required | API key for LLM |
| `DEV_MODEL` | `gpt-4o` | Model name |
| `DEV_BASE_URL` | OpenAI default | API base URL |
| `DEV_TEMPERATURE` | `0.2` | Sampling temperature |
| `DEV_MAX_TOKENS` | `8192` | Max tokens per response |
| `SUMMARIZER_MODEL` | same as `DEV_MODEL` | Model for context compaction |
| `SUMMARIZER_TEMPERATURE` | `0.1` | Temperature for compaction |
| `SUMMARIZER_MAX_TOKENS` | `4096` | Max tokens for compaction |

## Default Tools

### `read_file(file_path, line_offset=1, n_lines=500)`

Read a file with line numbers. Use `line_offset=-N` to read last N lines.

### `write_file(file_path, content)`

Write content to a file. Creates parent directories. Max 256KB.

### `edit_file(file_path, old_string, new_string)`

Replace `old_string` with `new_string`. Must be unique in file.

### `shell(commands)`

Run shell command. Output capped at 32KB. 120s timeout.

### `grep(pattern, path=".", glob="*")`

Search file contents with ripgrep (falls back to grep).

### `search_files(pattern, path=".", file_glob="*")`

Find files by name pattern.

### `submit_handoff(status, state_notes, files_touched, done, next_actions, handoff_to)`

Signal completion/context exhaustion. Calls the handoff callback.
