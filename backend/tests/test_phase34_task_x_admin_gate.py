"""Phase 34 · Task X · Feb-2026 — admin-equivalent roles can edit any
job in their tenant.

The gate change lives in ``utils.require_admin`` which now accepts
``admin``, ``super_admin``, AND ``owner``. Every mutating job
endpoint depends on that gate, so this test locks the invariant at
its source.
"""
from __future__ import annotations
import pytest
from fastapi import HTTPException
from utils import require_admin


def test_admin_role_accepted():
    user = {"id": "u1", "tenant_id": "t1", "role": "admin"}
    assert require_admin(user) is user


def test_super_admin_role_accepted():
    user = {"id": "u2", "tenant_id": "t1", "role": "super_admin"}
    assert require_admin(user) is user


def test_owner_role_accepted():
    """Phase 34 · Task X — ``owner`` role now bypasses the same
    ``require_admin`` gate as ``admin`` / ``super_admin``."""
    user = {"id": "u3", "tenant_id": "t1", "role": "owner"}
    assert require_admin(user) is user


def test_technician_role_rejected():
    """Techs stay in their existing lane — no admin-scope endpoints."""
    user = {"id": "u4", "tenant_id": "t1", "role": "technician"}
    with pytest.raises(HTTPException) as exc:
        require_admin(user)
    assert exc.value.status_code == 403


def test_customer_role_rejected():
    user = {"id": "u5", "tenant_id": "t1", "role": "customer"}
    with pytest.raises(HTTPException) as exc:
        require_admin(user)
    assert exc.value.status_code == 403


def test_missing_role_rejected():
    with pytest.raises(HTTPException) as exc:
        require_admin({"id": "u6", "tenant_id": "t1"})
    assert exc.value.status_code == 403
