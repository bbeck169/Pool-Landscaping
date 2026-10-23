"""TD-invoice-edit-forwardref · Feb-2026.

Regression test for the ``PydanticUserError`` that live-500'd every
request against ``/api/openapi.json`` after commit ``487c3e4d8``
(td-offline-bundle-tenant-cache · BE · Phase 2 Lane D).

Root cause: ``@invalidates_offline_bundle`` wraps ``patch_invoice``
with ``@functools.wraps``; combined with the ``body: InvoiceEditBody
= Body(...)`` annotation (explicit ``Body(...)`` wrapper + locally-
defined Pydantic model) FastAPI's schema builder resolved the body
type as ``Annotated[ForwardRef('InvoiceEditBody'), Body(...)]`` and
Pydantic's ``get_definitions`` raised ``PydanticUserError`` on every
schema introspection call.

Fix: ``patch_invoice`` no longer uses the decorator; instead the
handler calls an inline ``_invalidate_offline_bundle_for_user`` at
each success-return path.  This test imports the FastAPI app and
calls ``app.openapi()`` directly — exercises the exact code path
that previously 500'd without touching HTTP, auth, or the database.

The sibling 7 decorated handlers in ``routers.jobs`` /
``routers.quotes`` are NOT regressed by this change — their body
types don't trigger the same ForwardRef resolution (see
``TD-invalidates-offline-bundle-forwardref-safe`` recon notes).
"""
from __future__ import annotations


def test_openapi_schema_builds_after_patch_invoice_decorator_removal() -> None:
    """``app.openapi()`` must succeed.  Prior to this fix it raised
    ``pydantic.errors.PydanticUserError: TypeAdapter[...ForwardRef
    ('InvoiceEditBody')...] is not fully defined`` and every
    ``GET /api/openapi.json`` returned 500.
    """
    import server  # noqa: PLC0415 — local import to surface missing deps clearly.

    schema = server.app.openapi()

    assert schema.get("openapi"), "openapi version missing"
    paths = schema.get("paths") or {}
    # The ``patch_invoice`` route is the one that previously blew
    # up schema generation.  Prefix is stamped on by the router
    # include in ``server.py`` (``/api`` + the router's
    # ``/quotes/{invoice_id}``).
    patch_invoice_path = "/api/quotes/{invoice_id}"
    assert patch_invoice_path in paths, (
        f"{patch_invoice_path} missing from openapi.paths — the "
        "schema built but ``patch_invoice`` was dropped")
    assert "patch" in paths[patch_invoice_path], (
        f"{patch_invoice_path} present but has no ``patch`` method")


def test_patch_invoice_inline_invalidation_wiring_present() -> None:
    """Static-source guard — ``patch_invoice`` MUST call the inline
    helper at BOTH success-return paths so a future refactor can't
    silently drop offline-bundle invalidation on invoice edits.

    Mirrors the shape of ``test_hook_sweep_stamps_primary_mutation_
    endpoints`` in ``test_td_offline_bundle_tenant_cache.py`` but
    scoped to the inline-helper variant used by ``invoice_edit``.
    """
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "routers/invoice_edit.py"
    ).read_text(encoding="utf-8")

    # Helper is defined.
    assert "def _invalidate_offline_bundle_for_user(" in src
    # It wraps the real invalidate() call.
    assert "_invalidate_offline_bundle_cache(tenant_id)" in src
    # It's invoked from patch_invoice at BOTH return paths — count
    # the call sites.  Prefer >=2 to be resilient to additional
    # future success-return branches.
    assert src.count("_invalidate_offline_bundle_for_user(user)") >= 2
    # Decorator is NOT reapplied by a stray refactor.
    assert "@invalidates_offline_bundle\nasync def patch_invoice(" not in src
