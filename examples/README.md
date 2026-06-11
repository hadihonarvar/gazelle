# examples/

A learning path of 12 examples. Each is **self-contained** and starts with a plain-language SCENARIO explaining the problem it solves.

Read them in order — each one builds on the last.

```
SIMPLE          01 → 02 → 03         "see the system working"
MORE COMPLEX    04 → 05 → 06         "approvals, real LLMs, streaming audit"
ADVANCED        07 → 08 → 09         "production patterns: rules, transforms, web service"
COMPLETE        10                   "the full thing — one realistic DevOps scenario"
INTEGRATIONS    11 (Flask)  12 (Django)   "drop Lynx into your existing web framework"
```

## The 12 examples

| # | File | Verdict shown | Problem in one line |
|---|------|--------------|---------------------|
| 01 | [`01_hello_allow.py`](01_hello_allow.py) | `allow` | "Just confirm my install works." |
| 02 | [`02_block_dangerous.py`](02_block_dangerous.py) | `deny` | "Block `rm -rf /` before it can run." |
| 03 | [`03_preview_writes.py`](03_preview_writes.py) | `dry_run` | "Show me the file BEFORE saving it." |
| 04 | [`04_human_approval.py`](04_human_approval.py) | `approve_required` | "Pause for my OK before wiring money." |
| 05 | [`05_real_llm_blocked.py`](05_real_llm_blocked.py) | `allow` + `deny` | "Use a REAL LLM (Claude / GPT) — does Lynx still gate it?" |
| 06 | [`06_streaming_to_jsonl.py`](06_streaming_to_jsonl.py) | (focus: sinks) | "Stream every event to a jsonl file — your audit trail." |
| 07 | [`07_refund_workflow.py`](07_refund_workflow.py) | `allow` + `approve` + `deny` | "Customer support: small refunds auto, big ones ask, fraud denies." |
| 08 | [`08_sql_transform.py`](08_sql_transform.py) | `transform` | "Auto-add `WHERE tenant_id = X` to every multi-tenant SQL query." |
| 09 | [`09_fastapi_service.py`](09_fastapi_service.py) | full HTTP service | "Wrap Lynx in FastAPI for production deployment." |
| 10 | [`10_devops_assistant.py`](10_devops_assistant.py) | **all five verdicts** (one policy, run in staging + prod) | "An AI DevOps assistant — every safety rule in one realistic scenario." |
| 11 | [`11_flask_service.py`](11_flask_service.py) | sync HTTP service | "Same as 09 but for Flask — sync framework, `asyncio.run(...)` inside view." |
| 12 | [`12_django_service.py`](12_django_service.py) | Django 4.1+ async views | "Same as 09 but as a single-file Django app." |

## How to run any of them

```bash
# Set up once
pip install -e ".[dev]"

# Examples 01-04, 06-08, 10 — no API key needed (scripted agents)
python examples/01_hello_allow.py
python examples/02_block_dangerous.py
python examples/03_preview_writes.py
python examples/04_human_approval.py    # type "y" + Enter at the prompt
python examples/06_streaming_to_jsonl.py
python examples/07_refund_workflow.py
python examples/08_sql_transform.py
python examples/10_devops_assistant.py

# Example 05 — needs a real LLM API key
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY=sk-...
python examples/05_real_llm_blocked.py

# Example 09 — runs as a web service
pip install fastapi uvicorn
uvicorn examples.09_fastapi_service:app --reload
# Then POST to http://localhost:8000/agent/run

# Example 11 — Flask web service
pip install flask
# Use the file-path form: the digit-prefixed filename is not a valid Python
# module name, so the dotted "examples.11_flask_service" form will not work.
flask --app examples/11_flask_service.py run --debug

# Example 12 — Django web service (single-file)
pip install django
python examples/12_django_service.py runserver
```

## After running anything

In v2 the audit goes to **your sinks**, not to a Lynx-managed database. Inspect the events as they happen via `stdout_sink()`, or stream them to a file via `jsonl_sink(...)` (see example 06).

There is no `lynx ps` / `lynx trace` / `lynx audit` — v2 holds no past runs.

## What each example demonstrates

| | Concept | Where to learn |
|--|---------|----------------|
| ALLOW    | Policy lets the action through unchanged | 01, 02, 05, 07, 10 |
| DENY     | Policy refuses; agent sees the denial as a tool result | 02, 05, 07, 08, 10 |
| DRY_RUN  | Tool's `.shadow` runs instead of the real function; preview only | 03, 10 |
| APPROVE_REQUIRED | Sync `on_approval` handler is called; the run blocks until it returns | 04, 07, 10 |
| TRANSFORM | Policy rewrites the action's args (e.g. injects a `WHERE` clause) | 08, 10 (staging kubectl apply) |
| Streaming events via sinks | Every step emits events; sinks consume them | All; explicit focus in 06 |
| Multiple sinks (stdout + jsonl) | `multi_sink(...)` fans out | 06 |
| Web service integration | FastAPI / Flask / Django | 09 / 11 / 12 |
| Real LLM | ClaudeAgent / OpenAIAgent | 05 |

## Where to go next

After running through the examples:

| You want to… | Read |
|--------------|------|
| Understand the design | [`docs/v2-rfc.md`](../docs/v2-rfc.md) |
| Understand the vocabulary | [`docs/concepts.md`](../docs/concepts.md) |
| Build your own policy from scratch | [`docs/02-policy-language.md`](../docs/02-policy-language.md) |
| Copy-paste common policy patterns | [`docs/cookbook.md`](../docs/cookbook.md) |
| Wire sinks / approvals into your stack (SQLite, Postgres, Splunk, OTel, Slack, Temporal, ...) | [`docs/integration-cookbook.md`](../docs/integration-cookbook.md) |
| Get unstuck | [`docs/faq.md`](../docs/faq.md) |

## Want to contribute another example?

See [CONTRIBUTING.md](../CONTRIBUTING.md). Good examples are:
- Self-contained — one Python file + (optionally) one YAML
- Lead with a plain-language SCENARIO at the top of the docstring
- Use a scripted agent for the offline path; document the API key for the LLM path
- Print enough output that the demo tells you what happened
- Demonstrate a verdict, sink, or capability that no existing example covers
