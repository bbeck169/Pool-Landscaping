"""Feb-2026 · P34 — Contextvar-based gate-bypass marker for the
release worker.

When the release worker dispatches a previously-deferred SMS / email,
it re-enters the adapter's ``send_sms`` / ``send_email``. Without a
bypass, the adapter's quiet-hours gate could re-defer the same row if
the window closed between ``scheduled_for`` and ``now``. This
contextvar sentinel lets the worker skip the gate exactly once per
dispatched row (scoped to the current task via
``contextvars.ContextVar``)."""
from __future__ import annotations

import contextlib
import contextvars


_bypass = contextvars.ContextVar("p34_bypass_gate", default=False)


def is_bypassing() -> bool:
    return bool(_bypass.get())


@contextlib.contextmanager
def bypass_gate():
    """Marks the current task as bypassing the quiet-hours gate.
    Nested / re-entrant is fine — reset always restores the prior
    value."""
    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)
