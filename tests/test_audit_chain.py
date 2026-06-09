"""Property + tampering tests for the audit chain."""

from __future__ import annotations

import pytest

from gazelle.core.types import (
    GENESIS_HASH,
    AuditEvent,
    canonical_json,
)
from gazelle.stores.sqlite import SQLiteStore


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(tmp_path / "state.db")


def _append(store: SQLiteStore, run_id: str, seq: int, kind: str, body: dict) -> AuditEvent:
    prev = store.latest_audit_hash(run_id)
    event = AuditEvent.build(prev=prev, run_id=run_id, seq=seq, kind=kind, body=body)
    store.append_audit(event)
    return event


def test_chain_starts_at_genesis(store):
    e0 = _append(store, "R-1", 0, "start", {"x": 1})
    assert e0.prev == GENESIS_HASH


def test_chain_links_consecutively(store):
    e0 = _append(store, "R-1", 0, "start", {"x": 1})
    e1 = _append(store, "R-1", 1, "next", {"y": 2})
    assert e1.prev == e0.id


def test_verify_clean_chain(store):
    for i, kind in enumerate(["start", "next", "next", "end"]):
        _append(store, "R-1", i, kind, {"i": i})
    ok, err = store.verify_audit_chain("R-1")
    assert ok, f"expected clean: {err}"


def test_verify_detects_tampered_body(store):
    _append(store, "R-1", 0, "start", {"x": 1})
    _append(store, "R-1", 1, "next", {"y": 2})

    # Tamper: rewrite the body of event 1, leaving its id alone.
    with store._conn:
        store._conn.execute(
            "UPDATE audit_events SET body=? WHERE run_id=? AND seq=?",
            (canonical_json({"y": 999}), "R-1", 1),
        )

    ok, err = store.verify_audit_chain("R-1")
    assert ok is False
    assert err is not None


def test_verify_detects_missing_event(store):
    for i in range(3):
        _append(store, "R-1", i, "k", {"i": i})

    # Delete the middle event entirely.
    with store._conn:
        store._conn.execute("DELETE FROM audit_events WHERE run_id=? AND seq=1", ("R-1",))

    ok, err = store.verify_audit_chain("R-1")
    assert ok is False
    assert "seq" in (err or "")
