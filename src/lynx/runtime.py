"""Public Runtime facade.

This is what most users touch. Wraps Scheduler + Store + Policy into a small
API: run / resume / replay / approve.
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from typing import Any

from lynx.core.mediator import get_broker
from lynx.core.policy import PolicyBundle, load_policy_file
from lynx.core.scheduler import RunResult, Scheduler
from lynx.core.types import Budget, Principal
from lynx.sdk import Agent
from lynx.stores.sqlite import SQLiteStore


class Runtime:
    """The public surface — one object, a handful of methods.

    For most users::

        from lynx import runtime

        result = await runtime.run(agent, task="...", policy="policy.yaml")
    """

    def __init__(
        self,
        store: SQLiteStore | None = None,
        policy: PolicyBundle | None = None,
    ) -> None:
        self._store = store
        self._policy = policy
        self._scheduler: Scheduler | None = None

    # -----------------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------------

    def configure(
        self,
        store_path: str | Path = ".lynx/state.db",
        policy_path: str | Path | None = None,
    ) -> None:
        if self._store is None:
            self._store = SQLiteStore(store_path)
        if policy_path is not None:
            self._policy = load_policy_file(policy_path)
        if self._store is not None and self._policy is not None:
            self._scheduler = Scheduler(self._store, self._policy)

    def _ensure_ready(self, policy_path: str | Path | None = None) -> Scheduler:
        if self._store is None:
            self._store = SQLiteStore()
        if self._policy is None:
            if policy_path is None:
                policy_path = Path("policy.yaml")
            self._policy = load_policy_file(policy_path)
        if self._scheduler is None or self._scheduler.bundle.id != self._policy.id:
            self._scheduler = Scheduler(self._store, self._policy)
        return self._scheduler

    @property
    def store(self) -> SQLiteStore:
        if self._store is None:
            self._store = SQLiteStore()
        return self._store

    # -----------------------------------------------------------------------
    # Run / Resume
    # -----------------------------------------------------------------------

    async def run(
        self,
        agent: Agent,
        task: str,
        policy: str | Path | None = None,
        budget: dict[str, Any] | Budget | None = None,
        principal: dict[str, Any] | Principal | None = None,
        environment: str = "dev",
        workspace: str = ".",
    ) -> RunResult:
        scheduler = self._ensure_ready(policy)
        budget_obj = _coerce_budget(budget)
        principal_obj = _coerce_principal(principal)
        return await scheduler.start(
            agent=agent,
            goal=task,
            principal=principal_obj,
            environment=environment,
            workspace=workspace,
            budget=budget_obj,
        )

    def run_sync(self, *args: Any, **kwargs: Any) -> RunResult:
        return asyncio.run(self.run(*args, **kwargs))

    async def resume(self, agent: Agent, run_id: str, approver: str | None = None) -> RunResult:
        scheduler = self._ensure_ready()
        return await scheduler.resume(agent, run_id, approver=approver)

    # -----------------------------------------------------------------------
    # Approvals
    # -----------------------------------------------------------------------

    async def approve(self, approval_id: str, approver: str) -> None:
        """Mark an approval as granted. Persists to DB so resume works after restart."""
        from datetime import datetime

        try:
            get_broker().grant(approval_id, approver)
        except KeyError:
            # The broker is in-process; on a fresh process it has no record.
            # That's fine — the DB is the source of truth.
            pass
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE approval_requests SET status='granted', granted_by=?, "
                "resolved_at=? WHERE id=?",
                (approver, datetime.now(UTC).isoformat(), approval_id),
            )

    async def deny(self, approval_id: str, approver: str, reason: str = "") -> None:
        from datetime import datetime

        try:
            get_broker().deny(approval_id, approver)
        except KeyError:
            pass
        with self.store._conn:
            self.store._conn.execute(
                "UPDATE approval_requests SET status='denied', granted_by=?, "
                "resolved_at=? WHERE id=?",
                (approver, datetime.now(UTC).isoformat(), approval_id),
            )

    # -----------------------------------------------------------------------
    # Read APIs (used by CLI and any future UI)
    # -----------------------------------------------------------------------

    def list_runs(self, limit: int = 50) -> list[Any]:
        return self.store.list_runs(limit=limit)

    def get_run(self, run_id: str) -> Any:
        return self.store.get_run(run_id)

    def get_steps(self, run_id: str) -> list[Any]:
        return self.store.get_steps(run_id)

    def audit_chain(self, run_id: str) -> Any:
        return list(self.store.audit_chain(run_id))

    def verify_audit(self, run_id: str) -> tuple[bool, str | None]:
        return self.store.verify_audit_chain(run_id)


# Module-level singleton — like `requests.get`, `runtime.run` is the entry point.
runtime = Runtime()


# ---------------------------------------------------------------------------
# Coercion helpers — let users pass dicts instead of dataclasses
# ---------------------------------------------------------------------------


def _coerce_budget(b: dict[str, Any] | Budget | None) -> Budget:
    if b is None:
        return Budget(steps=50, duration_seconds=600)
    if isinstance(b, Budget):
        return b
    return Budget(**b)


def _coerce_principal(p: dict[str, Any] | Principal | None) -> Principal:
    if p is None:
        return Principal(kind="user", id="anonymous")
    if isinstance(p, Principal):
        return p
    return Principal(**p)
