# pipe-dev-agent

Ephemeral developer agent. One task, one context window, then handoff.

## What it does

- Takes a **task description** (e.g., "Add user authentication to this FastAPI app")
- Explores the codebase (reads files, greps, shells)
- Writes code (creates/edits files)
- Runs checks (tests, type checks, lint)
- When context runs low, **hands off** to the next agent with a rich progress report

## Why

Most coding agents die because they:
1. Read the same files repeatedly
2. Get stuck in tool loops
3. Run out of context and lose all progress

This agent solves that by:
- **Hard exploration budget** (3 turns max for scouts, 2 for builders)
- **Tool loop detection** (same call 3x → force handoff)
- **Context compaction** (summarizes old conversation when it gets large)
- **Rich handoffs** (next agent gets files explored, discoveries, errors, test results — not just files written)

## Install

```bash
pip install pipe-dev-agent
```

With browser tools:
```bash
pip install pipe-dev-agent[playwright]
```

## Quick Start

```python
from pipe_dev_agent import run_developer
from pipe_dev_agent.tools import get_default_tools

# Define the task
task = """
Add JWT authentication to this FastAPI app.
- Use python-jose for JWT handling
- Add /login and /register endpoints
- Protect /api/* routes with a dependency
"""

# Get the default toolkit (file, shell, grep)
tools = get_default_tools()

# Run the agent
result = run_developer(
    task=task,
    tools=tools,
    working_dir="/path/to/your/project",
)

# Check what happened
print("Status:", result["status"])  # "complete", "context_exhausted", "blocked"
print("Files touched:", result.get("files_touched", []))
print("Handoff notes:", result.get("state_notes", []))
```

## Handoffs

When the agent runs out of context (or hits a loop), it doesn't just die. It produces a **handoff document** with:

- **Files explored** — what was read (so next agent doesn't re-read)
- **Discoveries** — what was learned about the codebase
- **Work completed** — files written, tests added
- **Errors encountered** — what failed and why
- **Test results** — which tests passed/failed
- **Next actions** — what the next agent should do

Pass the handoff to the next agent:

```python
result1 = run_developer(task=task, tools=tools)

result2 = run_developer(
    task=task,
    tools=tools,
    handoff_in=result1["handoff"],  # continue where agent 1 left off
    handoff_count=1,  # this is the 2nd agent on this task
)
```

## Configuration

### Model

By default uses Kimi (Moonshot AI). Configure via env vars:

```bash
export OPENAI_API_KEY="sk-..."      # or KIMI_API_KEY
export DEV_MODEL="gpt-4o"            # or kimi-k2-6, claude-sonnet-4, etc.
export DEV_BASE_URL="https://api.openai.com/v1"  # optional
export DEV_TEMPERATURE="0.2"
export DEV_MAX_TOKENS="8192"
```

Or pass a model factory:

```python
from langchain_openai import ChatOpenAI

def my_model():
    return ChatOpenAI(model="gpt-4o", temperature=0.2)

result = run_developer(task=task, tools=tools, model_factory=my_model)
```

### Custom Handoff Backend

By default handoffs are written to a local JSON file. Plug in your own:

```python
def my_handoff_callback(payload):
    # Save to your database, queue, etc.
    print(f"Agent finished with status: {payload.status}")
    print(f"Files touched: {payload.files_touched}")
    return {"handoff_id": "abc-123"}

result = run_developer(task=task, tools=tools, handoff_callback=my_handoff_callback)
```

### Custom Tools

Add your own tools to the registry:

```python
from pipe_dev_agent.tools import ToolRegistry
from langchain_core.tools import tool

@tool
def deploy_to_staging():
    """Deploy current branch to staging environment."""
    ...

tools = get_default_tools()
tools.register("deploy", deploy_to_staging)

result = run_developer(task=task, tools=tools)
```

## Architecture

```
┌─────────────┐     ┌──────────┐     ┌─────────┐
│   Agent     │────▶│  Tools   │────▶│  Files  │
│  (LLM)      │     │(file,    │     │  / Shell│
│             │◀────│ shell,   │◀────│  / Code │
└─────────────┘     │ browser) │     └─────────┘
     │              └──────────┘
     ▼
┌─────────────┐
│  Handoff    │
│  (progress  │
│   report)   │
└─────────────┘
```

The agent runs in a **ReAct loop**:
1. LLM decides what to do (read file, run test, write code)
2. Tool executes
3. Result goes back to LLM
4. Repeat until task complete or context exhausted

**Guardrails:**
- Max 1000 turns per agent
- Max 3 exploration turns (read/grep/shell without writes)
- Context compaction at ~30K chars
- Token budget warnings at 120K, force handoff at 140K

## License

MIT
