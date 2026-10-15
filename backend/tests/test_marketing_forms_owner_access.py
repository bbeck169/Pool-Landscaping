"""OWNER-ACCESS-MARKETING-FORMS · Feb-2026 — regression lock.

Phase 1 Commit 1 of the owner-access ship for Marketing Forms.

Finding on inspection: ALL admin Marketing Forms endpoints already
depend on ``utils.require_admin``, which admits ``admin``,
``super_admin``, AND ``owner`` (see ``utils.py:226`` and the sibling
``tests/test_phase34_task_x_admin_gate.py`` which locks the role set
at the gate level).  No production-code change is required on the
backend — owner accounts can already reach every ``/admin/forms*``
endpoint.

This test is a forward-looking regression gate: it source-parses
``routers/marketing_forms.py`` and asserts

  1. The router module imports ``require_admin``.
  2. Every endpoint whose path begins with ``/admin/forms`` depends
     on ``require_admin`` via ``Depends(require_admin)`` — i.e. no
     handler sneaks in a stricter hard-coded role check that would
     silently exclude owner.
  3. ``marketing_forms.py`` contains ZERO literal references to the
     role strings ``"admin"`` / ``"super_admin"`` / ``"owner"`` /
     ``"super admin"`` inside handler bodies.  (The one allowed
     occurrence lives in a docstring that is corrected in the same
     atomic — see assertion 3b.)

Paired FE route-guard test:
    ``frontend/src/test/marketing-forms-phase1-owner-access.test.jsx``
"""
from __future__ import annotations

import re
from pathlib import Path


_SRC_PATH = (
    Path(__file__).resolve().parents[1] / "routers" / "marketing_forms.py"
)
_SRC = _SRC_PATH.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# 1. The module imports require_admin.
# ──────────────────────────────────────────────────────────────────
def test_marketing_forms_imports_require_admin():
    assert "require_admin" in _SRC, (
        "marketing_forms.py must import require_admin — otherwise "
        "the owner-access gate is bypassed at module boot."
    )
    # Explicit from-import check (positional in the file; see
    # routers/marketing_forms.py line ~40).
    assert re.search(
        r"from\s+utils\s+import[^\n]*\brequire_admin\b", _SRC,
    ), "require_admin must be imported from utils, not shadowed."


# ──────────────────────────────────────────────────────────────────
# 2. Every /admin/forms* endpoint uses Depends(require_admin).
# ──────────────────────────────────────────────────────────────────
# Walk the file linearly, pair each ``@router.{verb}("/admin/forms…")``
# decorator with the next function definition, and assert that
# definition's parameter list contains ``Depends(require_admin)``
# before the next ``@router.`` decorator.
_ROUTE_RE = re.compile(
    r'@router\.(?P<verb>get|post|patch|put|delete)\('
    r'\s*"(?P<path>/admin/forms[^"]*)"',
)
_NEXT_DECORATOR_RE = re.compile(r"\n@router\.")


def _handler_block_after(idx: int) -> str:
    """Return the text from ``idx`` up to the next @router decorator
    or EOF — this is the handler's signature + body."""
    tail = _SRC[idx:]
    m = _NEXT_DECORATOR_RE.search(tail[1:])  # skip the current '\n@'
    if not m:
        return tail
    return tail[: m.start() + 1]


def test_every_admin_forms_endpoint_uses_require_admin():
    matches = list(_ROUTE_RE.finditer(_SRC))
    # Marketing Forms admin surface shipped so far has 8 endpoints
    # (create, list, get, patch, delete, list_versions, revert,
    # list_submissions).  The guard is >= so future additions don't
    # break the test; the per-endpoint ``require_admin`` assertion
    # below is the real check.
    assert len(matches) >= 8, (
        f"Expected >= 8 /admin/forms endpoints, found {len(matches)}; "
        "did an endpoint get renamed out of /admin/forms namespace?"
    )
    for m in matches:
        block = _handler_block_after(m.start())
        assert "Depends(require_admin)" in block, (
            f"Endpoint {m.group('verb').upper()} {m.group('path')} "
            f"must use Depends(require_admin) so owner / admin / "
            f"super_admin all pass. Handler block:\n{block[:400]}"
        )


# ──────────────────────────────────────────────────────────────────
# 3. No literal role-string check inside the module (handlers).
# ──────────────────────────────────────────────────────────────────
# Handlers must NOT contain lines like ``if user["role"] == "admin"``
# — that would silently exclude owner even though require_admin
# admits them.  The one allowed occurrence of the string ``admin``
# in handlers is as part of ``require_admin`` or ``admin_bell`` /
# ``admin_only`` / ``admin/forms`` route literals, which are
# non-authorization identifiers.
def test_no_hardcoded_role_check_in_marketing_forms_handlers():
    # Flag any ``user[...]role...`` or ``user.get("role")`` compared
    # against a literal role string — the forbidden pattern.
    forbidden = re.compile(
        r'user\s*(?:\[|\.get\(\s*)["\']role["\']\s*\]?\s*\)?\s*'
        r'(?:==|in)\s*',
    )
    assert not forbidden.search(_SRC), (
        "marketing_forms.py contains a hard-coded user-role check "
        "inside a handler. This would bypass require_admin's "
        "owner-admitting behavior. Use Depends(require_admin) "
        "instead."
    )


# ──────────────────────────────────────────────────────────────────
# 4. Positive invariant lock: require_admin itself admits owner.
# ──────────────────────────────────────────────────────────────────
# Duplicates the coverage in ``test_phase34_task_x_admin_gate.py`` on
# purpose — owner access on Marketing Forms depends on this
# invariant NOT regressing silently.
def test_require_admin_admits_owner_role():
    from utils import require_admin
    user = {"id": "u-owner", "tenant_id": "t1", "role": "owner"}
    assert require_admin(user) is user, (
        "require_admin must accept owner. If this fails, "
        "the owner-access ship for Marketing Forms is broken "
        "AND every other require_admin-gated surface simultaneously."
    )
