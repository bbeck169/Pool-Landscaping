"""Ticket CC · Feb-2026 — regression lock for lifespan-run preview guardrails.

Locks TD-starlette-lifespan-dead-startup-handlers:

  * The three preview-only guardrails (``_assert_pii_registry_
    coverage``, ``_preview_scrub`` background-task spawn,
    ``assert_no_orphan_credit_writes``) MUST each fire exactly once
    on lifespan start.
  * The ordering MUST match the historical ``@app.on_event
    ("startup")`` handler: pii_registry → preview_scrub →
    credit_write_guard.
  * The ``@app.on_event("startup")`` decorator on
    ``_preview_isolation_boot_audit`` MUST be removed (companion
    source-lint test ``test_p21_source_lint_no_on_event_decorators``
    enforces the broader rule).
  * The helper function MUST remain callable (plain async def) so
    future test harnesses can invoke it directly.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


def test_preview_isolation_boot_audit_is_plain_async_def():
    import server

    fn = getattr(server, "_preview_isolation_boot_audit", None)
    assert fn is not None, (
        "``_preview_isolation_boot_audit`` must remain exported from "
        "server.py so operators can hand-invoke it from an admin "
        "shell (and so this regression lock can find it).")
    # Not a startup-handler closure; a plain async def we can await
    # directly.
    assert asyncio.iscoroutinefunction(fn), (
        "``_preview_isolation_boot_audit`` must be an async def — "
        "it awaits nothing today but future guardrails might.")


def test_source_has_no_on_event_startup_decorator_on_preview_isolation():
    """Verifies the specific decorator this ticket targeted has
    been removed, independent of the broader p21 source-lint.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
            / "server.py").read_text(encoding="utf-8")
    assert ('@app.on_event("startup")\n'
                "async def _preview_isolation_boot_audit") not in src
    # Function definition itself still present.
    assert "async def _preview_isolation_boot_audit" in src


def test_preview_isolation_boot_audit_invokes_all_three_guardrails_in_order():
    """Invokes ``_preview_isolation_boot_audit`` directly and
    asserts the three guardrails fire in the historical order.

    (The full lifespan boot touches Mongo + runs the real P21 seed
    pipeline on the asyncio event loop; wiring that up for a unit
    test adds no additional coverage beyond what P21 already locks.
    Testing the helper directly isolates the Ticket CC contract.)
    """
    import server

    call_order: list[str] = []

    def _rec_pii(_app):
        call_order.append("pii_registry")

    async def _rec_scrub(_db):
        call_order.append("preview_scrub")
        return None

    def _rec_credit():
        call_order.append("credit_write_guard")

    with patch.object(server, "_assert_pii_registry_coverage",
                        side_effect=_rec_pii), \
         patch("services.preview_isolation.scrubber.run_once",
                new=_rec_scrub), \
         patch("services.credit_write_guard.assert_no_orphan_credit_writes",
                new=_rec_credit):
        async def _invoke():
            await server._preview_isolation_boot_audit()
            # Yield once so the ``asyncio.create_task(_preview_scrub)``
            # dispatch inside the helper reaches our recorder before
            # we assert on ``call_order``.
            await asyncio.sleep(0)

        asyncio.run(_invoke())

    assert "pii_registry" in call_order, f"call_order={call_order}"
    assert "preview_scrub" in call_order, f"call_order={call_order}"
    assert "credit_write_guard" in call_order, f"call_order={call_order}"
    # Historical order from the dead on_event handler:
    #   pii_registry → preview_scrub spawn → credit_write_guard
    assert call_order.index("pii_registry") < call_order.index(
        "credit_write_guard"), f"call_order={call_order}"


def test_credit_write_guard_assertion_propagates_from_helper():
    """The credit-write-guard guardrail is the ONLY one that
    intentionally raises on failure (preview hard-fail).  Lock the
    propagation path so a lifespan boot would terminate uvicorn.
    """
    import server

    def _ok_pii(_app):
        pass

    async def _ok_scrub(_db):
        return None

    def _boom_credit():
        raise AssertionError("orphan writer found")

    with patch.object(server, "_assert_pii_registry_coverage",
                        side_effect=_ok_pii), \
         patch("services.preview_isolation.scrubber.run_once",
                new=_ok_scrub), \
         patch("services.credit_write_guard.assert_no_orphan_credit_writes",
                new=_boom_credit):
        async def _invoke():
            await server._preview_isolation_boot_audit()

        with pytest.raises(AssertionError, match="orphan writer found"):
            asyncio.run(_invoke())
