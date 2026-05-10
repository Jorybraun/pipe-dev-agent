# Architecture

## Design Decisions

### Why ephemeral?

Most coding agents try to do everything in one session. They read files, write code, run tests, fix errors, all while context grows. Eventually they hit the context limit and lose everything.

Our approach: **one agent = one context window**. When the window fills up, the agent hands off to a fresh agent with a rich progress report. The new agent starts with full context and all the knowledge from the previous one.

### Scout / Builder split

**Scout** (first agent): Explores the codebase and writes an implementation spec. No code. Max 3 exploration turns.

**Builder** (subsequent agents): Executes the spec. Writes code, runs tests. Max 2 verification turns, then must implement.

This split prevents the common failure mode where an agent reads files endlessly and never writes code.

### Rich handoffs

When an agent exits, it produces a structured handoff document with:
- **Files explored** — so the next agent doesn't re-read
- **Discoveries** — what was learned about patterns, architecture
- **Work completed** — files written, tests added
- **Errors encountered** — what failed and why
- **Test results** — which tests passed/failed
- **Next actions** — concrete steps for the next agent

This is the key insight: the next agent needs to know what was **learned**, not just what was **written**.

## Guardrails

| Guardrail | Trigger | Action |
|---|---|---|
| Exploration budget | 3 reads/greps without writes (scout) or 2 (builder) | Force agent to start implementing |
| Tool loop | Same tool+args 3x in a row | Force handoff |
| Turn cap | 1000 agent→tool cycles | Force handoff |
| Token budget | 120K tokens | Warn agent to wrap up |
| Token limit | 140K tokens | Force handoff |
| Context compaction | 30K chars of old context | Summarize old conversation |
| Wall-clock timeout | 5 minutes | Force handoff |

## Handoff Format

```python
@dataclass
class HandoffPayload:
    status: str                    # "complete", "context_exhausted", "blocked"
    files_touched: list[str]       # all files read/written/edited
    files_written: list[str]       # files actually modified
    state_notes: list[str]         # discoveries, context, blockers
    done: list[dict]               # structured work items
    next_actions: list[str]        # what next agent should do
    context_used: int              # tokens consumed
    errors_encountered: list[str]  # failures and their causes
    tests_run: list[str]          # test results
    typechecks: list[str]         # type check results
    discoveries: list[str]        # what was learned about the codebase
```

## ReAct Loop

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│  Agent  │───▶│  Tools  │───▶│ Compact │───▶│ Budget  │
│  (LLM)  │    │         │    │         │    │ Guard   │
└────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
     │              │              │              │
     └──────────────┘              └──────────────┘
              ▲                           ▲
              │                           │
              └─────── (loop back) ───────┘
```

1. **Agent node**: LLM decides what to do, generates tool calls
2. **Tools node**: Executes tool calls, merges results
3. **Compact node**: Summarizes old context if it's grown large
4. **Budget guard**: Checks token usage, injects warnings
5. **Route**: Back to agent, or to force_handoff, or END

## Context Compaction

When old context exceeds ~30K chars, we:
1. Find the last 2 agent turns (preserve these verbatim)
2. Send everything before that to a summarizer LLM
3. Replace old context with a compact summary
4. Continue the loop

The compaction prompt asks the LLM to preserve:
- Current task state
- Errors and their resolutions
- Final working code (not intermediate attempts)
- Project structure and dependencies
- Design decisions
- Unfinished tasks

## Pluggability

### Model

Default reads from env vars. Override with a factory:

```python
def my_model():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model="gpt-4o", temperature=0.2)

run_developer(task=task, model_factory=my_model)
```

### Handoff backend

Default writes to `.handoffs.jsonl`. Override with a callback:

```python
def my_callback(payload: HandoffPayload) -> dict:
    db.save_handoff(payload)
    return {"handoff_id": str(uuid4())}

run_developer(task=task, handoff_callback=my_callback)
```

### Tools

Default toolkit: file, shell, grep, search. Add your own:

```python
from pipe_dev_agent.tools import ToolRegistry

tools = get_default_tools()
tools.register("deploy", deploy_tool)
tools.register("notify", slack_tool)
```

## File Structure

```
pipe_dev_agent/
├── agent.py          # ReAct loop, graph builder, run_developer()
├── progress.py       # extract_progress() from message history
├── budget.py         # TokenBudget tracking
├── checkpoint.py     # SqliteSaver / MemorySaver wrappers
├── model.py          # default_model_factory() from env vars
├── types.py          # DevState, DevResult, HandoffPayload, etc.
├── prompts/
│   └── developer.md  # System prompt (scout/builder modes)
└── tools/
    ├── __init__.py   # ToolRegistry, get_default_tools()
    ├── file.py       # read_file, write_file, edit_file
    ├── shell.py      # shell commands
    ├── search.py     # grep, search_files
    └── handoff.py    # submit_handoff tool
```
