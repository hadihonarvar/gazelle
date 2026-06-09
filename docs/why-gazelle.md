# Why Gazelle?

A decision guide for "should I use this, and when not?"

---

## The one-paragraph pitch

**Gazelle sits between your AI agent and the real world.** Every action the agent wants to take (shell command, SQL query, HTTP call, file write) is checked against a YAML policy you wrote. Dangerous actions are blocked, irreversible ones are previewed first, the rest run normally. Every decision is recorded in a hash-chained audit log. Without Gazelle, hallucinated commands run as-is. With Gazelle, **only policy-approved actions touch the world.**

## When you need Gazelle

You need Gazelle when **any** of these are true:

| Situation | Why Gazelle helps |
|-----------|------------------|
| Your agent runs shell commands or SQL | One hallucinated `rm -rf /` or `DELETE FROM users` is a disaster. Policy makes those structurally impossible. |
| Your agent moves money, sends messages, creates GitHub PRs | Approval thresholds and rate limits enforced by the kernel, not by the model |
| You need a SOC 2 / HIPAA / EU AI Act audit trail | Hash-chained, content-addressed audit log generated automatically |
| You're shipping an LLM-powered product to customers | "The model decided to" isn't a defense. Gazelle gives you a paper trail of what was decided, why, and who approved it |
| Multiple people manage the same agent | YAML policy is reviewable in PRs. Code-review your guardrails instead of trusting prompts |
| You want crash safety on long-running agents | Pre-execution checkpointing + idempotent resume |
| You're running agents in regulated industries (finance / healthcare / gov) | Threat-modeled, audited, on-prem-capable |

## When you don't need Gazelle

| Situation | Use instead |
|-----------|-------------|
| Your agent only reads data (no side effects) | Just an LLM call + a read-only DB user; no kernel needed |
| You're running one-off scripts locally for personal use | Type at the terminal yourself |
| All your tools are already strictly idempotent and read-only | LangChain or vanilla SDK is enough |
| You need cross-machine workflow orchestration but not policy | [Temporal](https://temporal.io/) (durable execution, no policy) |
| You need cluster-wide policy without agents | [OPA](https://openpolicyagent.org) (policy, no agent loop) |

## How Gazelle compares to alternatives

| Tool | What it solves | What it doesn't |
|------|---------------|-----------------|
| **Naked LangChain / CrewAI / SDK** | Building the agent loop | Reliability, safety, audit, durable execution |
| **Temporal** | Durable execution + retries | Policy on individual tool calls, audit chain |
| **Open Policy Agent (OPA)** | Cluster-wide policy decisions | Agent loop, durability, tool mediation |
| **LangSmith / Langfuse** | LLM observability (after the fact) | Stopping bad actions before they run |
| **Gazelle** | Policy + durability + audit *at the tool-call boundary* | Cluster orchestration; observability of LLM token-level traces |

**Gazelle's niche is the tool-call boundary** — the single place where an agent's intention meets the world. Tools above it (frameworks) keep planning; tools below it (Temporal, OPA) keep coordinating. Nobody else owns the seat-belt at that exact layer.

## Real incidents Gazelle would have prevented

These all happened in 2025–2026:

1. **AWS engineer's prod environment wiped** by an agent asked to fix a minor Cost Explorer issue. With Gazelle's `require_approval` rule on production destructive ops, the rebuild would have prompted for sign-off.
2. **Meta AI safety director's inbox deleted** by her own agent; "stop" signals were ignored. Gazelle owns the stop signal at the kernel level — not "whenever the model decides to listen."
3. **Google Antigravity wiped a developer's `D:\` drive** when asked to clear a cache folder. Path containment in policy makes this impossible.
4. **n8n upgrade broke function-calling schemas silently across the user base.** Tool contracts in Gazelle are versioned and pinned to the run.
5. **5,000 fraud-watchlist refund.** A clever sob story could convince an LLM-driven support agent to issue any refund. Policy with a `is_watchlist_customer` predicate makes it deniable at the kernel.

## What Gazelle is *not* trying to be

| Not | Because |
|-----|---------|
| A new agent framework | LangGraph / CrewAI / OpenAI SDK already exist; we wrap them, not replace them |
| A prompt-injection defense | Gazelle stops unsafe *actions*; it doesn't reason about whether the agent's *intention* was corrupted by a hostile document. Treat LLM outputs as untrusted; let policy be the second line of defense. |
| A general-purpose RBAC system | Policy is for tool calls. Use your existing auth layer for user permissions. |
| A model evaluation framework | Use Braintrust, LangSmith, or Arize Phoenix for that. Gazelle is downstream — it shows what *happened*, not whether the LLM was *good*. |

## Summary in one line

> Gazelle is the seat belt. Your LLM is the driver. You still pick the destination — but if the driver hallucinates, the belt holds.
