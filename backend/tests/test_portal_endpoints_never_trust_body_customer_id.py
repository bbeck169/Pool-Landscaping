"""Feb-2026 · Phase F3 · Contract test — portal never trusts a
body-supplied ``customer_id``.

Every route on the customer-portal router that accepts a request
body MUST scope its persistence to the SESSION's ``customer_id``
(from the JWT). A body key named ``customer_id`` must be either
(a) silently dropped by pydantic (unknown field on a strict model)
or (b) explicitly rejected with 422 — never (c) trusted.

Implementation:
  * Introspect the FastAPI ``routers.customer_portal.router`` at
    import time.
  * For every route with a ``BaseModel`` body parameter, verify
    the model class DOES NOT declare a ``customer_id`` field.
    (Local ``ServiceRequestIn`` is the primary target; if any
    future portal model adds ``customer_id`` this test fails
    loudly before the crosswire ships.)
  * If any model adds ``customer_id`` in the future, this fails
    with a clear pointer to the route + model + field.
"""
from __future__ import annotations

import inspect
from typing import Any, List

from pydantic import BaseModel

from routers.customer_portal import router as portal_router


def _find_body_models(route) -> List[type]:
    """Return every ``BaseModel`` subclass referenced as a
    parameter of the route's endpoint. Filters out injected
    dependencies (``Depends``) and path/query primitives."""
    fn = getattr(route, "endpoint", None)
    if fn is None:
        return []
    sig = inspect.signature(fn)
    models: List[type] = []
    for param in sig.parameters.values():
        anno = param.annotation
        if isinstance(anno, type) and issubclass(anno, BaseModel):
            models.append(anno)
    return models


def test_no_portal_body_model_declares_customer_id():
    """The F1 P0-A repair depends on ``ServiceRequestIn`` NOT
    declaring ``customer_id``. Any future portal model that
    accepts a body-level customer id is a regression risk."""
    violations: List[str] = []
    for route in portal_router.routes:
        path = getattr(route, "path", "") or ""
        methods = getattr(route, "methods", set()) or set()
        # Only consider write endpoints.
        if not (methods & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        for model in _find_body_models(route):
            fields = getattr(model, "model_fields", None) or {}
            if "customer_id" in fields:
                violations.append(
                    f"{sorted(methods)} {path} — {model.__name__} "
                    "declares 'customer_id' as a body field. The "
                    "portal MUST scope by session customer_id only. "
                    "Remove the field or route through a "
                    "session-only helper."
                )
    assert not violations, (
        "portal body models expose customer_id:\n  - "
        + "\n  - ".join(violations)
    )


def test_portal_service_request_body_ignores_extra_customer_id():
    """Direct pydantic-level guard: the strict schema drops
    unknown fields on construction — the field never reaches the
    handler."""
    from routers.customer_portal import ServiceRequestIn

    body = ServiceRequestIn.model_validate({
        "service_type": "Pool Cleaning",
        "notes": "test",
        "customer_id": "STRANGER",  # extra — must be dropped
    })
    assert not hasattr(body, "customer_id"), (
        "ServiceRequestIn accepted a body-level customer_id — the "
        "P0-A crosswire attack surface is reopened."
    )
    # And a direct setattr also must not succeed on the strict
    # schema (matches F1 unit test coverage).
    import pytest as _pytest
    with _pytest.raises((ValueError, TypeError)):
        setattr(body, "customer_id", "STRANGER")
