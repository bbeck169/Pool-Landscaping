"""Phase 56.13a — Training subsystem (backend).
Phase 56.13a-commit — adds Certificate of Completion (PDF).

Multi-tenant training modules for internal upskilling (CPO prep,
supplemental pool topics, landscaper training, etc.).

Two module classes:
- SYSTEM MODULES (`is_system=True`, no `tenant_id`): globally-visible,
  read-only via the API, seeded only by trusted scripts.
- CUSTOM MODULES (`is_system=False`, `tenant_id` set): admin-editable,
  tenant-scoped.

RBAC:
- customer               → 403 on every endpoint.
- technician             → read+take modules matching their department.
                           quiz answers redacted (no correct_choice_ids).
- admin / super_admin    → read all + write custom + view all attempts +
                           see full quiz answer key + admin cert audit.

Certificates (Phase 56.13a-commit):
- Auto-awarded on first passing quiz attempt (score >= passing_score).
- Retakes with higher score upgrade the existing cert (no duplicates).
- PDF rendered on-demand (no S3 dependency); disclaimer prominent.
- IMPORTANT: The PDF prominently states "CPO Prep — Not Official
  Certification" and includes a bordered disclaimer block.
"""
from io import BytesIO
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

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


# Hotfix #4 · Feb-2026 — Trainings designation visibility.
#
# ``_TENANT_DESIGNATIONS`` is the set of specialities the tenant
# currently recognises. Adding a new designation later (e.g.
# ``"irrigation"``) is a single-line change here — the visibility
# rule automatically stays correct.
#
# Terminology mapping between the brief and this codebase:
#   brief `tech.designations`         → derived from ``user.department``
#   brief `training.required_designations` → the module's ``department``
#     field (`"pool"` | `"landscaping"` | `"both"`)
_TENANT_DESIGNATIONS: tuple[str, ...] = ("pool", "landscaping")
_UNIVERSAL_MODULE_TAG = "both"   # matches an "all designations" training

# Two department naming conventions coexist in the users collection —
# the canonical short form (``"pool"`` / ``"landscaping"``) and the
# modern ``_tech`` suffix form (``"pool_tech"`` / ``"landscape_tech"``)
# introduced by phase 41.1b's seed refactor. Training modules are
# tagged with the canonical short form only, so we normalise on read.
_DEPT_ALIASES: dict[str, str] = {
    "pool_tech": "pool",
    "landscape_tech": "landscaping",
    "landscaper": "landscaping",   # historical
}


def _normalize_dept(raw: str) -> str:
    d = (raw or "").lower().strip()
    return _DEPT_ALIASES.get(d, d)


def _user_designations(u: dict) -> set[str]:
    """Return the *set* of designations the tech carries.

    * scalar ``department = "pool"``       → ``{"pool"}``
    * scalar ``department = "landscaping"`` → ``{"landscaping"}``
    * scalar ``department = "both"``        → *every* tenant designation
                                              (cross-trained tech)
    * empty / unknown                        → ``set()``  (no designation)

    ``pool_tech`` / ``landscape_tech`` seed-style values are aliased to
    the canonical form so training visibility works regardless of which
    naming convention the caller was seeded with.
    """
    d = _normalize_dept(_dept(u))
    if not d:
        return set()
    if d == "both":
        return set(_TENANT_DESIGNATIONS)
    return {d}


def _visible_departments(u: dict) -> Optional[List[str]]:
    """Departments this user is allowed to see. ``None`` = all.

    Rule (hotfix #4):
      * Admin / super_admin                            → all
      * Tech whose designations cover EVERY tenant     → all
        designation (superset rule — "both means all")
      * Tech with one designation                      → that one + universal
      * Tech with zero designations                    → universal-only
    """
    if _is_admin(u):
        return None
    tech = _user_designations(u)
    tenant = set(_TENANT_DESIGNATIONS)
    if tech and tech >= tenant:
        # Superset — including the "both" cross-trained case and
        # any future "every designation the tenant has" case.
        return None
    if not tech:
        # Zero-designation tech: only untagged / universal trainings.
        return [_UNIVERSAL_MODULE_TAG]
    return sorted(tech | {_UNIVERSAL_MODULE_TAG})


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


def _redact_quiz_for_learner(mod: dict, user: dict) -> dict:
    """Strip `correct_choice_ids` + `explanation` from every quiz question
    so techs cannot cheat by reading the answer key from the API. Admins
    and super_admins see the full quiz."""
    if _is_admin(user):
        return mod
    quiz = mod.get("quiz") or {}
    questions = quiz.get("questions") or []
    redacted = []
    for q in questions:
        redacted.append({k: v for k, v in q.items()
                         if k not in ("correct_choice_ids", "explanation")})
    mod = {**mod, "quiz": {**quiz, "questions": redacted}}
    return mod


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
    return _redact_quiz_for_learner(mod, user)


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

    # Phase 56.13a-commit — auto-award certificate on pass.
    cert_id = None
    if result["passed"]:
        cert = await _award_or_upgrade_certificate(
            tenant=tenant, user=user, module=mod, score=result["score"]
        )
        cert_id = cert.get("certificate_id")
    attempt["certificate_id"] = cert_id
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


# ─── Phase 56.13a-commit — Certificate helpers ─────────────────────────────
_DISCLAIMER_PDF = (
    "IMPORTANT: This is an internal training completion certificate only. "
    "It does NOT constitute official Certified Pool Operator (CPO) "
    "certification. Official CPO certification requires enrollment and "
    "testing through an authorized provider such as PHTA or NSPF. Do not "
    "use this certificate to represent yourself as a certified pool "
    "operator to customers, employers, or regulatory bodies."
)
_SUBTITLE_PDF = "CPO Prep — Not Official Certification"


async def _next_cert_sequence(tenant_id: str, module_code: str) -> int:
    """Monotonic per-tenant + per-module cert sequence. Idempotent via
    count+1 rule; racy under high concurrency but a single tenant awarding
    certs one at a time on quiz pass will not hit that."""
    n = await db.training_certificates.count_documents({
        "tenant_id": tenant_id, "module_code": module_code,
    })
    return n + 1


def _build_certificate_id(module_code: str, awarded_at_iso: str, seq: int) -> str:
    """`CPO-PREP-2026-000042` — uppercased module code, year, 6-digit seq."""
    year = awarded_at_iso[:4] if len(awarded_at_iso) >= 4 else datetime.now(timezone.utc).strftime("%Y")
    slug = module_code.upper().replace("_", "-")
    return f"{slug}-{year}-{seq:06d}"


async def _award_or_upgrade_certificate(*, tenant: dict, user: dict, module: dict, score: float) -> dict:
    """Idempotent: one cert per (tenant, user, module). Upgrade `quiz_score`
    on higher retake. Returns the current cert doc (existing or new)."""
    existing = await db.training_certificates.find_one(
        {"tenant_id": tenant["id"], "user_id": user["id"], "module_code": module["code"]},
        {"_id": 0},
    )
    now = now_iso()
    if existing:
        if score > float(existing.get("quiz_score") or 0):
            await db.training_certificates.update_one(
                {"tenant_id": tenant["id"], "user_id": user["id"], "module_code": module["code"]},
                {"$set": {"quiz_score": score, "updated_at": now}},
            )
            existing["quiz_score"] = score
            existing["updated_at"] = now
        return existing

    seq = await _next_cert_sequence(tenant["id"], module["code"])
    cert_id = _build_certificate_id(module["code"], now, seq)
    doc = {
        "id": new_id(),
        "certificate_id": cert_id,
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "module_code": module["code"],
        "module_title": module.get("title") or module["code"],
        "user_name_snapshot": user.get("name") or user.get("email") or user["id"],
        "tenant_name_snapshot": tenant.get("name") or tenant.get("slug") or "Company",
        "quiz_score": float(score),
        "awarded_at": now,
        "updated_at": now,
    }
    await db.training_certificates.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _render_certificate_pdf(cert: dict) -> bytes:
    """Landscape letter PDF using reportlab. Prominent 'Not Official
    Certification' subtitle + bordered disclaimer block."""
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    page_w, page_h = landscape(letter)
    c = canvas.Canvas(buf, pagesize=landscape(letter))

    # Border
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.setLineWidth(3)
    c.rect(0.4 * inch, 0.4 * inch, page_w - 0.8 * inch, page_h - 0.8 * inch)

    # Tenant name (header)
    tenant_name = cert.get("tenant_name_snapshot") or "Company"
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(page_w / 2, page_h - 1.0 * inch, tenant_name)

    # Title
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(page_w / 2, page_h - 1.8 * inch, "Certificate of Completion")

    # PROMINENT SUBTITLE — required by spec
    c.setFillColor(colors.HexColor("#B91C1C"))
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(page_w / 2, page_h - 2.3 * inch, _SUBTITLE_PDF)

    # Body
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica", 14)
    awarded_at = cert.get("awarded_at") or ""
    awarded_display = awarded_at.split("T")[0] if "T" in awarded_at else awarded_at
    score_pct = int(round(float(cert.get("quiz_score") or 0) * 100))
    user_name = cert.get("user_name_snapshot") or ""
    module_title = cert.get("module_title") or cert.get("module_code") or ""

    body_y = page_h - 3.1 * inch
    c.drawCentredString(page_w / 2, body_y, "This certifies that")
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(page_w / 2, body_y - 0.5 * inch, user_name)
    c.setFont("Helvetica", 14)
    c.drawCentredString(page_w / 2, body_y - 1.0 * inch,
                        f"completed the {module_title} training module")
    c.drawCentredString(page_w / 2, body_y - 1.35 * inch,
                        f"on {awarded_display} with a score of {score_pct}%.")

    # Disclaimer block — bordered, prominent
    disc_y = 1.2 * inch
    disc_h = 1.4 * inch
    disc_x = 0.9 * inch
    disc_w = page_w - 1.8 * inch
    c.setStrokeColor(colors.HexColor("#B91C1C"))
    c.setLineWidth(2)
    c.rect(disc_x, disc_y, disc_w, disc_h)
    c.setFillColor(colors.HexColor("#7F1D1D"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(disc_x + 0.15 * inch, disc_y + disc_h - 0.25 * inch, "IMPORTANT DISCLAIMER")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#0F172A"))
    # Simple wrap: chunk the disclaimer at ~100 chars.
    text = c.beginText(disc_x + 0.15 * inch, disc_y + disc_h - 0.5 * inch)
    text.setLeading(12)
    words = _DISCLAIMER_PDF.split()
    line, lines = "", []
    for w in words:
        if len(line) + len(w) + 1 > 120:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    for l in lines:
        text.textLine(l)
    c.drawText(text)

    # Footer
    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("Helvetica", 8)
    c.drawString(0.7 * inch, 0.6 * inch,
                 f"Certificate ID: {cert.get('certificate_id','')}")
    c.drawRightString(page_w - 0.7 * inch, 0.6 * inch,
                      f"Generated by Pool & Landscaping — {awarded_display}")

    c.showPage()
    c.save()
    return buf.getvalue()


# ─── Phase 56.13a-commit — Certificate endpoints ───────────────────────────
@router.get("/training/certificates")
async def list_my_certificates(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Current user's certificates in this tenant."""
    _forbid_customer(user)
    rows = await db.training_certificates.find(
        {"tenant_id": tenant["id"], "user_id": user["id"]}, {"_id": 0},
    ).sort("awarded_at", -1).to_list(200)
    return rows


@router.get("/training/certificates/admin")
async def list_all_certificates_admin(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin audit view — all certificates in this tenant."""
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")
    rows = await db.training_certificates.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("awarded_at", -1).to_list(1000)
    return rows


# ─── Phase 56.13b-followup — bulk progress + leaderboard ───────────────────
@router.get("/training/progress/admin")
async def list_progress_admin(
    module_code: Optional[str] = Query(None, description="Filter to a single module code."),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only bulk read of every training_progress doc in this tenant.

    Powers the Team CPO Readiness widget's "in progress" counter — the
    per-user attempts endpoint is too heavy for a dashboard widget.
    Strictly tenant-scoped (no cross-tenant leakage).

    Response shape (per row):
        {
            user_id, module_code, lessons_completed: [...],
            has_started: bool, started_at, last_activity_at,
        }
    """
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")

    q: dict = {"tenant_id": tenant["id"]}
    if module_code:
        q["module_code"] = module_code

    rows = await db.training_progress.find(q, {"_id": 0}).to_list(5000)
    out = []
    for r in rows:
        lessons = list(r.get("lessons_completed") or [])
        out.append({
            "user_id": r.get("user_id"),
            "module_code": r.get("module_code"),
            "lessons_completed": lessons,
            "has_started": len(lessons) > 0,
            "started_at": r.get("started_at"),
            "last_activity_at": r.get("updated_at") or r.get("started_at"),
        })
    return out


@router.get("/training/leaderboard")
async def training_leaderboard(
    days: int = Query(90, ge=1, le=365, description="Rolling window in days."),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only per-tech rollup over the last `days` days.

    Response: list of `{user_id, name, email, department, role,
    modules_completed, quizzes_passed, quiz_attempts,
    certificates_earned, avg_score}`. `avg_score` averages
    `training_quiz_attempts.score` across attempts inside the window.
    """
    if not _is_admin(user):
        raise HTTPException(403, "Admin access required")

    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    users = await db.users.find(
        {"tenant_id": tenant["id"], "role": {"$in": ["technician", "admin", "super_admin"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "department": 1, "role": 1},
    ).to_list(2000)

    attempts = await db.training_quiz_attempts.find(
        {"tenant_id": tenant["id"], "submitted_at": {"$gte": cutoff}},
        {"_id": 0, "user_id": 1, "score": 1, "passed": 1, "module_code": 1},
    ).to_list(20000)

    progress = await db.training_progress.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "user_id": 1, "module_code": 1, "lessons_completed": 1},
    ).to_list(20000)

    certs = await db.training_certificates.find(
        {"tenant_id": tenant["id"], "awarded_at": {"$gte": cutoff}},
        {"_id": 0, "user_id": 1, "module_code": 1},
    ).to_list(20000)

    modules = await db.training_modules.find(
        _module_query(tenant["id"]),
        {"_id": 0, "code": 1, "lessons": 1},
    ).to_list(500)
    lesson_counts = {m["code"]: len(m.get("lessons") or []) for m in modules}

    # Per-user aggregates.
    per_user: dict = {}
    for a in attempts:
        uid = a.get("user_id")
        if not uid:
            continue
        row = per_user.setdefault(uid, {"scores": [], "passed_modules": set(), "attempts": 0, "certs": 0, "completed_modules": set()})
        row["attempts"] += 1
        if isinstance(a.get("score"), (int, float)):
            row["scores"].append(float(a["score"]))
        if a.get("passed"):
            row["passed_modules"].add(a.get("module_code"))

    for c in certs:
        uid = c.get("user_id")
        if not uid:
            continue
        row = per_user.setdefault(uid, {"scores": [], "passed_modules": set(), "attempts": 0, "certs": 0, "completed_modules": set()})
        row["certs"] += 1

    for p in progress:
        uid = p.get("user_id")
        code = p.get("module_code")
        if not uid or not code:
            continue
        completed = len(p.get("lessons_completed") or [])
        total = lesson_counts.get(code, 0)
        if total and completed >= total:
            row = per_user.setdefault(uid, {"scores": [], "passed_modules": set(), "attempts": 0, "certs": 0, "completed_modules": set()})
            row["completed_modules"].add(code)

    out = []
    for u in users:
        uid = u["id"]
        agg = per_user.get(uid, {"scores": [], "passed_modules": set(), "attempts": 0, "certs": 0, "completed_modules": set()})
        scores = agg["scores"]
        out.append({
            "user_id": uid,
            "name": u.get("name") or u.get("email") or "—",
            "email": u.get("email"),
            "department": (u.get("department") or "").lower() or None,
            "role": (u.get("role") or "").lower() or None,
            "modules_completed": len(agg["completed_modules"]),
            "quizzes_passed": len(agg["passed_modules"]),
            "quiz_attempts": agg["attempts"],
            "certificates_earned": agg["certs"],
            "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
        })
    # Sort by certificates desc, then modules_completed desc, then quizzes_passed desc.
    out.sort(key=lambda r: (
        -(r["certificates_earned"] or 0),
        -(r["modules_completed"] or 0),
        -(r["quizzes_passed"] or 0),
    ))
    return out


@router.get("/training/certificates/{certificate_id}")
async def get_certificate(
    certificate_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    cert = await db.training_certificates.find_one(
        {"tenant_id": tenant["id"], "certificate_id": certificate_id}, {"_id": 0},
    )
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if not _is_admin(user) and cert.get("user_id") != user["id"]:
        raise HTTPException(403, "Not your certificate")
    return cert


@router.get("/training/certificates/{certificate_id}/pdf")
async def download_certificate_pdf(
    certificate_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _forbid_customer(user)
    cert = await db.training_certificates.find_one(
        {"tenant_id": tenant["id"], "certificate_id": certificate_id}, {"_id": 0},
    )
    if not cert:
        raise HTTPException(404, "Certificate not found")
    if not _is_admin(user) and cert.get("user_id") != user["id"]:
        raise HTTPException(403, "Not your certificate")
    pdf_bytes = _render_certificate_pdf(cert)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="{cert.get("certificate_id","certificate")}.pdf"'
            ),
        },
    )

