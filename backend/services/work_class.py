"""Work-class dimension helpers — Feb 2026.

The ``work_class`` field on ``db.jobs`` docs is orthogonal to
``job_type`` (which classifies the discipline — ``"pool"`` /
``"landscaping"``). Values:

* ``"service"`` — a routine visit (weekly pool clean, chem delivery,
  landscape mow, etc.). Default.
* ``"repair"`` — a fix-something visit (pump repair, leak, broken
  valve, etc.).

Read-time invariant: any job doc missing ``work_class`` (legacy rows
predating this ship) is treated as ``"service"``. No backfill needed
— callers use :func:`infer_work_class` on read and any counter split
uses ``total − repair = service`` so legacy rows land in the service
bucket automatically.

Write-time invariant: the two write paths that accept ``work_class``
(``POST /api/jobs`` and ``PATCH /api/jobs/{jid}``) run every value
through :func:`normalize_work_class`, which raises ``ValueError`` on
anything but the two literal values. Routers translate to HTTP 400.
"""
from __future__ import annotations

from typing import Any, Optional

_VALID: frozenset = frozenset({"service", "repair"})


def normalize_work_class(value: Optional[str]) -> str:
    """Return a normalized ``work_class`` value.

    Accepts ``None`` → ``"service"`` (default). Case-insensitive on
    the two literal values. Anything else raises ``ValueError``.
    """
    if value is None:
        return "service"
    s = str(value).strip().lower()
    if s == "":
        return "service"
    if s in _VALID:
        return s
    raise ValueError(f"invalid work_class: {value!r} (want 'service' or 'repair')")


def infer_work_class(job: Any) -> str:
    """Read-time fallback for legacy jobs.

    Returns ``"service"`` for any job doc that doesn't carry a
    literal ``"repair"`` value. Never raises — safe to call on any
    dict-shaped or ``None`` input.
    """
    if not isinstance(job, dict):
        return "service"
    v = job.get("work_class")
    if isinstance(v, str) and v.strip().lower() == "repair":
        return "repair"
    return "service"
