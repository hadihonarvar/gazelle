"""Tests for core type helpers — IDs, canonical JSON, audit event hashing."""

from __future__ import annotations

from gazelle.core.types import (
    AuditEvent,
    canonical_json,
    compute_idempotency_key,
    new_id,
)


def test_new_id_prefix() -> None:
    assert new_id("T").startswith("T-")
    assert new_id("R").startswith("R-")
    # ULIDs are 26 chars; with prefix "X-" → 28
    assert len(new_id("T")) == 28


def test_canonical_json_is_stable() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_idempotency_key_deterministic() -> None:
    k1 = compute_idempotency_key("R1", 5, "shell", {"cmd": "ls"})
    k2 = compute_idempotency_key("R1", 5, "shell", {"cmd": "ls"})
    k3 = compute_idempotency_key("R1", 5, "shell", {"cmd": "lsa"})
    assert k1 == k2
    assert k1 != k3


def test_audit_event_id_is_content_addressed() -> None:
    e1 = AuditEvent.build(prev="0" * 64, run_id="R", seq=0, kind="x", body={"a": 1})
    # Recompute id from canonical payload
    import hashlib

    recomputed = hashlib.sha256(
        canonical_json(
            {
                "prev": e1.prev,
                "run_id": e1.run_id,
                "seq": e1.seq,
                "kind": e1.kind,
                "timestamp": e1.timestamp.isoformat(),
                "body": e1.body,
            }
        ).encode()
    ).hexdigest()
    assert recomputed == e1.id
