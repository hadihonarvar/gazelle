# Lynx Threat Model

A structured walkthrough of what Lynx defends against, what it does *not*, and how the trust boundaries are drawn. Format follows the STRIDE framework: **S**poofing, **T**ampering, **R**epudiation, **I**nformation disclosure, **D**enial of service, **E**levation of privilege.

> Status: v1.0 shipped. Mitigations marked **(v1.0)** are landed; **(v1.x)** are on the post-launch roadmap.

---

## 1. Trust boundaries

```
  ┌────────────────────────────────────────────┐
  │  AGENT (LLM, potentially adversarial)      │
  │  - may propose any tool call               │
  │  - may try to escape sandbox via prompt    │
  └────────────────────────┬───────────────────┘
                           │  ① ActionRequest
                           ▼
  ┌────────────────────────────────────────────┐
  │  LYNX KERNEL (trusted)                     │
  │  - PDP, mediator, scheduler, audit         │
  │  - same OS process as the operator         │
  └────────────────────────┬───────────────────┘
                           │  ② executed action
                           ▼
  ┌────────────────────────────────────────────┐
  │  TOOL FUNCTION (operator-supplied code)    │
  │  - may run in sandbox if declared          │
  └────────────────────────┬───────────────────┘
                           │  ③ real-world side effect
                           ▼
  ┌────────────────────────────────────────────┐
  │  WORLD (filesystem, DBs, APIs, etc.)       │
  └────────────────────────────────────────────┘

  Out-of-band:
  ┌────────────────────────────────────────────┐
  │  OPERATOR (writes policy + approves)       │
  └────────────────────────────────────────────┘
```

The **agent is untrusted**. The **kernel is trusted**. The **tool author and operator are trusted**.

---

## 2. STRIDE analysis

### S — Spoofing

| Threat | Mitigation |
|--------|-----------|
| Agent claims to be a different principal | Principal is set by the runtime caller; agent has no input into it. **(v1.0)** |
| Approval forged by attacker who reads DB | Approval rows include the `granted_by` principal and a resolved-at timestamp. For production, signed approvals via HSM are planned. **(v1.x)** |
| Adapter impersonates a different framework | Adapter modules are explicit imports; no auto-loading. Operator chooses which adapter to instantiate. **(v1.0)** |

### T — Tampering

| Threat | Mitigation |
|--------|-----------|
| Audit log rewritten to hide a denied/approved action | Audit chain is content-addressed (sha256 of canonical-JSON body) and linked: `event.id = sha256(prev || body)`. `verify_audit_chain` walks the chain and detects body changes, hash changes, and missing seqs. **(v1.0)** |
| Same-process attacker tampers with the audit DB | The kernel and the audit DB share a process boundary today. For untrusted tools, run them in the subprocess sandbox so they have no DB handle. **(v1.0)**. Separate audit-store writer process planned. **(v1.x)** |
| Policy YAML modified at runtime to widen a rule | The `PolicyBundle` is hashed (content-addressed `id`) at task-creation time and pinned on the Task row. Policy changes do not affect in-flight tasks. **(v1.0)** |
| Tool result rewritten between mediator and journal | The mediator and journal are in-process; no IPC boundary to attack. Trust model assumes the kernel is intact. |

### R — Repudiation

| Threat | Mitigation |
|--------|-----------|
| Operator denies they approved an action | Every approval is recorded as an AuditEvent with `body.approver`, hash-chained. Cannot be silently removed. **(v1.0)** |
| Agent claims it never proposed an action | `step.proposed` events are hash-chained, content-addressed, can be cryptographically signed when HSM signing lands. **(v1.x)** |

### I — Information disclosure

| Threat | Mitigation |
|--------|-----------|
| Sensitive args leak into audit log (passwords, tokens, PII) | The HTTP shadow redacts `Authorization`, `X-API-Key`, `Cookie` already. Generalized redaction at the audit-write boundary planned. **(v1.x)** |
| Tool output leaks into adjacent runs via conversation reconstruction | Each run owns its own journal; checkpoints are per-run. The store does not cross-link runs unless the operator code does. **(v1.0)** |
| Logs include full file contents from `read_file` results | `ActionResult.value` is JSON-serialized and stored. Operators must decide what to expose; we recommend wrapping read_file with a redactor when the file may contain secrets. Documented in the security guide. **(v1.0)** |

### D — Denial of service

| Threat | Mitigation |
|--------|-----------|
| Adversarial agent floods the kernel with tool calls | `Budget(steps=...)` caps step count. Default is 50. Duration cap also enforced. **(v1.0)** |
| Adversarial policy YAML triggers catastrophic regex backtracking | Regex compilation timeout planned; for now, lint command flags polynomial patterns. **(v1.x)** |
| Adversarial tool runs forever | The subprocess sandbox accepts `timeout_seconds`; default cap is 60s. **(v1.0)** |
| Adversarial agent fills the audit log to exhaust disk | Per-run audit count is bounded by Budget. SQLite is single-file; ops should disk-monitor. Operational concern, documented but not enforced. **(v1.0)** |
| Adversarial policy creates many small rules to slow PDP | PDP evaluation is linear in rule count; benchmarks show <1ms even with 200 rules. Caps planned only if a real abuse pattern surfaces. **(v1.x)** |

### E — Elevation of privilege

| Threat | Mitigation |
|--------|-----------|
| Agent escapes the workspace via path traversal in tool args | Operator's policy must include path-containment rules (see `examples/policies/devops.yaml`). Helper predicates planned. **(v1.x)** |
| Tool function called with rewritten args via `transform` verdict elevates beyond intended scope | `transform` is operator-defined; operator is trusted. Documented as "use sparingly." **(v1.0)** |
| Untrusted tool in same process reads `~/.ssh` | Use `@tool(sandbox="subprocess")` to bind the tool to a stripped env and working directory. **(v1.0)** |
| Approval bypass via direct DB write | Anyone with file-system access to `state.db` can edit it. This is the same trust level as the kernel; if you don't trust the host, use a sandboxed audit-store writer. Documented. **(v1.0)** |

---

## 3. Things Lynx does NOT defend against

1. **A malicious operator.** If the person writing policies is hostile, the policies are hostile. Out of scope.
2. **A compromised kernel binary.** If `pip install lynx-agent` itself is from a typosquatted package, all bets are off. PyPI's Trusted Publishing via OIDC mitigates supply-chain risk on our end.
3. **Side-channel attacks on the host OS.** Timing channels, RAM scraping, etc. are below our threat model.
4. **The wrapped LLM's prompt-injection vulnerabilities.** If a user puts a prompt-injection payload in a document that the agent reads, the agent may propose actions the user did not intend. Lynx prevents those *actions* from being unsafe; it does not prevent the *intent corruption*. Operators must still treat LLM outputs as untrusted.
5. **Wrapped-tool vulnerabilities.** If you wrap a vulnerable `eval()`-based tool with `@tool`, the policy can deny that tool — but if it's allowed, the vulnerability stays.

---

## 4. Security guarantees we make

If the kernel is intact and the operator's policy is correct, then:

1. **Every action is recorded.** The audit chain is the source of truth.
2. **No action runs without a Decision.** The mediator is the only execution path.
3. **No action runs with policy=DENY.** Verified by the test suite.
4. **No irreversible action without a shadow runs without approval (default policy).** Configurable.
5. **The Decision is reproducible from the (PolicyBundle, ActionRequest, ExecutionContext) triple.** The PDP is pure; replay produces the same Decision.

---

## 5. Disclosure policy

See [`SECURITY.md`](../SECURITY.md) for vulnerability reporting.

## 6. Next reviews

The next planned reviews are:

- **External security review.** Targets: audit-chain integrity, policy bypass paths, sandbox escape paths. Pending a third-party reviewer post-launch.
- **Annual review.** As new adapters / backends land.
