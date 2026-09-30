"""Feb-2026 · Drill-down role expansion — gate contract tests.

Locks the ``_require_drilldown_read_role`` helper introduced on
``routers/dashboard_drilldown.py`` so the four allowed roles
(``admin``, ``super_admin``, ``manager``, ``owner``) pass through
the three ``/rows`` endpoints unchanged, and every other role
receives the same 403 + ``admin_only`` detail as the tighter
``_require_admin_or_super`` gate that still protects the six
write / picker endpoints.

The tests are deliberately in-process (no HTTP, no DB, no seed
drift) so they run in milliseconds and stay green regardless of
which demo users are seeded on any given environment.  Live-HTTP
role coverage is exercised by the K41 suite
(``tests/test_k41_dashboard_drilldown.py``); this file locks the
helper contract itself so a future rename or role-set drift is
caught immediately.
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from routers import dashboard_drilldown as dd


# ═════════════════════════════════════════════════════════════════════
# 1) Role-set constants — regression guards
# ═════════════════════════════════════════════════════════════════════
def test_admin_roles_constant_unchanged_for_write_endpoints():
    """The six write / picker endpoints still route through
    ``_require_admin_or_super`` — its role set must stay narrow so
    a drill-down read-expansion doesn't accidentally open the
    ``data-integrity/resolve`` bulk mutation to managers."""
    assert dd._ADMIN_ROLES == {"admin", "super_admin"}


def test_drilldown_read_roles_constant_expands_to_manager_and_owner():
    assert dd._DRILLDOWN_READ_ROLES == {
        "admin", "super_admin", "manager", "owner",
    }


# ═════════════════════════════════════════════════════════════════════
# 2) Helper contract — positive roles pass, negatives raise 403
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "manager", "owner"])
def test_require_drilldown_read_role_admits_all_four(role: str):
    # ``None`` return = accepted (function raises on deny).
    assert dd._require_drilldown_read_role({"role": role}) is None


@pytest.mark.parametrize("role", ["ADMIN", "Super_Admin", "Manager", "OWNER"])
def test_require_drilldown_read_role_is_case_insensitive(role: str):
    """Matches the pre-existing case-insensitive contract on
    ``_require_admin_or_super`` — role tokens can arrive in mixed
    case from legacy user rows."""
    assert dd._require_drilldown_read_role({"role": role}) is None


@pytest.mark.parametrize("role", [
    "technician", "tech",           # field techs
    "dispatch", "dispatcher",       # dispatcher variants
    "customer",                     # portal caller
    "office",                       # office staff (below the finance line)
    "sales",                        # sales rep
    "",                             # empty string
])
def test_require_drilldown_read_role_denies_non_privileged(role: str):
    with pytest.raises(HTTPException) as exc_info:
        dd._require_drilldown_read_role({"role": role})
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "admin_only"


def test_require_drilldown_read_role_denies_none_user():
    with pytest.raises(HTTPException) as exc_info:
        dd._require_drilldown_read_role(None)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "admin_only"


def test_require_drilldown_read_role_denies_missing_role_key():
    """User dict without a ``role`` field — legacy fixture shape."""
    with pytest.raises(HTTPException) as exc_info:
        dd._require_drilldown_read_role({})
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "admin_only"


# ═════════════════════════════════════════════════════════════════════
# 3) Regression — narrower gate still denies manager / owner so the
#    write / picker endpoints keep their tight scope.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["manager", "owner"])
def test_require_admin_or_super_still_denies_manager_and_owner(role: str):
    with pytest.raises(HTTPException) as exc_info:
        dd._require_admin_or_super({"role": role})
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "admin_only"


# ═════════════════════════════════════════════════════════════════════
# 4) Endpoint-wiring — the 3 ``/rows`` handlers call the NEW helper
#    and none of them ever fall back to ``_require_admin_or_super``.
# ═════════════════════════════════════════════════════════════════════
_ROWS_ENDPOINTS = (
    dd.data_integrity_rows,
    dd.income_by_category_rows,
    dd.income_by_service_rows,
)


@pytest.mark.parametrize("handler", _ROWS_ENDPOINTS)
def test_rows_endpoint_calls_new_helper(handler):
    src = inspect.getsource(handler)
    assert "_require_drilldown_read_role(user)" in src, (
        f"{handler.__name__} must call _require_drilldown_read_role; "
        f"expanded gate is a contract."
    )
    # The narrower helper must not appear anywhere in the body of
    # the three read endpoints — a stray call would silently deny
    # manager / owner on that endpoint.
    assert "_require_admin_or_super" not in src, (
        f"{handler.__name__} unexpectedly still references "
        f"_require_admin_or_super; expanded gate broken."
    )


def test_write_and_picker_endpoints_still_on_narrower_gate():
    """The six write / picker handlers (``resolve`` singular +
    bulk, ``undo-bulk``, ``line-item-audit``, and both picker
    endpoints) must stay on ``_require_admin_or_super``.  A
    module-level grep protects against a copy-paste swap during
    the expansion."""
    src = inspect.getsource(dd)
    # Locate every call site of the narrower gate and verify it's
    # NOT preceded by one of the three ``/rows`` decorators.
    narrower_call_sites = re.findall(
        r"_require_admin_or_super\(user\)", src,
    )
    # We seeded 9 total call sites originally; 3 were converted to
    # the wider gate. Remaining count MUST be 6.
    assert len(narrower_call_sites) == 6, (
        f"Expected 6 narrower-gate call sites (writes + pickers); "
        f"found {len(narrower_call_sites)}. "
        f"Someone widened / narrowed the wrong endpoint."
    )
