"""Phase P21 · Feb-2026 — Async startup init-state tracker.

Backs the "bind fast, init in background" split. The FastAPI lifespan
runs structural schema/index migrations synchronously BEFORE the yield
so the pod never accepts requests against a half-migrated schema, then
kicks two background tasks (SEED → INTEGRITY_SCAN, chained) whose
progress is recorded here.

The dataclass shape is exported over ``/api/health`` so ops sees each
task's ``status``, ``duration_ms``, ``retry_count``, and ``error``
without needing to grep supervisor logs.

Rules of the shape:
  * ``TaskStatus`` is a str-enum so it JSON-serializes cleanly via
    FastAPI's default encoder.
  * ``TaskRecord.to_dict`` is the wire shape read by the health probe;
    keep it stable so /api/health consumers can key on it.
  * ``InitState`` is process-local (mutated in place); the lifespan
    stores a single instance on ``app.state.init``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class TaskRecord:
    name: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> dict:
        """JSON-friendly projection for the health endpoint."""
        return {
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "retry_count": self.retry_count,
        }


@dataclass
class InitState:
    tasks: dict = field(default_factory=dict)
    schema_migrations_done_at: Optional[float] = None
    # P23.1 · Feb-2026 — per-structural-migration status. Keyed by
    # migration name (e.g. ``perf_customers_v1``,
    # ``p23_restore_ethan_steven_technicians``). Distinct from
    # ``tasks`` (which tracks the two post-yield background tasks —
    # ``seed`` and ``integrity_scan``) so the two lists render as
    # separate sub-objects on ``/api/health``. Populated by the
    # ``_run_structural_migration`` helper in ``server.py``.
    structural_migrations: dict = field(default_factory=dict)

    def mark_migrations_done(self) -> None:
        """Called by the lifespan the instant the last synchronous
        structural migration completes and the app is safe to serve.
        Also seeds the two known background tasks in ``pending`` state
        so ``/api/health`` reports them immediately after bind."""
        self.schema_migrations_done_at = time.time()
        for name in ("seed", "integrity_scan"):
            self.tasks.setdefault(name, TaskRecord(name=name))

    # ── P23.1 · Structural-migration state transitions ────────────
    # These mirror the shape of ``start`` / ``done`` / ``error``
    # above but operate on the ``structural_migrations`` dict so
    # boot-time schema/data migrations get their own status surface
    # without polluting the SEED / SCAN post-yield tracking.

    def start_structural(self, name: str) -> TaskRecord:
        rec = self.structural_migrations.setdefault(
            name, TaskRecord(name=name),
        )
        rec.status = TaskStatus.RUNNING
        rec.started_at = time.time()
        return rec

    def done_structural(self, name: str) -> None:
        rec = self.structural_migrations.get(name)
        if not rec:
            return
        rec.status = TaskStatus.DONE
        rec.finished_at = time.time()
        rec.duration_ms = int(
            (rec.finished_at - (rec.started_at or rec.finished_at)) * 1000,
        )
        rec.error = None

    def error_structural(self, name: str, exc: BaseException) -> None:
        rec = self.structural_migrations.get(name)
        if not rec:
            return
        rec.status = TaskStatus.ERROR
        rec.finished_at = time.time()
        rec.duration_ms = int(
            (rec.finished_at - (rec.started_at or rec.finished_at)) * 1000,
        )
        rec.error = str(exc)[:500]

    def start(self, name: str) -> TaskRecord:
        """Transition a task into RUNNING. Idempotent for reruns
        (retry path) — keeps the same TaskRecord in place so
        ``retry_count`` accumulates across attempts."""
        rec = self.tasks.setdefault(name, TaskRecord(name=name))
        rec.status = TaskStatus.RUNNING
        rec.started_at = time.time()
        return rec

    def done(self, name: str) -> None:
        rec = self.tasks.get(name)
        if not rec:
            return
        rec.status = TaskStatus.DONE
        rec.finished_at = time.time()
        rec.duration_ms = int(
            (rec.finished_at - (rec.started_at or rec.finished_at)) * 1000,
        )
        rec.error = None

    def error(self, name: str, exc: BaseException) -> None:
        rec = self.tasks.get(name)
        if not rec:
            return
        rec.status = TaskStatus.ERROR
        rec.finished_at = time.time()
        rec.duration_ms = int(
            (rec.finished_at - (rec.started_at or rec.finished_at)) * 1000,
        )
        rec.error = str(exc)[:500]

    def bump_retry(self, name: str) -> None:
        rec = self.tasks.get(name)
        if rec:
            rec.retry_count += 1

    def health_snapshot(self) -> dict:
        """Wire shape consumed by ``GET /api/health``. ``status`` sits
        at the top level (``ok`` whenever ``schema_migrations_done_at``
        is stamped) — seed/scan progress lives under ``init.*`` and
        NEVER downgrades the top-level status. The health probe is
        never allowed to return non-200 solely because a background
        seed hasn't finished.

        P23.1 · Feb-2026 — includes a ``structural_migrations``
        sub-object keyed by migration name so ops has a single JSON
        surface to grep for a boot-time migration failure. Absent
        migrations are omitted from the payload; any ``status ==
        "error"`` entry is the on-call ping condition.
        """
        return {
            "schema_migrations": (
                "done" if self.schema_migrations_done_at else "pending"
            ),
            "structural_migrations": {
                name: rec.to_dict()
                for name, rec in self.structural_migrations.items()
            },
            "seed": self.tasks.get(
                "seed", TaskRecord(name="seed"),
            ).to_dict(),
            "integrity_scan": self.tasks.get(
                "integrity_scan", TaskRecord(name="integrity_scan"),
            ).to_dict(),
        }
