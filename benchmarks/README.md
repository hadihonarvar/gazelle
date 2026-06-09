# benchmarks/

How much overhead does Gazelle add to an agent? Two benchmarks, both runnable in seconds.

| Benchmark | What it measures | Why it matters |
|-----------|-----------------|----------------|
| **`bench_pdp.py`** | Policy Decision Point latency vs rule count | The PDP runs once per agent step. If it's slow, every agent step is slow. |
| **`bench_end_to_end.py`** | Full runtime overhead per step (vs. running the same tool naked) | The honest "what's the cost of using Gazelle" number. |

## Run them

```bash
.venv/bin/python benchmarks/bench_pdp.py
.venv/bin/python benchmarks/bench_end_to_end.py
```

## Expected numbers (June 2026, M1 Mac, Python 3.12)

### PDP latency

```
   rules     µs/call     calls/sec
------------------------------------
       0        1.1       883,651
      10       10.8        93,056
      50       50.0        20,016
     100      104.0         9,619
     250      253.6         3,943
     500      511.4         1,955
    1000     1055.2           948
```

**Linear scaling.** Typical real-world policies have <100 rules → ~100µs per evaluation. For real agents where each step is an LLM call (500ms–5s), the PDP overhead is essentially noise.

### End-to-end overhead

```
       naked          3.20ms        0.064ms/step
         gzl        160.50ms        3.210ms/step
    overhead                        3.146ms/step
```

The ~3ms/step overhead is almost entirely SQLite writes: one Step row + one AuditEvent per step. For agents with long-running tool calls (which is the realistic case), this is ~0.06% overhead.

Optimizations possible (deferred until measured):
- Batch checkpoints (one write per N steps in fast mode)
- Use a faster journal mode (`PRAGMA synchronous=NORMAL`)
- Postgres pipelining for the production backend

## Why these are simple

Both benchmarks are intentionally small — readable in one screen — so anyone can verify them and reproduce them. They're not full performance regression suites. If you suspect a regression, add a focused micro-benchmark next to these.

## Adding a new benchmark

Same structure: stand-alone Python file, prints a table, runs in <30 seconds, uses only `time.perf_counter()` plus the standard library + Gazelle.
