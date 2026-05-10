# Examples

## Basic Usage

```python
from pipe_dev_agent import run_developer
from pipe_dev_agent.tools import get_default_tools

tools = get_default_tools()

result = run_developer(
    task="Add a /health endpoint to this FastAPI app",
    tools=tools,
    working_dir="./my-project",
)

print(f"Status: {result['status']}")
print(f"Files touched: {result['files_touched']}")
print(f"Turns: {result['turn_count']}")
```

## Multi-Agent Chain

When context runs out, hand off to a fresh agent:

```python
# First agent explores and writes some code
result1 = run_developer(
    task="Implement user authentication",
    tools=tools,
    working_dir="./my-project",
)

if result1['status'] == 'context_exhausted':
    # Second agent continues with full context
    result2 = run_developer(
        task="Implement user authentication",
        tools=tools,
        working_dir="./my-project",
        handoff_in=result1['handoff'],
        handoff_count=1,
    )
```

## Custom Model

Use any OpenAI-compatible API:

```python
from langchain_openai import ChatOpenAI

def my_model():
    return ChatOpenAI(
        model="claude-sonnet-4",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-...",
        temperature=0.2,
    )

result = run_developer(
    task="Fix the bug in src/main.py",
    tools=tools,
    model_factory=my_model,
)
```

## Custom Handoff Backend

Save handoffs to your database:

```python
from pipe_dev_agent.types import HandoffPayload

def db_handoff_callback(payload: HandoffPayload) -> dict:
    handoff_id = db.handoffs.insert({
        'status': payload.status,
        'files_touched': payload.files_touched,
        'state_notes': payload.state_notes,
        'done': payload.done,
        'next_actions': payload.next_actions,
        'context_used': payload.context_used,
        'created_at': datetime.now(),
    })
    return {'handoff_id': handoff_id}

result = run_developer(
    task="Refactor the database layer",
    tools=tools,
    handoff_callback=db_handoff_callback,
)
```

## Custom Tools

Add deployment, notifications, etc.:

```python
from langchain_core.tools import tool
from pipe_dev_agent.tools import ToolRegistry

@tool
def deploy_to_staging(branch: str) -> str:
    """Deploy a git branch to the staging environment."""
    import subprocess
    result = subprocess.run(
        ['git', 'push', 'origin', branch],
        capture_output=True, text=True
    )
    return result.stdout

@tool
def notify_slack(message: str) -> str:
    """Send a message to the team's Slack channel."""
    import requests
    requests.post(SLACK_WEBHOOK, json={'text': message})
    return "Message sent"

tools = get_default_tools()
tools.register("deploy", deploy_to_staging)
tools.register("notify", notify_slack)

result = run_developer(
    task="Fix the login bug and deploy to staging",
    tools=tools,
)
```

## With Playwright (Browser Tools)

```bash
pip install pipe-dev-agent[playwright]
playwright install
```

```python
from pipe_dev_agent.tools import get_default_tools
from langchain_community.tools.playwright import NavigateTool, ClickTool

tools = get_default_tools()
tools.register("navigate", NavigateTool())
tools.register("click", ClickTool())

result = run_developer(
    task="Test the login flow by navigating to /login, filling the form, and clicking submit",
    tools=tools,
)
```

## Heartbeat for Long-Running Tasks

```python
import time

def heartbeat():
    print(f"[{time.strftime('%H:%M:%S')}] Agent still working...")

result = run_developer(
    task="Run the full test suite and fix any failures",
    tools=tools,
    heartbeat_callback=heartbeat,
)
```

## Checkpoint Persistence

Resume after a crash:

```python
from pipe_dev_agent.checkpoint import get_checkpointer

checkpointer = get_checkpointer("./checkpoints.db")

result = run_developer(
    task="Implement the payment gateway",
    tools=tools,
    thread_id="payment-task-001",
    checkpointer=checkpointer,
)

# Later, if the process crashes, resume with the same thread_id:
result2 = run_developer(
    task="Implement the payment gateway",
    tools=tools,
    thread_id="payment-task-001",
    checkpointer=checkpointer,
)
```
