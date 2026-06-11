# FAQ

### Does Lynx slow my agent down?

The PDP is a pure function; typical evaluation is ~1µs. Per step, the kernel adds a small number of dict / dataclass allocations plus whatever your sinks do. For real agents where each step is a 500 ms – 5 s LLM call, Lynx's overhead is negligible.

### Where does the audit go?

Wherever you point the sinks. v2 holds nothing. Common choices:
- `stdout_sink()` — dev
- `jsonl_sink(open("audit.jsonl", "a"))` — to disk; you own retention
- Custom `callback_sink(fn)` — ship to OTel, Datadog, Splunk, your bus

### Can I get the v1 hash-chained audit chain?

Not in v2. If you need it: `pip install "lynx-agent<2.0"`. We keep v1.0.x security-patched.

### How do I do cross-process approval (Slack, web UI)?

Write a custom `on_approval` handler that talks to your queue:

```python
async def slack_approval(req):
    msg = await slack.post(f"Approve {req.request.tool}?")
    btn = await slack.wait_for_click(msg, timeout=3600)
    return ApprovalDecision(granted=btn=="approve", approver=btn.user)

await run_agent(..., on_approval=callback_approval(slack_approval))
```

The `run_agent` call blocks on your handler. Lynx stays stateless; your handler owns the wait.

### What happens if my process crashes mid-run?

The run is lost. v2 does not survive a process restart. If you need that, use [Temporal](https://temporal.io) for the orchestration layer + Lynx for the policy layer, or pin v1.

### Is there a Runtime singleton?

No. Each `run_agent` call is fully independent. There is no `Runtime` class, no module-level `runtime`.

### How do I use a custom tool registry per request?

Just build a new `ToolSet`:

```python
@tool(reversible=True)
async def read_only(): ...

@tool(reversible=False)
async def writeable(): ...

dev_tools = ToolSet.from_functions(read_only, writeable)
prod_tools = ToolSet.from_functions(read_only)        # safer in prod
```

Pass whichever to `run_agent`. ToolSets are immutable, cheap to build, freed when the call returns.

### How do I hot-reload policy?

Re-call `load_policy_file()` whenever you want a new bundle. Build at request time if you need:

```python
async def handler():
    policy = load_policy_file("policy.yaml")    # fresh each request
    return await run_agent(..., policy=policy)
```

### Do I need to clean up anything?

No. v2 holds no file handles, no DB connections, no sockets, no subprocess refs. Your sinks own their files; close them when you're done. The subprocess sandbox auto-cleans its temp dir.

### Is mypy strict required for users?

No. You get the type annotations and can run mypy at whatever level you prefer. Inside Lynx, `mypy --strict` is a target we're moving toward but not yet a hard CI gate — it's an advisory check today.

### Can I use it inside FastAPI / Django / Flask?

Yes — see `examples/09_fastapi_service.py`, `11_flask_service.py`, `12_django_service.py`.

### What about MCP?

`lynx.adapters.mcp.mcp_tools(command) -> ToolSet` connects to an MCP server, discovers its tools, and returns them as an immutable `ToolSet`. Union it with your local tools and pass to `run_agent`:

```python
from lynx.adapters.mcp import mcp_tools
remote = await mcp_tools("python -m my_mcp_server")
tools = remote.union(ToolSet.from_functions(local_tool))
await run_agent(agent, task=..., tools=tools, policy=...)
```

No global registration. The MCP defaults are conservative (`reversible=False`, scope `mcp:tool`) so policies must explicitly allow them.

### How do I file a security issue?

[GitHub Security Advisories](https://github.com/hadihonarvar/lynx/security/advisories/new). Do not file a public issue.

### Where's the license?

[Apache 2.0](../LICENSE).
