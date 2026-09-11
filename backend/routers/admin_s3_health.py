"""Feb-2026 · Photos-in-S3 Phase 1 · admin health check endpoint.

Admin-only. Reports S3 config presence + bucket accessibility +
tiny write-then-delete self-test. See
``/app/memory/FEATURE_PHOTOS_S3_PHASE1.md`` for the response shape.
"""
from fastapi import APIRouter, Depends, HTTPException

from utils import get_current_user

router = APIRouter(tags=["admin"])


_HEALTH_ROLES = {"admin", "super_admin", "owner"}


@router.get("/admin/s3/health", operation_id="admin.s3.health")
async def s3_health(user: dict = Depends(get_current_user)):
    """Return the S3 subsystem health snapshot. Admin/owner only."""
    role = (user.get("role") or "").lower()
    if role not in _HEALTH_ROLES:
        raise HTTPException(403, "Admin only")
    from services.aws_s3.photos import health_check
    return health_check()
