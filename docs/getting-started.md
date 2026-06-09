# Getting started

A 5-minute walkthrough from `pip install` to seeing a real AI agent blocked from doing something dangerous.

---

## 1. Install (30 seconds)

```bash
pip install lynx-agent
lynx init
```

`init` creates:

```
policy.yaml         # the rules — edit this to match your safety policy
lynx.toml        # runtime config
.lynx/           # local SQLite store + audit log
```

## 2. Write your first tool (1 minute)

```python
# my_agent.py
import asyncio
from lynx import tool, runtime, ToolCall, FinalAnswer, Message

@tool(cost="low", reversible=False, scope=["filesystem:write"])
async def shell(cmd: str) -> str:
    """Run a shell command and return stdout."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return (out + err).decode()
```

That's it. The `@tool` decorator registers the function with Lynx and declares three things the policy engine needs to know:

- **`cost`** — `low | medium | high`. Used for budget caps.
- **`reversible`** — `False` means the action can't be undone. The default policy forces dry-run + approval for these.
- **`scope`** — free-form labels (`filesystem:write`, `db:write`, `net:egress`, `cloud:write`). Policy can match on these.

## 3. Write a scripted "agent" (1 minute)

A real agent would be Claude or GPT (see below). For the walkthrough, a scripted agent shows the loop more clearly:

```python
class DemoAgent:
    """Plays a fixed plan so we can see every verdict."""
    def __init__(self):
        self._i = 0
        self._plan = [
            ToolCall(tool="shell", args={"cmd": "ls /tmp"}, call_id="c1"),
            ToolCall(tool="shell", args={"cmd": "rm -rf /"}, call_id="c2"),  # hallucination
            FinalAnswer(text="all done"),
        ]
    async def step(self, conversation: list[Message]):
        a = self._plan[self._i]
        self._i += 1
        return a

async def main():
    result = await runtime.run(
        DemoAgent(),
        task="demonstrate lynx",
        policy="policy.yaml",
    )
    print(f"Status: {result.status}")
    print(f"Final:  {result.final_answer}")
    print(f"Run ID: {result.run_id}")

asyncio.run(main())
```

## 4. Run it (10 seconds)

```bash
$ python my_agent.py
Status: succeeded
Final:  all done
Run ID: R-01KTQ8VFXZ...
```

## 5. See what happened (30 seconds)

```bash
$ lynx trace R-01KTQ8VFXZ...
#0  shell({"cmd":"ls /tmp"})      → approve_required   (irreversible without shadow)
#1  shell({"cmd":"rm -rf /"})     → deny   (rm -rf / is hard-blocked)
```

The agent proposed `rm -rf /`. **The policy denied it.** The syscall never ran. Claude got `[denied by policy] rm -rf / is hard-blocked` as the tool result and the agent moved on to the final answer.

```bash
$ lynx audit verify R-01KTQ8VFXZ...
✔ audit chain for R-01KTQ8VFXZ... is intact

$ lynx audit export R-01KTQ8VFXZ... > evidence.jsonl
```

That `evidence.jsonl` is the compliance artifact. Hash-chained, content-addressed, tamper-evident.

## 6. Hook up a real LLM (2 minutes)

Swap the scripted agent for a real Claude or GPT:

```python
from lynx.adapters.anthropic_sdk import ClaudeAgent

agent = ClaudeAgent(model="claude-opus-4-7", system="You are a careful sysadmin.")
result = await runtime.run(agent, task="Clean up /tmp/", policy="policy.yaml")
```

Set `ANTHROPIC_API_KEY` in your environment. That's the only change. Now a real LLM proposes the actions, Lynx still gates them.

OpenAI is the same:

```python
from lynx.adapters.openai_sdk import OpenAIAgent
agent = OpenAIAgent(model="gpt-5")
```

LangGraph, CrewAI, and MCP servers also have one-line adapters — see [SDK reference](03-sdk-and-cli.md).

---

## What you just learned

| You wrote | Lynx gave you |
|-----------|-----------------|
| One `@tool` function | Policy enforcement on every call |
| One YAML policy (the default `lynx init` shipped) | Dry-run + deny + approval routing |
| One agent loop | Durable checkpoints + hash-chained audit |
| Zero infrastructure | A SQLite-backed local store + CLI for inspection |

## Where to go next

| You want to… | Read |
|--------------|------|
| Understand the vocabulary | [Concepts](concepts.md) |
| Write your own policy rules | [Policy language](02-policy-language.md) |
| Copy-paste common patterns | [Cookbook](cookbook.md) |
| Know when to use Lynx | [Why Lynx](why-lynx.md) |
| Get unstuck | [FAQ](faq.md) |
| Build your own adapter / shadow / store | [Architecture](../README.md#how-it-works) + [Contributing](../CONTRIBUTING.md) |
