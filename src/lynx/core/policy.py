"""Policy compiler + Policy Decision Point (PDP).

Pure functions; the PDP takes (bundle, request, context) and returns a Decision.
No module-level state. Python rules are passed explicitly to ``compile_policy``;
no ``@rule`` decorator with a hidden registry.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lynx.core.types import (
    ActionRequest,
    Decision,
    ExecutionContext,
    Verdict,
    canonical_json,
)

__all__ = [
    "PolicyBundle",
    "PolicyCompileError",
    "PolicyDefaults",
    "PythonRule",
    "allow",
    "approve_required",
    "compile_policy",
    "deny",
    "dry_run",
    "evaluate",
    "load_policy_file",
    "transform",
]


class PolicyCompileError(ValueError):
    """Raised when a policy YAML cannot be compiled into a PolicyBundle.

    Wraps PyYAML parse errors, unknown operators, malformed rules, and
    ReDoS-guard regex rejections. Catch this one type to surface a friendly
    error to operators.
    """


# ---------------------------------------------------------------------------
# Public Decision constructors (used in Python rules + tests)
# ---------------------------------------------------------------------------


def allow(reason: str = "", matched_rules: tuple[str, ...] = ()) -> Decision:
    return Decision(verdict=Verdict.ALLOW, reason=reason, matched_rules=matched_rules)


def deny(reason: str, matched_rules: tuple[str, ...] = ()) -> Decision:
    return Decision(verdict=Verdict.DENY, reason=reason, matched_rules=matched_rules)


def dry_run(reason: str = "", matched_rules: tuple[str, ...] = ()) -> Decision:
    return Decision(verdict=Verdict.DRY_RUN, reason=reason, matched_rules=matched_rules)


def approve_required(
    approvers: tuple[str, ...] = (),
    timeout_seconds: int = 1800,
    reason: str = "",
    matched_rules: tuple[str, ...] = (),
) -> Decision:
    return Decision(
        verdict=Verdict.APPROVE_REQUIRED,
        reason=reason,
        matched_rules=matched_rules,
        approvers=approvers,
        timeout_seconds=timeout_seconds,
    )


def transform(
    transform_args: Mapping[str, Any],
    reason: str = "",
    matched_rules: tuple[str, ...] = (),
) -> Decision:
    return Decision(
        verdict=Verdict.TRANSFORM,
        reason=reason,
        matched_rules=matched_rules,
        transform_args=transform_args,
    )


# ---------------------------------------------------------------------------
# Bundle types (frozen)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyDefaults:
    on_missing_shadow: Verdict = Verdict.APPROVE_REQUIRED
    on_no_match: Verdict = Verdict.DENY


@dataclass(frozen=True, slots=True)
class CompiledRule:
    id: str
    priority: int
    description: str
    matcher: Callable[[ActionRequest, ExecutionContext], bool]
    decision_factory: Callable[[ActionRequest, ExecutionContext], Decision]
    source_location: str
    # Sort index — used as the tie-break after -priority so file order is
    # preserved correctly past 10 rules at the same priority.
    order: int = 0


# A PythonRule is just any callable matching this shape.
PythonRule = Callable[[ActionRequest, ExecutionContext], "Decision | None"]


@dataclass(frozen=True, slots=True)
class _EvalStep:
    """One entry in the unified evaluation order (Python + YAML interleaved)."""

    rule_id: str
    priority: int
    order: int
    kind: str  # "python" | "yaml"
    fn: Callable[[ActionRequest, ExecutionContext], Decision | None]


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    id: str
    version: int
    rules: tuple[CompiledRule, ...]
    python_rules: tuple[tuple[str, int, PythonRule], ...]
    defaults: PolicyDefaults
    source_files: tuple[str, ...] = ()
    # Interleaved evaluation order — Python and YAML rules merged into a single
    # priority-ordered list so a higher-priority YAML rule beats a lower-priority
    # Python rule (and vice versa). Defaults to empty tuple for backward compat;
    # populated by ``compile_policy``.
    eval_order: tuple[_EvalStep, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Matcher compilation
# ---------------------------------------------------------------------------


PathFn = Callable[[ActionRequest, ExecutionContext], Any]


def _path_getter(dotted: str) -> PathFn:
    parts = dotted.split(".")

    def get(req: ActionRequest, ctx: ExecutionContext) -> Any:
        if parts[0] == "tool":
            return req.tool
        if parts[0] == "args":
            cur: Any = req.args
            for p in parts[1:]:
                if isinstance(cur, Mapping):
                    cur = cur.get(p)
                else:
                    return None
            return cur
        if parts[0] == "declared":
            cur = req.declared
            for p in parts[1:]:
                cur = getattr(cur, p, None)
            return cur
        if parts[0] == "context":
            cur = req.context
            for p in parts[1:]:
                if isinstance(cur, Mapping):
                    cur = cur.get(p)
                else:
                    cur = getattr(cur, p, None)
            return cur
        return None

    return get


_MAX_REGEX_LENGTH = 1000
_REGEX_DANGEROUS_PATTERNS = (
    re.compile(r"\(\s*\\?[wWsSdD.]\s*[\*\+]\s*\)\s*[\*\+]"),
    re.compile(r"\(\s*[a-zA-Z0-9]\s*[\*\+]\s*\)\s*[\*\+]"),
    re.compile(r"\(\s*([^)|]+)\s*\|\s*\1\s*\)\s*[\*\+]"),
)


def _compile_safe_regex(pattern: str) -> re.Pattern[str]:
    if len(pattern) > _MAX_REGEX_LENGTH:
        raise PolicyCompileError(f"Regex pattern too long ({len(pattern)} > {_MAX_REGEX_LENGTH})")
    for danger in _REGEX_DANGEROUS_PATTERNS:
        if danger.search(pattern):
            raise PolicyCompileError(
                f"Regex pattern {pattern!r} contains a nested unbounded "
                "quantifier; would be vulnerable to catastrophic backtracking"
            )
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise PolicyCompileError(f"Invalid regex {pattern!r}: {exc}") from exc


_OPERATORS = {
    "matches",
    "in",
    "contains",
    "contains_any",
    "contains_all",
    "gt",
    "ge",
    "lt",
    "le",
    "between",
    "not_between",
    "eq",
}


def _compile_predicate(
    spec: Mapping[str, Any] | str,
    predicates: Mapping[str, Mapping[str, Any]],
) -> Callable[[ActionRequest, ExecutionContext], bool]:
    if isinstance(spec, str):
        if spec not in predicates:
            suggestion = difflib.get_close_matches(spec, list(predicates), n=1, cutoff=0.6)
            hint = f" (did you mean {suggestion[0]!r}?)" if suggestion else ""
            raise PolicyCompileError(f"Unknown predicate: {spec!r}{hint}")
        return _compile_predicate(predicates[spec], predicates)

    if not isinstance(spec, Mapping):
        raise PolicyCompileError(f"Predicate must be Mapping or predicate name, got: {spec!r}")

    leaves: list[Callable[[ActionRequest, ExecutionContext], bool]] = []

    for key, value in spec.items():
        if key == "all_of":
            sub = [_compile_predicate(s, predicates) for s in value]
            leaves.append(lambda r, c, sub=sub: all(p(r, c) for p in sub))
        elif key == "any_of":
            sub = [_compile_predicate(s, predicates) for s in value]
            leaves.append(lambda r, c, sub=sub: any(p(r, c) for p in sub))
        elif key == "not":
            inner = _compile_predicate(value, predicates)
            leaves.append(lambda r, c, inner=inner: not inner(r, c))
        else:
            leaves.append(_compile_leaf(key, value))

    return lambda r, c, leaves=leaves: all(p(r, c) for p in leaves)


def _compile_leaf(key: str, value: Any) -> Callable[[ActionRequest, ExecutionContext], bool]:
    if "." in key:
        head, _, tail = key.rpartition(".")
        if tail in _OPERATORS:
            getter = _path_getter(head)
            return _operator_check(getter, tail, value)
        # Operator-shaped typo guard: a trailing segment that is a close miss
        # of a known operator is almost certainly a typo, not a literal field
        # name. Silent-fail would just be a never-matching rule.
        suggestion = difflib.get_close_matches(tail, sorted(_OPERATORS), n=1, cutoff=0.75)
        if suggestion:
            raise PolicyCompileError(
                f"Unknown operator suffix on {key!r}: "
                f"{tail!r} looks like a typo of {suggestion[0]!r}. "
                f"Known operators: {sorted(_OPERATORS)}"
            )
    getter = _path_getter(key)
    return lambda r, c, getter=getter, value=value: getter(r, c) == value


def _operator_check(
    getter: PathFn, op: str, value: Any
) -> Callable[[ActionRequest, ExecutionContext], bool]:
    if op == "eq":
        return lambda r, c: getter(r, c) == value
    if op == "matches":
        pat = _compile_safe_regex(value)

        def check_matches(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            return isinstance(v, str) and pat.search(v) is not None

        return check_matches
    if op == "in":
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise PolicyCompileError(
                f"`in` operator requires a list/tuple/set on the right-hand side, "
                f"got {type(value).__name__}: {value!r}"
            )
        rhs = (
            frozenset(value)
            if all(isinstance(x, (str, int, float, bool)) for x in value)
            else tuple(value)
        )
        return lambda r, c: getter(r, c) in rhs
    if op == "contains":

        def check_contains(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            return v is not None and value in v

        return check_contains
    if op == "contains_any":

        def check_contains_any(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            if v is None:
                return False
            return any(item in v for item in value)

        return check_contains_any
    if op == "contains_all":

        def check_contains_all(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            if v is None:
                return False
            return all(item in v for item in value)

        return check_contains_all
    if op in {"gt", "ge", "lt", "le"}:
        cmp_fn = {
            "gt": lambda a, b: a > b,
            "ge": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "le": lambda a, b: a <= b,
        }[op]

        def check_cmp(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            return v is not None and cmp_fn(v, value)

        return check_cmp
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise PolicyCompileError(
                f"`between` operator requires a 2-element list/tuple [lo, hi], got: {value!r}"
            )
        lo, hi = value
        if lo > hi:
            raise PolicyCompileError(f"`between` operator: lo > hi ({lo} > {hi}); range is empty")

        def check_between(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            return v is not None and lo <= v <= hi

        return check_between
    if op == "not_between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise PolicyCompileError(
                f"`not_between` operator requires a 2-element list/tuple [lo, hi], got: {value!r}"
            )
        lo, hi = value

        def check_not_between(r: ActionRequest, c: ExecutionContext) -> bool:
            v = getter(r, c)
            return v is not None and not (lo <= v <= hi)

        return check_not_between
    raise PolicyCompileError(f"Unknown operator: {op}")


# ---------------------------------------------------------------------------
# Decision factory compilation
# ---------------------------------------------------------------------------


def _parse_verdict(value: Any, rule_id: str) -> Verdict:
    """Verdict() is case-sensitive ('allow' only). Accept upper-case in YAML."""
    if isinstance(value, Verdict):
        return value
    if not isinstance(value, str):
        raise PolicyCompileError(
            f"Rule {rule_id!r}: verdict must be a string, got {type(value).__name__}"
        )
    try:
        return Verdict(value.lower())
    except ValueError as exc:
        valid = [v.value for v in Verdict]
        raise PolicyCompileError(
            f"Rule {rule_id!r}: unknown verdict {value!r}; valid: {valid}"
        ) from exc


def _compile_decision(
    raw: Mapping[str, Any] | str, rule_id: str
) -> Callable[[ActionRequest, ExecutionContext], Decision]:
    if isinstance(raw, str):
        return _simple_decision(raw, rule_id)

    verdict_str = raw.get("verdict") or raw.get("decision") or "deny"
    verdict = _parse_verdict(verdict_str, rule_id)
    reason = raw.get("reason", "")
    approvers = tuple(raw.get("approvers", ()))
    timeout = raw.get("timeout_seconds")
    transform_spec = raw.get("transform")

    if verdict == Verdict.TRANSFORM and transform_spec is None:
        raise PolicyCompileError(
            f"Rule {rule_id!r}: decision is 'transform' but no `transform:` block given. "
            "A transform rule must specify at least one of set/append/delete."
        )
    if verdict != Verdict.TRANSFORM and transform_spec is not None:
        raise PolicyCompileError(
            f"Rule {rule_id!r}: `transform:` block only applies to a transform decision"
        )
    if transform_spec is not None:
        _validate_transform_spec(transform_spec, rule_id)

    def factory(req: ActionRequest, ctx: ExecutionContext) -> Decision:
        return Decision(
            verdict=verdict,
            reason=reason,
            matched_rules=(rule_id,),
            approvers=approvers,
            timeout_seconds=timeout,
            transform_args=_apply_transform(transform_spec, req) if transform_spec else None,
        )

    return factory


def _simple_decision(
    name: str, rule_id: str
) -> Callable[[ActionRequest, ExecutionContext], Decision]:
    v = _parse_verdict(name, rule_id)
    if v == Verdict.TRANSFORM:
        raise PolicyCompileError(
            f"Rule {rule_id!r}: short-form `decision: transform` is not allowed; "
            "transform rules need an explicit `transform:` block."
        )
    return lambda r, c: Decision(verdict=v, matched_rules=(rule_id,))


_TRANSFORM_OPS = {"set", "append", "delete"}


def _validate_transform_spec(spec: Mapping[str, Any], rule_id: str) -> None:
    if not isinstance(spec, Mapping):
        raise PolicyCompileError(
            f"Rule {rule_id!r}: transform must be a mapping, got {type(spec).__name__}"
        )
    used = _TRANSFORM_OPS & set(spec)
    if not used:
        raise PolicyCompileError(
            f"Rule {rule_id!r}: transform must declare at least one of {sorted(_TRANSFORM_OPS)}"
        )
    if len(used) > 1:
        raise PolicyCompileError(
            f"Rule {rule_id!r}: transform may declare only one of {sorted(used)} per rule"
        )
    jsonpath = spec.get("jsonpath", "$.args")
    if not isinstance(jsonpath, str) or not jsonpath.startswith("$.args"):
        raise PolicyCompileError(
            f"Rule {rule_id!r}: transform jsonpath must start with '$.args' "
            f"(got {jsonpath!r}). Only top-level `args.<key>` rewrites are supported."
        )


def _apply_transform(spec: Mapping[str, Any], req: ActionRequest) -> Mapping[str, Any]:
    new_args: dict[str, Any] = dict(req.args)
    target = spec.get("jsonpath", "$.args").removeprefix("$.args.")
    if "set" in spec:
        new_args[target] = spec["set"]
    elif "append" in spec:
        cur = new_args.get(target, "")
        new_args[target] = str(cur) + str(spec["append"])
    elif "delete" in spec:
        new_args.pop(target, None)
    return new_args


# ---------------------------------------------------------------------------
# Compile entrypoint
# ---------------------------------------------------------------------------


def compile_policy(
    source: str | Mapping[str, Any],
    source_path: str = "<inline>",
    *,
    python_rules: tuple[PythonRule, ...] = (),
    python_rule_priorities: tuple[tuple[str, int], ...] = (),
) -> PolicyBundle:
    """Compile YAML (or dict) into a frozen PolicyBundle.

    Python rules are passed in explicitly — no module-level registry.
    Each Python rule must be a callable ``(ActionRequest, ExecutionContext) -> Decision | None``.

    Raises :class:`PolicyCompileError` for any malformed input.
    """
    if isinstance(source, str):
        try:
            loaded = yaml.safe_load(source) or {}
        except yaml.YAMLError as exc:
            raise PolicyCompileError(f"YAML parse error: {exc}") from exc
    else:
        loaded = source
    if not isinstance(loaded, Mapping):
        raise PolicyCompileError(f"Policy root must be a mapping, got {type(loaded).__name__}")
    data: Mapping[str, Any] = loaded

    try:
        version = int(data.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise PolicyCompileError(
            f"version must be an integer, got {data.get('version')!r}"
        ) from exc

    defaults_raw = data.get("defaults", {}) or {}
    defaults = PolicyDefaults(
        on_missing_shadow=_parse_verdict(
            defaults_raw.get("on_missing_shadow", Verdict.APPROVE_REQUIRED.value),
            "<defaults.on_missing_shadow>",
        ),
        on_no_match=_parse_verdict(
            defaults_raw.get("on_no_match", Verdict.DENY.value),
            "<defaults.on_no_match>",
        ),
    )

    predicates: Mapping[str, Mapping[str, Any]] = data.get("predicates", {}) or {}

    rules: list[CompiledRule] = []
    rule_bodies_canonical: list[Any] = []  # for content-addressing bundle_id
    raw_rules = data.get("rules", []) or []
    for idx, rspec in enumerate(raw_rules):
        if not isinstance(rspec, Mapping):
            raise PolicyCompileError(f"rules[{idx}] must be a mapping, got {type(rspec).__name__}")
        rid = rspec.get("id") or f"rule_{idx}"
        try:
            priority = int(rspec.get("priority", 0))
        except (TypeError, ValueError) as exc:
            raise PolicyCompileError(
                f"Rule {rid!r}: priority must be an integer, got {rspec.get('priority')!r}"
            ) from exc
        description = rspec.get("description", "")
        match = rspec.get("match", {})
        matcher = _compile_predicate(match, predicates)
        decision_factory = _compile_decision(
            {
                "verdict": rspec.get("decision", rspec.get("verdict", "deny")),
                "reason": rspec.get("reason", ""),
                "approvers": rspec.get("approvers", []),
                "timeout_seconds": rspec.get("timeout_seconds"),
                "transform": rspec.get("transform"),
            },
            rid,
        )
        rules.append(
            CompiledRule(
                id=rid,
                priority=priority,
                description=description,
                matcher=matcher,
                decision_factory=decision_factory,
                source_location=f"{source_path}:rule[{idx}]",
                order=idx,
            )
        )
        rule_bodies_canonical.append(
            {
                "id": rid,
                "priority": priority,
                "match": _canonical_predicate(match, predicates),
                "decision": {
                    "verdict": _verdict_canonical(
                        rspec.get("decision", rspec.get("verdict", "deny"))
                    ),
                    "approvers": list(rspec.get("approvers", []) or []),
                    "timeout_seconds": rspec.get("timeout_seconds"),
                    "transform": dict(rspec.get("transform") or {}),
                    "reason": rspec.get("reason", ""),
                },
            }
        )

    # Stable sort: priority desc, then file order (integer).
    rules.sort(key=lambda r: (-r.priority, r.order))

    # Python rule priorities: default 0; user can override via the second tuple.
    priority_map: Mapping[str, int] = dict(python_rule_priorities)
    py_rules_compiled: tuple[tuple[str, int, PythonRule], ...] = tuple(
        sorted(
            ((fn.__name__, priority_map.get(fn.__name__, 0), fn) for fn in python_rules),
            key=lambda t: -t[1],
        )
    )

    # Unified evaluation order — interleaved by priority. Python rules return
    # Decision | None (None = abstain); YAML rules match-and-decide via the
    # returned _yaml_eval closures (None = no-match).
    eval_steps: list[_EvalStep] = []
    for r in rules:
        eval_steps.append(
            _EvalStep(
                rule_id=r.id,
                priority=r.priority,
                order=r.order,
                kind="yaml",
                fn=_make_yaml_eval(r),
            )
        )
    for py_order, (name, prio, fn) in enumerate(py_rules_compiled):
        eval_steps.append(
            _EvalStep(
                rule_id=name,
                priority=prio,
                # Python rules sort *after* equal-priority YAML rules for stability.
                order=10**9 + py_order,
                kind="python",
                fn=_make_python_eval(name, fn),
            )
        )
    eval_steps.sort(key=lambda s: (-s.priority, s.order))

    # Content-addressed bundle id — covers rule bodies, defaults, version,
    # and python-rule names+priorities.
    bundle_id = hashlib.sha256(
        canonical_json(
            {
                "version": version,
                "defaults": {
                    "on_missing_shadow": defaults.on_missing_shadow.value,
                    "on_no_match": defaults.on_no_match.value,
                },
                "rules": rule_bodies_canonical,
                "python_rules": [
                    {"name": name, "priority": prio} for name, prio, _ in py_rules_compiled
                ],
            }
        ).encode()
    ).hexdigest()[:16]

    return PolicyBundle(
        id=bundle_id,
        version=version,
        rules=tuple(rules),
        python_rules=py_rules_compiled,
        defaults=defaults,
        source_files=(source_path,),
        eval_order=tuple(eval_steps),
    )


def _make_yaml_eval(
    rule: CompiledRule,
) -> Callable[[ActionRequest, ExecutionContext], Decision | None]:
    def step(req: ActionRequest, ctx: ExecutionContext) -> Decision | None:
        if rule.matcher(req, ctx):
            return rule.decision_factory(req, ctx)
        return None

    return step


def _make_python_eval(
    name: str, fn: PythonRule
) -> Callable[[ActionRequest, ExecutionContext], Decision | None]:
    def step(req: ActionRequest, ctx: ExecutionContext) -> Decision | None:
        result = fn(req, ctx)
        if result is None:
            return None
        # Tag the python rule name in matched_rules.
        new_matched: tuple[str, ...] = (
            result.matched_rules if name in result.matched_rules else (*result.matched_rules, name)
        )
        return Decision(
            verdict=result.verdict,
            reason=result.reason or "",
            matched_rules=new_matched,
            approvers=result.approvers,
            transform_args=result.transform_args,
            timeout_seconds=result.timeout_seconds,
        )

    return step


def _verdict_canonical(value: Any) -> str:
    if isinstance(value, Verdict):
        return value.value
    if isinstance(value, str):
        return value.lower()
    return str(value)


def _canonical_predicate(spec: Any, predicates: Mapping[str, Mapping[str, Any]]) -> Any:
    """Inline named predicates so bundle_id hashes the same thing for two
    policies that compile to equivalent matchers."""
    if isinstance(spec, str):
        if spec in predicates:
            return _canonical_predicate(predicates[spec], predicates)
        # Not a predicate name — treat as a literal string value.
        return spec
    if isinstance(spec, Mapping):
        return {k: _canonical_predicate(v, predicates) for k, v in sorted(spec.items())}
    if isinstance(spec, (list, tuple)):
        return [_canonical_predicate(v, predicates) for v in spec]
    return spec


def load_policy_file(
    path: str | Path, *, python_rules: tuple[PythonRule, ...] = ()
) -> PolicyBundle:
    p = Path(path)
    try:
        text = p.read_text()
    except OSError as exc:
        raise PolicyCompileError(f"Cannot read policy file {p}: {exc}") from exc
    return compile_policy(text, source_path=str(p), python_rules=python_rules)


# ---------------------------------------------------------------------------
# PDP — pure
# ---------------------------------------------------------------------------


def evaluate(
    bundle: PolicyBundle,
    request: ActionRequest,
    context: ExecutionContext,
) -> Decision:
    """Pure: same (bundle, request, context) always returns the same Decision.

    Python and YAML rules are interleaved by priority. If a rule raises during
    evaluation it is recorded as a diagnostic marker in ``matched_rules`` (so
    the scheduler / sinks can surface it) and evaluation continues with the
    next rule. A buggy rule never silently fails-open.
    """
    eval_order = bundle.eval_order or _legacy_eval_order(bundle)
    errors: list[str] = []
    for step in eval_order:
        try:
            result = step.fn(request, context)
        except Exception as exc:
            errors.append(f"<rule_error:{step.rule_id}:{type(exc).__name__}>")
            continue
        if result is not None:
            if errors:
                return Decision(
                    verdict=result.verdict,
                    reason=result.reason,
                    matched_rules=(*errors, *result.matched_rules),
                    approvers=result.approvers,
                    transform_args=result.transform_args,
                    timeout_seconds=result.timeout_seconds,
                )
            return result

    if not request.declared.reversible and not request.declared.has_shadow:
        return Decision(
            verdict=bundle.defaults.on_missing_shadow,
            reason="irreversible action with no shadow; default policy",
            matched_rules=(*errors, "<default:on_missing_shadow>"),
        )
    return Decision(
        verdict=bundle.defaults.on_no_match,
        reason="no rule matched; default policy",
        matched_rules=(*errors, "<default:on_no_match>"),
    )


def _legacy_eval_order(bundle: PolicyBundle) -> tuple[_EvalStep, ...]:
    """Backward-compat fallback for bundles built before the eval_order field
    was added. New bundles always carry eval_order populated by compile_policy."""
    steps: list[_EvalStep] = []
    for r in bundle.rules:
        steps.append(
            _EvalStep(
                rule_id=r.id,
                priority=r.priority,
                order=r.order,
                kind="yaml",
                fn=_make_yaml_eval(r),
            )
        )
    for idx, (name, prio, fn) in enumerate(bundle.python_rules):
        steps.append(
            _EvalStep(
                rule_id=name,
                priority=prio,
                order=10**9 + idx,
                kind="python",
                fn=_make_python_eval(name, fn),
            )
        )
    steps.sort(key=lambda s: (-s.priority, s.order))
    return tuple(steps)
