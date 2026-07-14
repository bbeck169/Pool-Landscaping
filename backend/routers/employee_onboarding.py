"""Phase 20B.2 · Employee onboarding — templates + assignments.

Distinct from the pre-existing `onboarding.py` (which is an admin's one-time
tenant setup wizard). This module manages HR-style onboarding checklists for
new employees: doc uploads, safety videos, quizzes, and policy acks.

- `onboarding_templates` — reusable, per-tenant, per-role.
- `onboarding_assignments` — per-user progress, transitions
  `not_started → in_progress → complete`.
"""
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


class StepIn(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = ""
    kind: str                              # task|doc_upload|video|quiz|policy_ack
    resource_url: Optional[str] = None
    quiz_questions: Optional[List[Dict[str, Any]]] = None  # [{q, choices, correct_index}]


class TemplateIn(BaseModel):
    role: str                              # technician|admin|marketing|generic
    title: str
    steps: List[StepIn]


class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    role: Optional[str] = None
    steps: Optional[List[StepIn]] = None


class AssignIn(BaseModel):
    user_id: str
    template_id: str


class QuizIn(BaseModel):
    answers: List[int]                     # index selection per question


# ── Default templates seeded on first fetch (per-tenant, idempotent) ─────
_DEFAULT_TECH_STEPS: List[Dict[str, Any]] = [
    {"title": "Sign W-4 / W-9", "kind": "doc_upload",
     "description": "Upload your signed tax withholding form."},
    {"title": "Watch pool safety video", "kind": "video",
     "description": "Complete the 8-minute safety training.",
     "resource_url": "https://www.example.com/videos/pool-safety.mp4"},
    {"title": "Chemical handling quiz", "kind": "quiz",
     "description": "Score 80% or higher to pass.",
     "quiz_questions": [
         {"q": "Chlorine + acid safe to mix?",
          "choices": ["Always", "Never", "Only if diluted"], "correct_index": 1},
         {"q": "Ideal pool pH range?",
          "choices": ["5.5–6.5", "7.2–7.8", "8.5–9.5"], "correct_index": 1},
         {"q": "First step when a chemical splash hits the eyes?",
          "choices": ["Wipe with towel", "Rinse with water immediately", "Call 911"],
          "correct_index": 1},
     ]},
    {"title": "Uniform issued & sign-off", "kind": "policy_ack",
     "description": "Confirm receipt of two shirts, one hat, name tag."},
    {"title": "PPE acknowledgment", "kind": "policy_ack",
     "description": "I have received and understand the PPE guidelines."},
    {"title": "GPS auto clock-in overview", "kind": "video",
     "description": "How the mobile app auto-detects arrival at a job site.",
     "resource_url": "https://www.example.com/videos/gps-clockin.mp4"},
]


async def _ensure_default_templates(tenant_id: str) -> None:
    existing = await db.onboarding_templates.count_documents(
        {"tenant_id": tenant_id, "role": "technician", "is_default": True}
    )
    if existing:
        return
    steps = [{**s, "id": new_id()} for s in _DEFAULT_TECH_STEPS]
    await db.onboarding_templates.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "role": "technician",
        "title": "Technician onboarding",
        "steps": steps,
        "is_default": True,
        "created_by": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })


@router.get("/onboarding/templates")
async def list_templates(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await _ensure_default_templates(tenant["id"])
    return await db.onboarding_templates.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)


@router.post("/onboarding/templates")
async def create_template(body: TemplateIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "role": body.role.strip(),
        "title": body.title.strip(),
        "steps": [{**s.dict(), "id": s.id or new_id()} for s in body.steps],
        "is_default": False,
        "created_by": user["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.onboarding_templates.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.put("/onboarding/templates/{tid}")
async def update_template(tid: str, body: TemplateUpdate,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if body.title is not None: upd["title"] = body.title.strip()
    if body.role is not None:  upd["role"] = body.role.strip()
    if body.steps is not None:
        upd["steps"] = [{**s.dict(), "id": s.id or new_id()} for s in body.steps]
    r = await db.onboarding_templates.update_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Template not found")
    return await db.onboarding_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/onboarding/templates/{tid}")
async def delete_template(tid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    r = await db.onboarding_templates.delete_one(
        {"id": tid, "tenant_id": tenant["id"], "is_default": {"$ne": True}}
    )
    if r.deleted_count == 0:
        raise HTTPException(404, "Template not found or default is protected")
    return {"ok": True}


# ── Assignments ─────────────────────────────────────────────────────────
@router.get("/onboarding/assignments")
async def list_assignments(
    user_id: Optional[str] = Query(None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if user_id:
        # Cross-tenant hardening — match the route-optimize pattern.
        other = await db.users.find_one(
            {"id": user_id}, {"_id": 0, "id": 1, "tenant_id": 1}
        )
        if not other:
            raise HTTPException(404, "user_id not found")
        if other.get("tenant_id") != tenant["id"]:
            raise HTTPException(403, "user_id not in current tenant")
        q["user_id"] = user_id
    return await db.onboarding_assignments.find(q, {"_id": 0}).sort("started_at", -1).to_list(1000)


@router.get("/onboarding/assignments/mine")
async def my_assignments(user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    """Any logged-in user's own onboarding assignments (unblocks employee view)."""
    return await db.onboarding_assignments.find(
        {"tenant_id": tenant["id"], "user_id": user["id"]}, {"_id": 0}
    ).sort("started_at", -1).to_list(200)


@router.post("/onboarding/assignments")
async def assign_template(body: AssignIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    tmpl = await db.onboarding_templates.find_one(
        {"id": body.template_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not tmpl:
        raise HTTPException(404, "Template not found")
    target = await db.users.find_one(
        {"id": body.user_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not target:
        raise HTTPException(404, "User not found in this tenant")
    existing = await db.onboarding_assignments.find_one(
        {"tenant_id": tenant["id"], "user_id": body.user_id, "template_id": body.template_id},
        {"_id": 0},
    )
    if existing:
        return existing
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "user_id": body.user_id,
        "template_id": body.template_id,
        "template_snapshot": tmpl,
        "status": "not_started",
        "step_progress": {},
        "started_at": now_iso(),
        "completed_at": None,
    }
    await db.onboarding_assignments.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _refresh_status(assignment: dict) -> dict:
    total = len(assignment["template_snapshot"]["steps"])
    done = sum(1 for v in (assignment.get("step_progress") or {}).values()
               if v.get("completed_at"))
    if done == 0:
        status = "not_started"
    elif done < total:
        status = "in_progress"
    else:
        status = "complete"
    upd: Dict[str, Any] = {"status": status}
    if status == "complete" and not assignment.get("completed_at"):
        upd["completed_at"] = now_iso()
    await db.onboarding_assignments.update_one({"id": assignment["id"]}, {"$set": upd})
    assignment.update(upd)
    return assignment


def _own_or_admin(assignment: dict, user: dict):
    if user.get("role") in ("admin", "super_admin"):
        return
    if assignment.get("user_id") != user.get("id"):
        raise HTTPException(403, "Not your assignment")


@router.post("/onboarding/assignments/{aid}/steps/{sid}/complete")
async def complete_step(aid: str, sid: str,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    a = await db.onboarding_assignments.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not a: raise HTTPException(404, "Assignment not found")
    _own_or_admin(a, user)
    step_ids = [s["id"] for s in a["template_snapshot"]["steps"]]
    if sid not in step_ids:
        raise HTTPException(400, "Step not part of assignment")
    sp = a.get("step_progress") or {}
    sp[sid] = {**sp.get(sid, {}), "completed_at": now_iso()}
    await db.onboarding_assignments.update_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"$set": {"step_progress": sp}}
    )
    a["step_progress"] = sp
    return await _refresh_status(a)


@router.post("/onboarding/assignments/{aid}/steps/{sid}/upload")
async def upload_step(aid: str, sid: str,
                      evidence_url: str = Query(..., description="already-hosted URL"),
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    """We accept a pre-uploaded URL (multipart lives in object storage router)."""
    a = await db.onboarding_assignments.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not a: raise HTTPException(404, "Assignment not found")
    _own_or_admin(a, user)
    sp = a.get("step_progress") or {}
    sp[sid] = {**sp.get(sid, {}), "evidence_url": evidence_url,
               "completed_at": now_iso()}
    await db.onboarding_assignments.update_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"$set": {"step_progress": sp}}
    )
    a["step_progress"] = sp
    return await _refresh_status(a)


@router.post("/onboarding/assignments/{aid}/steps/{sid}/quiz")
async def submit_quiz(aid: str, sid: str, body: QuizIn,
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    a = await db.onboarding_assignments.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not a: raise HTTPException(404, "Assignment not found")
    _own_or_admin(a, user)
    step = next((s for s in a["template_snapshot"]["steps"] if s["id"] == sid), None)
    if not step or step.get("kind") != "quiz":
        raise HTTPException(400, "Step is not a quiz")
    qs = step.get("quiz_questions") or []
    if len(body.answers) != len(qs):
        raise HTTPException(400, f"Expected {len(qs)} answers")
    correct = 0
    for q, ans in zip(qs, body.answers):
        if int(ans) == int(q.get("correct_index", -1)):
            correct += 1
    score = round(100 * correct / max(1, len(qs)))
    passed = score >= 80
    sp = a.get("step_progress") or {}
    sp[sid] = {
        **sp.get(sid, {}),
        "quiz_score": score,
        "quiz_passed": passed,
        "completed_at": now_iso() if passed else None,
    }
    await db.onboarding_assignments.update_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"$set": {"step_progress": sp}}
    )
    a["step_progress"] = sp
    await _refresh_status(a)
    return {"score": score, "passed": passed, "step_id": sid}
