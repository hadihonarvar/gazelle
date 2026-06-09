# examples/

Runnable demos. Each one is self-contained: a Python script + a YAML policy.

| Demo | What it shows |
|------|--------------|
| **`hello_agent.py`** | Minimal scripted agent. The smallest end-to-end loop that exercises the runtime. Use this if you want to see "what's the API shape?" |
| **`file_janitor.py`** + `janitor-policy.yaml` | Real filesystem demo: an agent tidies a workspace. Shows all four common verdicts — **allow** (reads), **deny** (writes outside workspace, hard `rm -rf /`), **dry_run** (writes inside workspace). Real files get deleted. No LLM needed. |
| **`claude_janitor.py`** | Same demo but driven by a real Claude agent via `ANTHROPIC_API_KEY`. Use this to see a real LLM proposing actions and getting blocked. |
| **`openai_janitor.py`** | Same as above but with OpenAI's GPT. Set `OPENAI_API_KEY`. |
| **`refund_agent.py`** + `refund-policy.yaml` | Customer support refund agent. Showcases **approve_required** (medium refunds need supervisor), **deny** (fraud watchlist + amounts over cap), and the audit log as compliance evidence. |
| **`fastapi_server.py`** | Drop-in FastAPI integration. POST /agent/run runs the agent; GET /agent/runs/{id} inspects; POST /agent/approvals/{id} resumes after approval. |

## How to run them

```bash
# Always run from the repo root
pip install -e ".[dev]"
lynx init                    # creates default policy + state dir

# Scripted demos (no API key needed)
python examples/hello_agent.py
python examples/file_janitor.py
python examples/refund_agent.py

# Real LLM demos (need an API key)
export ANTHROPIC_API_KEY=sk-ant-...
python examples/claude_janitor.py

export OPENAI_API_KEY=sk-...
python examples/openai_janitor.py

# Web service demo
pip install fastapi uvicorn
uvicorn examples.fastapi_server:app --reload
# Then POST to http://localhost:8000/agent/run
```

## After running anything

```bash
lynx ps                      # see the runs
lynx trace <run-id>          # see the step-by-step
lynx audit verify <run-id>   # check the hash chain
lynx audit export <run-id>   # compliance export (jsonl)
```

## Want to contribute another example?

See [CONTRIBUTING.md](../CONTRIBUTING.md). New examples should:

1. Be self-contained — one Python file + one YAML if needed
2. Either include a scripted agent (no API key) *or* clearly document the env var
3. Print enough output that running it tells you what happened
4. Demonstrate a verdict or capability that no existing example covers
