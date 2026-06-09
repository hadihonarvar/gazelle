# Cookbook

Copy-pasteable patterns for the policy.yaml file you write.

Each recipe answers "I want X" with the YAML to make X true.

---

## I want to block `rm -rf /` regardless of context

```yaml
- id: shell-rm-rf-root
  priority: 100        # high priority so it fires before anything else
  match:
    tool: shell
    args.cmd.matches: '^\s*rm\s+(-[rRf]+\s+)+/(\s|$)'
  decision: deny
  reason: "rm -rf / is hard-blocked"
```

## I want to allow reads but require approval for writes

```yaml
rules:
  - id: read-only-allow
    match:
      declared.scope.contains_any: ["filesystem:read", "db:read", "net:read"]
    decision: allow

  - id: writes-need-approval
    match:
      declared.scope.contains_any: ["filesystem:write", "db:write", "net:write"]
    decision: approve_required
    approvers: ["@oncall"]
    timeout_seconds: 1800
```

## I want production to be stricter than dev

```yaml
predicates:
  in_prod: { context.environment: prod }
  is_destructive:
    args.cmd.matches: '(?i)\b(delete|drop|truncate|rm)\b'

rules:
  - id: prod-destructive-needs-approval
    match:
      all_of: [in_prod, is_destructive]
    decision: approve_required
    approvers: ["@dba-oncall"]

  - id: dev-destructive-allowed
    match: is_destructive
    decision: allow
```

## I want every irreversible action to be dry-run first

```yaml
- id: irreversible-dry-run
  match: { declared.reversible: false }
  decision: dry_run
```

## I want a path-containment rule (no writes outside the workspace)

```yaml
- id: write-outside-workspace
  match:
    tool: [write_file, delete_file]
    args.path.matches: '^/(etc|System|Library|root)(/|$)'
  decision: deny
  reason: "Writes outside workspace are forbidden"
```

(For *fully dynamic* workspace containment, use a Python rule — see "Python escape hatch" below.)

## I want a spend cap on refunds

```yaml
predicates:
  is_refund: { tool: refund_customer }

rules:
  - id: over-500-blocked
    priority: 100
    match:
      all_of:
        - is_refund
        - { args.amount_usd.gt: 500 }
    decision: deny
    reason: "Amounts over $500 require Finance, not Support."

  - id: medium-refund-needs-approval
    priority: 50
    match:
      all_of:
        - is_refund
        - { args.amount_usd.gt: 50 }
    decision: approve_required
    approvers: ["supervisor:on-call"]

  - id: small-refund-allowed
    priority: 30
    match:
      all_of:
        - is_refund
        - { args.amount_usd.le: 50 }
    decision: allow
```

## I want to block actions to a fraud-watchlist customer

```yaml
predicates:
  is_watchlist_customer:
    args.customer_id.in: ["C-789", "C-1023"]

rules:
  - id: fraud-watchlist-block
    priority: 100
    match: is_watchlist_customer
    decision: deny
    reason: "Customer is on the fraud watchlist; finance must handle manually."
```

For dynamic watchlists, see "Python escape hatch" below.

## I want SQL DELETE/UPDATE without WHERE to be denied

```yaml
- id: sql-bulk-mutation-denied
  match:
    tool: sql_exec
    args.sql.matches: '(?i)^\s*(DELETE|UPDATE)\b(?!.*\bWHERE\b)'
  decision: deny
  reason: "DELETE / UPDATE without WHERE clause is forbidden"
```

## I want to auto-add `tenant_id` filter to every SQL query

```yaml
- id: sql-tenant-scope-injection
  match:
    tool: sql_exec
    args.sql.matches: '(?i)\b(update|delete)\b'
  decision: transform
  transform:
    jsonpath: "$.args.sql"
    append: " AND tenant_id = '${context.principal.id}'"
```

## I want to redact secrets in HTTP calls

The built-in `http_shadow` already does this. To enforce it as policy:

```yaml
- id: outbound-http-must-use-shadow
  match:
    tool: http_call
    declared.has_shadow: false
  decision: deny
  reason: "HTTP tools must declare a shadow that redacts Authorization headers"
```

## I want to require sandbox isolation for net-egress tools

```yaml
- id: net-egress-must-sandbox
  match:
    declared.scope.contains: "net:egress"
    declared.sandbox: "none"
  decision: deny
  reason: "Network egress tools must declare sandbox='subprocess' or stronger"
```

## I want to block actions outside business hours

```yaml
predicates:
  after_hours:
    context.extra.utc_hour.not_between: [9, 17]

rules:
  - id: destructive-after-hours-deny
    match:
      all_of:
        - after_hours
        - { declared.reversible: false }
    decision: deny
    reason: "Irreversible actions blocked outside business hours"
```

You'll need to set `context.extra.utc_hour` when starting the run:

```python
runtime.run(
    agent, task="...", policy="policy.yaml",
    principal={"kind": "user", "id": "hadi"},
    # If extra context is needed, pass via principal/environment in your wrapper.
)
```

## Python escape hatch — workspace path containment

YAML can't easily reference dynamic context like `context.workspace`. Use a Python rule:

```python
# policy_rules.py
import os
from lynx import policy

@policy.rule(id="block-paths-outside-workspace", priority=10)
def block_paths_outside_workspace(req, ctx):
    if req.tool not in ("shell", "write_file", "delete_file"):
        return None  # rule does not apply
    paths = extract_paths(req.args)
    workspace = os.path.abspath(ctx.workspace)
    for path in paths:
        if not os.path.abspath(path).startswith(workspace):
            return policy.deny(reason=f"Path {path} escapes workspace {workspace}")
    return None  # let later rules decide
```

```yaml
# policy.yaml
include_python: ["./policy_rules.py"]
```

## Python escape hatch — dynamic watchlist

```python
@policy.rule(id="fraud-watchlist-block", priority=100)
def fraud_watchlist_block(req, ctx):
    if req.tool != "refund_customer":
        return None
    customer_id = req.args.get("customer_id", "")
    if redis.sismember("fraud_watchlist", customer_id):
        return policy.deny(reason=f"{customer_id} is on the fraud watchlist")
    return None
```

## Default-deny with explicit allow-list

```yaml
defaults:
  on_no_match: deny

rules:
  - id: allowlist-shell
    match:
      tool: shell
      args.cmd.matches: '^(ls|cat|grep|head|tail)\s'
    decision: allow

  - id: allowlist-sql-select
    match:
      tool: sql_exec
      args.sql.matches: '(?i)^\s*SELECT\b'
    decision: allow

  # Anything else → deny via default
```

## Allow-everything-but-block-known-bad

```yaml
defaults:
  on_no_match: allow

rules:
  - id: block-rm-rf-root
    match:
      tool: shell
      args.cmd.matches: '^\s*rm\s+(-[rRf]+\s+)+/(\s|$)'
    decision: deny

  - id: block-bulk-deletes
    match:
      tool: sql_exec
      args.sql.matches: '(?i)^\s*DELETE\b(?!.*\bWHERE\b)'
    decision: deny

  # Everything else → allow via default
```

(Use this *carefully* — default-allow is a footgun if you forget a destructive tool.)

---

## More patterns

If you build a useful rule and think others would benefit, send a PR adding it to this file. The cookbook grows by accretion.
