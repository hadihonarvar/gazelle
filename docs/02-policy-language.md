# Policy Language Spec

The contract between the operator (who writes policy) and the kernel (which enforces it). Three layers of expressiveness, all compiling to the same internal representation.

---

## Goals

1. **Reviewable in a pull request.** A non-Python reader can understand what a policy does from the YAML alone.
2. **Lintable and testable.** `gazelle policy lint` catches mistakes; `gazelle policy test fixtures/` proves behavior against examples.
3. **Pinned per task.** A task created today is evaluated against today's policy bundle, even if the file changes tomorrow.
4. **Deterministic.** No network, no clocks, no randomness inside the PDP. Same input → same Decision, always.
5. **Fast.** Sub-millisecond evaluation per request, even with hundreds of rules.

---

## Tier 1 — Declarative YAML (covers ~80% of cases)

```yaml
# policy.yaml
version: 1
defaults:
  on_missing_shadow: approve_required   # if a non-reversible tool has no shadow()
  on_no_match: deny                     # default-deny if no rule matches

rules:
  - id: allow-read-only
    description: "Read-only tools are always fine"
    match:
      declared.scope.contains_any: ["filesystem:read", "net:read", "compute:read"]
    decision: allow

  - id: shell-rm-rf-root
    description: "Never delete from root"
    match:
      tool: shell
      args.cmd.matches: '^\s*rm\s+(-[rRf]+\s+)+/(\s|$)'
    decision: deny
    reason: "rm -rf / is never allowed"

  - id: prod-mutations-need-approval
    match:
      context.environment: prod
      declared.scope.contains_any: ["filesystem:write", "db:write", "cloud:write"]
    decision: approve_required
    approvers: ["@oncall"]
    timeout_seconds: 1800

  - id: irreversible-dry-run-first
    match:
      declared.reversible: false
    decision: dry_run

  - id: tenant-scope-injection
    description: "All SQL writes must include tenant_id filter"
    match:
      tool: sql_exec
      args.sql.matches: '(?i)\bupdate\b|\bdelete\b'
    decision: transform
    transform:
      jsonpath: "$.sql"
      append: " AND tenant_id = '${context.principal.id}'"
```

### Field reference

```
match.<field>: <value>             # exact equality
match.<field>.matches: <regex>     # PCRE-ish, anchored at neither end
match.<field>.in: [a, b, c]        # set membership
match.<field>.contains: x          # substring (string) or element (list)
match.<field>.contains_any: [...]  # any overlap
match.<field>.contains_all: [...]  # subset
match.<field>.gt / .ge / .lt / .le: <num>
match.<field>.between: [lo, hi]    # inclusive
match.all_of: [<match>, ...]       # AND of sub-matches
match.any_of: [<match>, ...]       # OR of sub-matches
match.not: <match>                 # negation
```

### Available match fields

Anything in `ActionRequest` is addressable:

- `tool`
- `args.<path>` — `args.cmd`, `args.bucket`, `args.body.subject`, etc.
- `declared.cost`, `declared.reversible`, `declared.scope`, `declared.has_shadow`
- `context.environment`, `context.principal.kind`, `context.principal.id`, `context.workspace`
- `context.run_id`, `context.step_seq`
- `context.extra.<key>` — arbitrary operator-set data

### Decision shapes

```yaml
decision: allow
# ---
decision: deny
reason: "<why; shown to model + user>"
# ---
decision: dry_run
# ---
decision: approve_required
approvers: ["@oncall", "user:hadi"]
timeout_seconds: 1800
reason: "Destructive op in prod"
# ---
decision: transform
transform:
  jsonpath: "$.args.field"
  set: <literal>            # or
  append: <string>          # or
  delete: true              # or
  template: "${...}"        # string interpolation from context
```

---

## Tier 2 — Reusable Predicates

Compose patterns into named predicates and reference them by name.

```yaml
predicates:
  destructive_db:
    tool: ["sql_exec", "mongo_exec"]
    args.body.matches: '(?i)\b(drop|truncate|delete)\b'

  high_blast:
    declared.blast_radius_hint.gt: 100

  in_prod:
    context.environment: prod

  after_hours:
    context.extra.utc_hour.not_between: [9, 17]

rules:
  - id: prod-destructive-needs-approval
    match:
      all_of: [destructive_db, in_prod]
    decision: approve_required
    approvers: ["@dba-oncall"]

  - id: high-blast-after-hours-deny
    match:
      all_of: [high_blast, after_hours]
    decision: deny
    reason: "Large-blast ops blocked outside business hours"
```

Predicates are pure inlinable booleans. The compiler expands references at load time; there is no recursion or runtime indirection.

---

## Tier 3 — Programmatic Rules (Python escape hatch)

For predicates YAML can't easily express — path extraction, structural pattern matching, decimal math.

```python
# policy_rules.py
from gazelle import policy

@policy.rule(id="block-paths-outside-workspace", priority=10)
def block_paths_outside_workspace(req, ctx):
    if req.tool != "shell":
        return None  # rule does not apply
    for path in extract_paths_from_cmd(req.args.get("cmd", "")):
        absolute = resolve(path, base=ctx.workspace)
        if not absolute.startswith(ctx.workspace):
            return policy.deny(
                reason=f"Path {absolute} escapes workspace {ctx.workspace}"
            )
    return None
```

```yaml
# policy.yaml
include_python: ["./policy_rules.py"]
```

**Constraints on Python rules:**
- Must be a pure function of `(ActionRequest, ExecutionContext) -> Decision | None`.
- Returning `None` means "this rule does not apply; continue evaluation."
- No I/O, no global state, no random/time access outside what `ctx` exposes. The kernel enforces this at import time with an AST check.
- Rules are sorted by `priority` (descending), then by definition order.

---

## Evaluation Semantics

For each `ActionRequest`, the PDP runs:

```
1. Walk rules in (priority desc, file order) order.
2. For each rule, check `match` against the request.
3. If match → return rule.decision.
4. If no rule matches:
     - If declared.reversible == False and not declared.has_shadow:
         return defaults.on_missing_shadow.
     - Else:
         return defaults.on_no_match.
```

**First match wins.** No accumulation, no scoring. This makes policies predictable and debuggable.

To "review then enforce", layer rules from specific to general:

```yaml
rules:
  - id: allow-curl-localhost     # most specific
    match: { tool: shell, args.cmd.matches: "^curl http://localhost" }
    decision: allow

  - id: deny-curl                # general
    match: { tool: shell, args.cmd.matches: "^curl " }
    decision: deny
```

---

## Policy Bundle (compiled form)

A YAML file + included Python files compile into a **PolicyBundle**:

```python
@dataclass(frozen=True)
class PolicyBundle:
    id: str                           # sha256 of canonical bundle source
    version: int
    rules: tuple[CompiledRule, ...]
    defaults: PolicyDefaults
    source_files: tuple[str, ...]     # for `policy show`

@dataclass(frozen=True)
class CompiledRule:
    id: str
    priority: int
    matcher: Callable[[ActionRequest, ExecutionContext], bool]
    decision_factory: Callable[[ActionRequest, ExecutionContext], Decision]
    source_location: str              # "policy.yaml:line 42"
```

The bundle `id` is content-addressed; identical source → identical bundle ID. A Task pins itself to the bundle ID present at creation time.

---

## CLI: `policy lint`

Catches mistakes before deployment.

Checks:
- YAML schema validity
- Unknown match fields
- Regex compilability
- Unreachable rules (a more general rule sits above a more specific one)
- Predicates referenced but not defined
- Python rules with disallowed imports
- Approvers referenced but undefined in the principals file

```
$ gazelle policy lint policy.yaml
✔ 14 rules, 6 predicates loaded
✔ All regexes valid
⚠ Rule `allow-curl-localhost` is unreachable (rule `deny-curl` at line 12 matches first)
✘ Rule `prod-mutations-need-approval` references undefined approver `@oncall`
```

---

## CLI: `policy test`

Fixtures live alongside the policy and are run by the linter:

```yaml
# fixtures/shell-rm.yaml
- name: "rm -rf / is denied"
  given:
    tool: shell
    args: { cmd: "rm -rf /" }
    declared: { reversible: false, scope: ["filesystem:write"] }
    context: { environment: dev, principal: { kind: user, id: hadi } }
  expect:
    verdict: deny
    matched_rule: shell-rm-rf-root

- name: "rm -rf inside workspace is allowed in dev"
  given: { ... }
  expect:
    verdict: allow
```

```
$ gazelle policy test fixtures/
✔ 23/23 fixtures passed
```

---

## Hot reload

Out of scope for MVP. Reload requires restarting the runtime process. The bundle ID pinning rule means in-flight tasks are unaffected.

---

## Determinism and Replay

Because the PDP is pure, replaying a `Run` against its pinned `PolicyBundle` produces **identical decisions**. This is what makes `runtime.replay --edit` honest: edit a step's input, re-evaluate, see the new path the agent would have taken.

---

## What this language deliberately does NOT do

- **No turing-completeness in YAML.** No loops, no variables beyond match-time interpolation, no arbitrary computation.
- **No global state.** Each rule is a pure function of its match.
- **No cross-rule data passing.** First-match-wins is enforced.
- **No mutation of the request.** Only `transform` produces a new args dict, and the PDP returns it; the kernel applies it.

These are the "boring" constraints that make policy reasoning tractable.
