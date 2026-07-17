"""Phase 56.13a — Training subsystem (backend).

Multi-tenant training modules for internal upskilling (CPO prep,
supplemental pool topics, landscaper training, etc.). Ships with the
subsystem substrate ONLY — no CPO content is seeded from this router.
The CPO content lives in `/app/backend/seed/training_cpo_chapters/` and
is committed to the DB via `python -m backend.seed.training_cpo --commit`
after user review.

Two module classes:
- SYSTEM MODULES (`is_system=True`, no `tenant_id`): globally-visible,
  read-only via the API, seeded only by trusted scripts.
- CUSTOM MODULES (`is_system=False`, `tenant_id` set): admin-editable,
  tenant-scoped.

RBAC:
- customer               → 403 on every endpoint (no learner UI for customers).
- technician             → read+take modules matching their department
                           ("pool" tech sees pool + both; "landscaping"
                           tech sees landscaping + both).
- admin / super_admin    → read all + write custom + view all attempts.

Endpoints (8):
  GET    /api/training/modules
  GET    /api/training/modules/{code}
  POST   /api/training/modules              — admin only, custom modules
  PATCH  /api/training/modules/{code}       — admin only, custom modules
  DELETE /api/training/modules/{code}       — admin only, custom modules
  POST   /api/training/modules/{code}/progress
  POST   /api/training/modules/{code}/quiz
  GET    /api/training/modules/{code}/attempts

Collections:
  - training_modules        {code (unique per tenant), is_system, tenant_id?, ...}
  - training_progress       {tenant_id, user_id, module_code, lessons_completed[]}
  - training_quiz_attempts  {tenant_id, user_id, module_code, score, passed, ...}
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from models import (
    TrainingModuleIn, TrainingModuleUpdate,
    TrainingProgressIn, TrainingQuizSubmit,
)
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

router = APIRouter()


# ─── helpers ────────────────────────────────────────────────────────────────
def _role(u: dict) -> str:
    return (u.get("role") or "").lower()


def _dept(u: dict) -> str:
    return (u.get("department") or "").lower()


def _is_admin(u: dict) -> bool:
    return _role(u) in ("admin", "super_admin")


def _visible_departments(u: dict) -> Optional[List[str]]:
    """Return the list of module departments the user is allowed to see,
    or None to mean 'all departments'. Admins see all."""
    if _is_admin(u):
        return None
    d = _dept(u)
    if d == "landscaping":
        return ["landscaping", "both"]
    if d == "pool":
        return ["pool", "both"]
    # Techs without a department default to pool (matches Phase 49.3 seed).
    return ["pool", "both"]


def _module_query(tenant_id: str, code: Optional[str] = None) -> dict:
    """Match either the system row (no tenant_id) OR this tenant's custom row.

    NOTE: A tenant may override a system module by creating a custom module
    with the SAME code + `is_system=False`. Reads prefer the tenant-specific
    override when present; writes only ever touch custom (tenant-scoped) rows.
    """
    q: dict = {
        "$or": [
            {"is_system": True},
            {"tenant_id": tenant_id, "is_system": {"$ne": True}},
        ],
    }
    if code:
        q["code"] = code
    return q


async def _resolve_module(code: str, tenant_id: str) -> Optional[dict]:
    """Fetch a module by code — tenant custom overrides system module."""
    custom = await db.training_modules.find_one(
        {"code": code, "tenant_id": tenant_id, "is_system": {"$ne": True}},
        {"_id": 0},
    )
    if custom:
        return custom
    return await db.training_modules.find_one(
        {"code": code, "is_system": True}, {"_id": 0}
    )


def _forbid_customer(u: dict) -> None:
    if _role(u) == "customer":
        raise HTTPException(403, "Training is not available to customers")


def _forbid_impersonated_writes(u: dict) -> None:
    if u.get("is_impersonated"):
        raise HTTPException(403, "Disabled while viewing as another user")


def _module_visible_to(mod: dict, u: dict) -> bool:
    if _is_admin(u):
        return True
    depts = _visible_departments(u) or []
    return (mod.get("department") or "pool").lower() in depts


def _score_quiz(module: dict, submitted: dict) -> dict:
    """Compare submitted answers against `correct_choice_ids` on each Q.
    Returns {correct, total, score, passed}."""
    quiz = module.get("quiz") or {}
    questions = quiz.get("questions") or []
    passing = float(quiz.get("passing_score") or 0.75)
    total = len(questions)
    correct = 0
    for q in questions:
        qid = q.get("id")
        chosen = submitted.get(qid)
        correct_ids = q.get("correct_choice_ids") or []
        if chosen and chosen in correct_ids:
            correct += 1
    score = (correct / total) if total else 0.0
    return {
        "correct": correct,
        "total": total,
        "score": round(score, 4),
        "passed": score >= passing,
        "passing_score": passing,
    }


# ─── endpoints ─────────────────────────────────────────────────────────────
@router.get("/training/modules")
async def list_modules(
    department: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List modules visible to the caller (department-filtered for techs)."""
    _forbid_customer(user)
    q = _module_query(tenant["id"])
    depts = _visible_departments(user)
    if depts is not None:
        q["department"] = {"$in": depts}
    if department:
        # narrow further if caller requests a specific department
        if depts is not None and department not in depts:
            return []
        q["department"] = department
    rows = await db.training_modules.find(q, {"_id": 0}).sort("code", 1).to_list(500)

    # De-dup: tenant custom overrides system module of same code.
    by_code: dict = {}
    for r in rows:
        code = r.get("code")
        if code in by_code:
            # prefer tenant custom over system
            if r.get("tenant_id"):
                by_code[code] = r
        else:
            by_code[code] = r

    # Attach the caller's progress summary to each module.
    codes = list(by_code.keys())
    progress_rows = []
    if codes:
        progress_rows = await db.training_progress.find(
            {"tenant_id": tenant["id"], "user_id": user["id"],
             "module_code": {"$in": codes}},
            {"_id": 0},
        ).to_list(500)
    progress_map = {p["module_code"]: p for p in progress_rows}

    out = []
    for code, m in by_code.items():
        p = progress_map.get(code)
        completed = set((p or {}).get("lessons_completed") or [])
        total_lessons = len(m.get("lessons") or [])
        out.append({
            "code": m.get("code"),
            "title": m.get("title"),
            "department": m.get("department"),
            "description": m.get("description") or "",
            "badge_label": m.get("badge_label") or "",
            "disclaimer": m.get("disclaimer") or "",
            "is_system": bool(m.get("is_system")),
            "lesson_count": total_lessons,
            "question_count": len((m.get("quiz") or {}).get("questions") or []),
            "progress": {
                "lessons_completed": len(completed),
                "lessons_total": total_lessons,
                "percent": (round(len(completed) / total_lessons, 4) if total_lessons else 0.0),
            },
        })
    return out


@router.get("/training/modules/{code}")
async def get_module(
    code: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    mod = await _resolve_module(code, tenant["id"])
    if not mod:
        raise HTTPException(404, "Module not found")
    if not _module_visible_to(mod, user):
        raise HTTPException(403, "Module not available for your department")
    # Attach caller progress + last quiz attempt.
    progress = await db.training_progress.find_one(
        {"tenant_id": tenant["id"], "user_id": user["id"], "module_code": code},
        {"_id": 0},
    )
    last_attempt = await db.training_quiz_attempts.find_one(
        {"tenant_id": tenant["id"], "user_id": user["id"], "module_code": code},
        {"_id": 0}, sort=[("submitted_at", -1)],
    )
    mod["progress"] = progress or {
        "user_id": user["id"], "module_code": code,
        "lessons_completed": [], "started_at": None, "updated_at": None,
    }
    mod["last_attempt"] = last_attempt
    return mod


@router.post("/training/modules")
async def create_module(
    body: TrainingModuleIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Admins only. Custom modules are always `is_system=False` +
    tenant-scoped. System modules are seeded exclusively by trusted
    scripts."""
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    _forbid_impersonated_writes(user)

    # Block collision with system code (admins can still override via same
    # code, so allow tenant-scoped duplicate — but not another custom row).
    existing_custom = await db.training_modules.find_one(
        {"code": body.code, "tenant_id": tenant["id"], "is_system": {"$ne": True}},
        {"_id": 0, "code": 1},
    )
    if existing_custom:
        raise HTTPException(409, f"Custom module with code '{body.code}' already exists")

    doc = body.dict()
    # Force system fields — the caller cannot elevate their module.
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "is_system": False,
        "created_by_user_id": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    await db.training_modules.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/training/modules/{code}")
async def update_module(
    code: str, body: TrainingModuleUpdate,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    _forbid_impersonated_writes(user)

    # First refuse if only a system module exists — system modules are
    # immutable via API.
    custom = await db.training_modules.find_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": {"$ne": True}},
        {"_id": 0},
    )
    if not custom:
        system = await db.training_modules.find_one({"code": code, "is_system": True}, {"_id": 0})
        if system:
            raise HTTPException(409, "System modules are immutable; create a custom module with the same code to override")
        raise HTTPException(404, "Module not found")

    updates = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not updates:
        return {"ok": True, "unchanged": True}
    if updates.get("department") is not None:
        d = updates["department"].lower()
        if d not in ("pool", "landscaping", "both"):
            raise HTTPException(400, "department must be pool | landscaping | both")
        updates["department"] = d
    updates["updated_at"] = now_iso()
    await db.training_modules.update_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": {"$ne": True}},
        {"$set": updates},
    )
    doc = await db.training_modules.find_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": {"$ne": True}}, {"_id": 0}
    )
    return doc


@router.delete("/training/modules/{code}")
async def delete_module(
    code: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    _forbid_impersonated_writes(user)

    system = await db.training_modules.find_one({"code": code, "is_system": True}, {"_id": 0, "code": 1})
    custom = await db.training_modules.find_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": {"$ne": True}},
        {"_id": 0, "code": 1},
    )
    if not custom:
        if system:
            raise HTTPException(409, "System modules cannot be deleted")
        raise HTTPException(404, "Module not found")
    await db.training_modules.delete_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": {"$ne": True}}
    )
    return {"ok": True, "deleted": code}


@router.post("/training/modules/{code}/progress")
async def mark_lesson_complete(
    code: str, body: TrainingProgressIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    mod = await _resolve_module(code, tenant["id"])
    if not mod:
        raise HTTPException(404, "Module not found")
    if not _module_visible_to(mod, user):
        raise HTTPException(403, "Module not available for your department")

    lesson_ids = {l.get("id") for l in (mod.get("lessons") or [])}
    if body.lesson_id not in lesson_ids:
        raise HTTPException(400, f"lesson_id '{body.lesson_id}' not part of module '{code}'")

    now = now_iso()
    # Upsert progress row; add lesson to set atomically.
    await db.training_progress.update_one(
        {"tenant_id": tenant["id"], "user_id": user["id"], "module_code": code},
        {
            "$setOnInsert": {
                "id": new_id(),
                "tenant_id": tenant["id"],
                "user_id": user["id"],
                "module_code": code,
                "started_at": now,
            },
            "$addToSet": {"lessons_completed": body.lesson_id},
            "$set": {"updated_at": now},
        },
        upsert=True,
    )
    doc = await db.training_progress.find_one(
        {"tenant_id": tenant["id"], "user_id": user["id"], "module_code": code},
        {"_id": 0},
    )
    total = len(mod.get("lessons") or [])
    completed = len((doc or {}).get("lessons_completed") or [])
    return {
        "ok": True,
        "progress": doc,
        "percent": round(completed / total, 4) if total else 0.0,
    }


@router.post("/training/modules/{code}/quiz")
async def submit_quiz(
    code: str, body: TrainingQuizSubmit,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    mod = await _resolve_module(code, tenant["id"])
    if not mod:
        raise HTTPException(404, "Module not found")
    if not _module_visible_to(mod, user):
        raise HTTPException(403, "Module not available for your department")

    quiz = mod.get("quiz") or {}
    if not (quiz.get("questions") or []):
        raise HTTPException(400, "This module has no quiz")

    # Validate the answers payload is a plain dict of {qid: choice_id}.
    if not isinstance(body.answers, dict):
        raise HTTPException(400, "answers must be an object of {question_id: choice_id}")

    result = _score_quiz(mod, body.answers)
    attempt = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "module_code": code,
        "score": result["score"],
        "correct": result["correct"],
        "total": result["total"],
        "passed": result["passed"],
        "passing_score": result["passing_score"],
        "answers": body.answers,
        "submitted_at": now_iso(),
    }
    await db.training_quiz_attempts.insert_one(attempt)
    attempt.pop("_id", None)
    return attempt


@router.get("/training/modules/{code}/attempts")
async def list_attempts(
    code: str,
    user_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Techs → own attempts only. Admins → all attempts within tenant;
    filter to a single user with `?user_id=`."""
    _forbid_customer(user)
    mod = await _resolve_module(code, tenant["id"])
    if not mod:
        raise HTTPException(404, "Module not found")

    q: dict = {"tenant_id": tenant["id"], "module_code": code}
    if not _is_admin(user):
        q["user_id"] = user["id"]
    elif user_id:
        q["user_id"] = user_id

    rows = await db.training_quiz_attempts.find(q, {"_id": 0})\
        .sort("submitted_at", -1).to_list(500)
    return rows
