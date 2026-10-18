"""TD-78c · Feb-2026 — ``dispatcher`` added to ``K6_UNLOCK_ROLES``.

Operator-ruled: dispatchers legitimately edit completed jobs
(correcting tech notes, re-attaching missed photos, fixing
chemistry typos on behalf of the field). This test suite pins
the role addition and the matching audit-trail contract.

Twin on the FE: ``frontend/src/pages/jobs/JobDetail.jsx::K6_UNLOCK_ROLES``
+ ``frontend/src/test/jobdetail-k6-completed-unlock.test.jsx``.
"""
from __future__ import annotations


def test_dispatcher_is_in_K6_UNLOCK_ROLES():
    from services.edit_window import K6_UNLOCK_ROLES, role_bypasses_edit_window
    assert "dispatcher" in K6_UNLOCK_ROLES
    assert role_bypasses_edit_window("dispatcher") is True
    # Case-insensitive helper still works.
    assert role_bypasses_edit_window("Dispatcher") is True
    assert role_bypasses_edit_window("DISPATCHER") is True


def test_K6_UNLOCK_ROLES_now_has_exactly_eight_roles():
    """Pin the set size post-TD-78c so a future refactor that
    accidentally drops ``dispatcher`` or ``employee`` fails loudly."""
    from services.edit_window import K6_UNLOCK_ROLES
    assert len(K6_UNLOCK_ROLES) == 8
    assert K6_UNLOCK_ROLES == frozenset({
        "super_admin", "admin", "manager",
        "tech", "technician", "owner",
        "employee",
        "dispatcher",
    })


def test_customer_is_still_not_in_K6_UNLOCK_ROLES():
    """Negative regression lock — the TD-78c addition must NOT
    accidentally admit the portal role to the K6 bypass."""
    from services.edit_window import K6_UNLOCK_ROLES, role_bypasses_edit_window
    assert "customer" not in K6_UNLOCK_ROLES
    assert role_bypasses_edit_window("customer") is False
    assert role_bypasses_edit_window("CUSTOMER") is False


def test_operator_role_still_absent_per_td78c_scope_decision():
    """Operator-ruled: TD-78c adds ONLY ``dispatcher``. The
    operator-spec'd ``operator`` role was audit-confirmed as a
    non-seeded role string in the codebase (only usages are
    generic nouns in CMS/rule contexts) and was EXPLICITLY
    excluded from the TD-78c scope."""
    from services.edit_window import K6_UNLOCK_ROLES, role_bypasses_edit_window
    assert "operator" not in K6_UNLOCK_ROLES
    assert role_bypasses_edit_window("operator") is False
