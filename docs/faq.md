# FAQ

The questions people ask in the first 48 hours.

---

### Does Gazelle slow my agent down?

The PDP itself is ~1µs for a typical policy (≤100 rules). End-to-end overhead per step is ~3ms — almost entirely SQLite writes for the checkpoint + audit log. For real agents where each step is an LLM call (typically 500ms–5s), Gazelle's overhead is negligible (<1%).

Live numbers in [`benchmarks/`](../benchmarks/README.md).

### Which agent frameworks does it support?

Built-in adapters: **Anthropic Claude, OpenAI, LangGraph, CrewAI, MCP servers**. The `Agent` protocol is one method — adding a new framework is typically <100 lines.

You can also use Gazelle with a hand-rolled loop. Anything with `async def step(conversation) -> ToolCall | FinalAnswer` works.

### Do I need to rewrite my tools?

No. Wrap existing functions with `@tool(...)`. If your tool is synchronous, wrap it in `asyncio.to_thread(...)` inside an async shim.

### How do I write a policy rule?

Three layers, increasing power:

```yaml
# Layer 1: declarative YAML
- id: block-prod-deletes
  match:
    tool: aws_cli
    context.environment: prod
    args.cmd.matches: '^aws .* delete-'
  decision: deny
```

```yaml
# Layer 2: named predicates for reuse
predicates:
  in_prod: { context.environment: prod }
  is_destructive:
    args.cmd.matches: '(?i)\b(delete|drop|truncate)\b'
rules:
  - match: { all_of: [in_prod, is_destructive] }
    decision: approve_required
    approvers: ["@oncall"]
```

```python
# Layer 3: Python escape hatch for edge cases YAML can't express
@policy.rule(priority=10)
def block_paths_outside_workspace(req, ctx):
    for path in extract_paths(req.args.get("cmd", "")):
        if not path.startswith(ctx.workspace):
            return policy.deny(reason=f"Path {path} escapes workspace")
```

Full grammar in [`docs/02-policy-language.md`](02-policy-language.md).

### Can I test my policy without running an agent?

Yes — `gazelle policy lint policy.yaml` validates it; fixture-based testing is supported with `gazelle policy test fixtures/`. The PDP is a pure function, so unit tests are easy:

```python
from gazelle.policy import compile_policy, evaluate

bundle = compile_policy(open("policy.yaml").read())
decision = evaluate(bundle, request, context)
assert decision.verdict == "deny"
```

### What if my LLM doesn't realize an action was denied?

Gazelle feeds the denial back into the conversation as a tool result:

```
[denied by policy] rm -rf / is hard-blocked
```

Modern LLMs (Claude, GPT-4/5, Gemini) treat this as a normal tool failure and retry with a different approach. If you find your model ignoring denials, prompt-engineer the system message to acknowledge denials explicitly.

### Where does state get stored?

By default: `./.gazelle/state.db` (SQLite). You can point to any path via config. For production, swap to Postgres:

```python
from gazelle.stores.postgres import PostgresStore
runtime = Runtime(store=PostgresStore("postgresql://..."), policy=...)
```

### Is the audit log secure?

Each event is content-addressed (`event.id = sha256(prev || canonical_json(body))`) and linked to its predecessor. `gazelle audit verify <run-id>` walks the chain and detects body changes, hash mismatches, or missing events.

Anyone with write access to the SQLite file can edit it — Gazelle does not defend against that. For untrusted hosts, use Postgres with restricted DB user permissions, or wait for v1.1's signed-audit feature.

### How do I add a new tool to an existing agent?

Decorate the function and the agent picks it up:

```python
@tool(cost="low", reversible=True, scope=["db:read"])
async def query_users(filter: str) -> list[dict]:
    ...
```

If you're using the Anthropic/OpenAI adapters, the tool's signature is auto-translated into the model's tool schema. No prompt-engineering needed.

### Can multiple agents share the same store?

Yes. SQLite handles concurrent reads via WAL mode. For high-throughput multi-agent or multi-process setups, use Postgres.

### What about secrets in the audit log?

The HTTP shadow already redacts `Authorization`, `X-API-Key`, `Cookie`. For tool arguments containing secrets, either:

1. Don't pass secrets as tool args (read them from env inside the tool)
2. Wrap the tool with a redactor before registering it

A first-class redaction layer is planned for v1.1.

### Does Gazelle work with sync code (Flask, Django < 4.1)?

Yes — use `runtime.run_sync(...)`. Tool functions still need to be `async def`, but the outer runtime call can be sync.

### Can I run Gazelle inside FastAPI / Django / Flask?

Yes. See [`examples/fastapi_server.py`](../examples/fastapi_server.py) for the cleanest integration. Django + Flask snippets are in the same file's comments.

### Does it need an API key?

The runtime itself doesn't. The adapters (`ClaudeAgent`, `OpenAIAgent`) need their respective API keys via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). If you're using a scripted agent, no keys at all.

### How do I handle approvals from Slack / email / a web UI?

The approval broker is in-memory; the source of truth is the SQLite/Postgres `approval_requests` table. When `approve_required` fires, you get an `approval_id` back. Wire any UI you like to call `runtime.approve(approval_id, approver="...")`. After approval, call `runtime.resume(run_id)` to continue the agent.

See the FastAPI example for a concrete webhook implementation.

### Can I see what the agent did *before* a step ran?

`gazelle replay <run-id> --inspect` walks the step history without re-executing. To re-run from a step with edits: `gazelle replay <run-id> --from-step 8 --edit args.cmd='ls'`.

### What licenses does the project have?

[Apache 2.0](../LICENSE). Patent-protective, permissive, compatible with most commercial use.

### Where do I file a bug?

[GitHub Issues](https://github.com/hadihonarvar/gazelle/issues). Use the `[bug]` template. Include a minimal reproducer (Python file + policy.yaml).

### Where do I propose a feature?

[GitHub Issues](https://github.com/hadihonarvar/gazelle/issues) with the `[feat]` template. For larger changes, please file an issue *before* writing the PR.

### How do I report a security vulnerability?

**Do not file a public issue.** Use [GitHub Security Advisories](https://github.com/hadihonarvar/gazelle/security/advisories/new). See [`SECURITY.md`](../SECURITY.md).
