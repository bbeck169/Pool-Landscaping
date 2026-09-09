"""Phase 16 · Business OS · Items A–G.

One consolidated router that ships:
  A) SOP Library                  — /api/sops (CRUD + AI generate)
  B) Role Definitions             — /api/role-definitions (CRUD + seed 8 roles)
  C) KPI Scorecards               — /api/kpi-scorecards (per-role + status colors)
  D) Crew Huddle                  — /api/huddles (list/create) + AI agenda + action-items → tasks
  E) LeanBoards (3)               — /api/leanboards (SOP-tied kanban) + card-move
  F) Sprint Planner               — /api/sprints (plan/review/retro)
  G) Four Pillars overview        — /api/os/overview

Global rules honoured:
* Every endpoint is admin-only via `require_admin`.
* Every collection stores `tenant_id` and every query filters by it (Phase 15D).
* AI features use `EMERGENT_LLM_KEY` via emergentintegrations. Silent stub-fallback
  when key is unset so demos still work.

Item H (Lana AI persona) is seeded via `routers/ai_ops.py::SEEDED_EMPLOYEES`.
Item I (tier gates) lives in `routers/tenant_plans.py`.
"""
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()


# ─── Seed data ─────────────────────────────────────────────────────────────
SEED_SOPS = [
    {"slug": "weekly-pool-service", "title": "Weekly Pool Service",
     "category": "Pool", "owner_role": "lead_tech",
     "content": "1. Test water chemistry (FC/CC/pH/TA/CH/CYA/salt).\n2. Skim surface + brush walls.\n3. Vacuum floor.\n4. Empty skimmer + pump baskets.\n5. Backwash if PSI ≥ +8 above clean.\n6. Add chems per SWG calculator.\n7. Photo before/after."},
    {"slug": "salt-cell-cleaning", "title": "Salt Cell Cleaning",
     "category": "Pool", "owner_role": "lead_tech",
     "content": "Yearly. Muriatic-acid soak 15 min, rinse, reinstall, log salt ppm."},
    {"slug": "filter-service", "title": "DE / Cartridge Filter Service",
     "category": "Pool", "owner_role": "lead_tech",
     "content": "Every 90 days. Backwash → open → clean grids → recharge DE → log clean PSI."},
    {"slug": "green-pool-recovery", "title": "Green Pool Recovery",
     "category": "Pool", "owner_role": "lead_tech",
     "content": "Day 0 shock + brush. Day 2 vacuum-to-waste + rebalance. Photograph daily."},
    {"slug": "spring-open", "title": "Spring Pool Open",
     "category": "Pool", "owner_role": "tech",
     "content": "Remove cover, prime pump, inspect equipment, chem-shock, run 24hr."},
    {"slug": "winterize", "title": "Winterize Pool",
     "category": "Pool", "owner_role": "tech",
     "content": "Lower water level, blow lines, plug returns, add winter chems, cover."},
    {"slug": "mow-and-edge", "title": "Mow, Edge, Blow",
     "category": "Landscape", "owner_role": "tech",
     "content": "Mow at proper height, string-trim edges, edge hardscapes, blow debris to street."},
    {"slug": "seasonal-trim", "title": "Seasonal Shrub Trim",
     "category": "Landscape", "owner_role": "lead_tech",
     "content": "Shape shrubs to healthy structure. Photograph before/after. Note irrigation issues."},
    {"slug": "irrigation-audit", "title": "Irrigation Audit",
     "category": "Landscape", "owner_role": "lead_tech",
     "content": "Run each zone, check heads, adjust arcs, log broken parts, upsell repair."},
    {"slug": "sales-consult-call", "title": "Sales Consult (Phone)",
     "category": "Sales", "owner_role": "sales",
     "content": "Discovery → pain → budget → schedule visit. Log CRM lead. Follow up 24 hr."},
]

SEED_ROLES = [
    {"slug": "owner", "title": "Owner", "reports_to": None,
     "responsibilities": ["Vision + strategy", "Cash & P&L", "Culture", "Final hire/fire authority"],
     "kpis": ["Net profit %", "Cash-on-hand", "Owner hours/week"]},
    {"slug": "ops_manager", "title": "Operations Manager", "reports_to": "owner",
     "responsibilities": ["Weekly schedule", "Crew coverage", "SOP adherence", "Equipment upkeep"],
     "kpis": ["On-time %", "First-visit fix %", "Route density"]},
    {"slug": "lead_tech", "title": "Lead Technician", "reports_to": "ops_manager",
     "responsibilities": ["Mentor techs", "Complex repairs", "QA weekly visits"],
     "kpis": ["Callback rate", "CSAT ≥ 4.7", "Hours billable"]},
    {"slug": "tech", "title": "Technician", "reports_to": "lead_tech",
     "responsibilities": ["Execute weekly SOPs", "Chem readings", "Photos", "Customer relations"],
     "kpis": ["Stops/day", "On-time arrival", "Photo compliance %"]},
    {"slug": "sales", "title": "Sales Rep", "reports_to": "owner",
     "responsibilities": ["Lead follow-up", "In-home consults", "Close deals", "Handoff to ops"],
     "kpis": ["Close rate", "Avg ticket", "Speed-to-lead ≤ 5 min"]},
    {"slug": "admin", "title": "Office Admin", "reports_to": "owner",
     "responsibilities": ["Scheduling", "Invoicing", "AR follow-up", "Client comms"],
     "kpis": ["Invoices sent ≤ 24hr", "AR aging ≤ 45d avg", "Portal usage %"]},
    {"slug": "marketing", "title": "Marketing Lead", "reports_to": "owner",
     "responsibilities": ["Content calendar", "SEO articles", "GBP", "Sequences"],
     "kpis": ["MQL/month", "Blog rank ≥ #10", "Review rate ≥ 20%"]},
    {"slug": "customer_service", "title": "Customer Service", "reports_to": "admin",
     "responsibilities": ["Answer inbound", "CSAT recovery", "Portal support"],
     "kpis": ["First-response ≤ 10 min", "CSAT ≥ 4.6", "Tickets closed/day"]},
]

SEED_LEANBOARDS = [
    {"slug": "weekly-service", "title": "Weekly Service Route", "sop_slug": "weekly-pool-service",
     "columns": ["Backlog", "This Week", "In Progress", "Photo QA", "Done"]},
    {"slug": "green-recovery", "title": "Green Pool Recovery", "sop_slug": "green-pool-recovery",
     "columns": ["Day 0", "Day 2", "Day 5", "Day 7 Reinspect", "Handoff to Weekly"]},
    {"slug": "sales-pipeline", "title": "Sales Pipeline", "sop_slug": "sales-consult-call",
     "columns": ["New Lead", "Contacted", "Consult Scheduled", "Proposal", "Won"]},
]


async def _seed_for_tenant(tenant_id: str) -> None:
    """Idempotent per-tenant seed. Only fills gaps."""
    # SOPs
    for s in SEED_SOPS:
        exists = await db.sops.find_one(
            {"tenant_id": tenant_id, "slug": s["slug"]}, {"_id": 0}
        )
        if not exists:
            await db.sops.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "version": 1, "created_at": now_iso(), **s
            })
    # Role defs
    for r in SEED_ROLES:
        exists = await db.role_definitions.find_one(
            {"tenant_id": tenant_id, "slug": r["slug"]}, {"_id": 0}
        )
        if not exists:
            await db.role_definitions.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "created_at": now_iso(), **r
            })
    # LeanBoards
    for lb in SEED_LEANBOARDS:
        exists = await db.leanboards.find_one(
            {"tenant_id": tenant_id, "slug": lb["slug"]}, {"_id": 0}
        )
        if not exists:
            await db.leanboards.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "created_at": now_iso(), **lb
            })
    # KPI scorecards — one row per role using kpi labels from SEED_ROLES,
    # target/actual placeholders that the customer edits in the UI.
    for r in SEED_ROLES:
        exists = await db.kpi_scorecards.find_one(
            {"tenant_id": tenant_id, "role_slug": r["slug"]}, {"_id": 0}
        )
        if not exists:
            metrics = [
                {"label": k, "target": 100, "actual": 0, "unit": "%",
                 "yellow_at": 80, "red_at": 60}
                for k in r["kpis"]
            ]
            await db.kpi_scorecards.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "role_slug": r["slug"], "role_title": r["title"],
                "metrics": metrics, "created_at": now_iso(),
            })


async def seed_business_os() -> None:
    """Seed every existing tenant. Called at startup + when a tenant is created."""
    tenants = await db.tenants.find({}, {"_id": 0}).to_list(500)
    for t in tenants:
        await _seed_for_tenant(t["id"])
    logger.info(f"Phase 16 · Business OS seeded for {len(tenants)} tenant(s)")


# ─── AI helper (Lana persona) ──────────────────────────────────────────────
async def _ai_generate(system_prompt: str, user_prompt: str,
                       max_tokens: int = 800,
                       tenant_id: Optional[str] = None) -> str:
    """Best-effort LLM call. Silent stub when EMERGENT_LLM_KEY is missing.

    Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the central
    AI chokepoint so per-tenant BYO keys + AI spend caps apply. On
    cap-exceeded / error we degrade to a friendly stub instead of
    raising so the SOP / huddle / retro drafters remain resilient."""
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return "(AI-stub — set EMERGENT_LLM_KEY to enable Lana's generation.)"
    try:
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        result = await call_llm_with_fallback(
            system_prompt=system_prompt, user_text=user_prompt,
            provider="anthropic", model="claude-sonnet-4-5",
            tenant_id=tenant_id,
            parse_json=False,
            max_tokens=max_tokens,
        )
        if is_ai_cap_exceeded(result):
            return "(AI unavailable — monthly spend cap reached.)"
        if result.get("error"):
            return f"(AI unavailable — {result.get('error')})"
        return ((result.get("raw") or {}).get("text") or "").strip()
    except Exception as e:
        logger.warning(f"Lana AI generation failed: {e}")
        return f"(AI unavailable — {e})"


LANA_SYSTEM = (
    "You are Lana, the Business Operating System coach for a pool & landscape service company. "
    "You draft SOPs, huddle agendas, and sprint retros in the style of Traction / EOS. "
    "Be terse, structured, actionable. Prefer bulleted lists."
)


# ─── Item A · SOP Library ──────────────────────────────────────────────────
class SopIn(BaseModel):
    title: str
    category: Optional[str] = "General"
    owner_role: Optional[str] = ""
    content: Optional[str] = ""
    slug: Optional[str] = None


class SopGenReq(BaseModel):
    title: str
    category: Optional[str] = "General"
    hint: Optional[str] = ""


@router.get("/sops")
async def list_sops(admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    return await db.sops.find({"tenant_id": tenant["id"]}, {"_id": 0}).sort("category", 1).to_list(500)


@router.post("/sops")
async def create_sop(body: SopIn, admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    doc = {"id": new_id(), "tenant_id": tenant["id"], "version": 1,
           "created_at": now_iso(),
           **body.dict()}
    if not doc.get("slug"):
        doc["slug"] = doc["title"].lower().replace(" ", "-")[:60]
    await db.sops.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/sops/{sid}")
async def update_sop(sid: str, body: SopIn, admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    r = await db.sops.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": upd, "$inc": {"version": 1}},
    )
    if not r.matched_count:
        raise HTTPException(404, "SOP not found")
    return await db.sops.find_one({"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/sops/{sid}")
async def delete_sop(sid: str, admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    await db.sops.delete_one({"id": sid, "tenant_id": tenant["id"]})
    return {"ok": True}


@router.post("/sops/generate")
async def generate_sop(body: SopGenReq, admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    prompt = (
        f"Draft a step-by-step SOP for a pool & landscape company.\n"
        f"Title: {body.title}\nCategory: {body.category}\n"
        f"Extra context: {body.hint or 'none'}\n"
        f"Format as a numbered list of concrete tech-friendly steps."
    )
    content = await _ai_generate(LANA_SYSTEM, prompt, max_tokens=600)
    return {"title": body.title, "category": body.category, "content": content}


# ─── Item B · Role Definitions ─────────────────────────────────────────────
class RoleDefIn(BaseModel):
    title: str
    slug: Optional[str] = None
    reports_to: Optional[str] = None
    responsibilities: Optional[List[str]] = []
    kpis: Optional[List[str]] = []


@router.get("/role-definitions")
async def list_roles(admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    return await db.role_definitions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(500)


@router.post("/role-definitions")
async def create_role(body: RoleDefIn, admin: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    doc = {"id": new_id(), "tenant_id": tenant["id"], "created_at": now_iso(),
           **body.dict()}
    if not doc.get("slug"):
        doc["slug"] = doc["title"].lower().replace(" ", "_")[:40]
    await db.role_definitions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/role-definitions/{rid}")
async def update_role(rid: str, body: RoleDefIn,
                      admin: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    r = await db.role_definitions.update_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    if not r.matched_count:
        raise HTTPException(404, "Role not found")
    return await db.role_definitions.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/role-definitions/{rid}")
async def delete_role(rid: str, admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    await db.role_definitions.delete_one({"id": rid, "tenant_id": tenant["id"]})
    return {"ok": True}


# ─── Item C · KPI Scorecards ───────────────────────────────────────────────
class MetricIn(BaseModel):
    label: str
    target: float = 100
    actual: float = 0
    unit: Optional[str] = "%"
    yellow_at: Optional[float] = 80
    red_at: Optional[float] = 60


class ScorecardIn(BaseModel):
    role_slug: str
    role_title: Optional[str] = ""
    metrics: List[MetricIn] = []


def _rag(actual: float, target: float, yellow: float, red: float) -> str:
    """Return 'green' | 'yellow' | 'red' based on actual vs. thresholds."""
    if target <= 0:
        return "green"
    pct = (actual / target) * 100 if target else 0
    if pct >= yellow:
        return "green"
    if pct >= red:
        return "yellow"
    return "red"


@router.get("/kpi-scorecards")
async def list_scorecards(admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    rows = await db.kpi_scorecards.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(500)
    # Attach RAG statuses
    for r in rows:
        for m in r.get("metrics", []):
            m["status"] = _rag(m.get("actual", 0), m.get("target", 100),
                                m.get("yellow_at", 80), m.get("red_at", 60))
    return rows


@router.post("/kpi-scorecards")
async def upsert_scorecard(body: ScorecardIn, admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    doc = {"tenant_id": tenant["id"], "role_slug": body.role_slug,
           "role_title": body.role_title,
           "metrics": [m.dict() for m in body.metrics],
           "updated_at": now_iso()}
    existing = await db.kpi_scorecards.find_one(
        {"tenant_id": tenant["id"], "role_slug": body.role_slug}, {"_id": 0}
    )
    if existing:
        await db.kpi_scorecards.update_one(
            {"tenant_id": tenant["id"], "role_slug": body.role_slug},
            {"$set": doc},
        )
        return {**existing, **doc}
    doc.update({"id": new_id(), "created_at": now_iso()})
    await db.kpi_scorecards.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ─── Item D · Crew Huddle ──────────────────────────────────────────────────
class HuddleIn(BaseModel):
    date: str  # YYYY-MM-DD
    title: Optional[str] = "Daily Huddle"
    attendees: Optional[List[str]] = []


class HuddleActionIn(BaseModel):
    huddle_id: str
    text: str
    owner_user_id: Optional[str] = None
    due_date: Optional[str] = None


@router.get("/huddles")
async def list_huddles(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    rows = await db.huddles.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("date", -1).to_list(60)
    return rows


@router.post("/huddles")
async def create_huddle(body: HuddleIn,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    doc = {"id": new_id(), "tenant_id": tenant["id"],
           "created_at": now_iso(), "action_items": [],
           **body.dict()}
    await db.huddles.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/huddles/{hid}")
async def get_huddle(hid: str, admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    doc = await db.huddles.find_one(
        {"id": hid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Huddle not found")
    return doc


@router.post("/huddles/{hid}/agenda")
async def draft_agenda(hid: str, admin: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Lana drafts a Traction-style Level-10 agenda for the huddle."""
    huddle = await db.huddles.find_one(
        {"id": hid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not huddle:
        raise HTTPException(404, "Huddle not found")
    # Load context: today's open jobs + open action items.
    open_jobs = await db.jobs.count_documents(
        {"tenant_id": tenant["id"], "status": {"$in": ["pending", "active"]}}
    )
    open_tasks = await db.tasks.count_documents(
        {"tenant_id": tenant["id"], "status": {"$ne": "done"}}
    )
    prompt = (
        f"Draft a 15-minute morning crew huddle agenda for a pool & landscape company.\n"
        f"Date: {huddle.get('date')}\n"
        f"Open jobs today: {open_jobs}. Open action items: {open_tasks}.\n"
        f"Use headings: 1) Wins & Recognition, 2) KPI Check, 3) Rocks, "
        f"4) Customer / Issues, 5) IDS (Identify-Discuss-Solve), 6) Action Items."
    )
    agenda = await _ai_generate(LANA_SYSTEM, prompt, max_tokens=500)
    await db.huddles.update_one(
        {"id": hid, "tenant_id": tenant["id"]},
        {"$set": {"agenda": agenda, "agenda_generated_at": now_iso()}},
    )
    return {"agenda": agenda}


@router.post("/huddles/{hid}/action-items")
async def add_action_item(hid: str, body: HuddleActionIn,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    huddle = await db.huddles.find_one(
        {"id": hid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not huddle:
        raise HTTPException(404, "Huddle not found")
    # Create a task in the shared tasks collection so it flows into the Tasks screen.
    task = {
        "id": new_id(), "tenant_id": tenant["id"],
        "title": body.text, "status": "open",
        "source": f"huddle:{hid}",
        "assignee_user_id": body.owner_user_id,
        "due_date": body.due_date,
        "created_at": now_iso(),
    }
    await db.tasks.insert_one(task)
    action = {"id": task["id"], "text": body.text,
              "owner_user_id": body.owner_user_id,
              "due_date": body.due_date, "task_id": task["id"]}
    await db.huddles.update_one(
        {"id": hid, "tenant_id": tenant["id"]},
        {"$push": {"action_items": action}},
    )
    task.pop("_id", None)
    return {"action": action, "task": task}


# ─── Item E · LeanBoards ───────────────────────────────────────────────────
class BoardCardIn(BaseModel):
    board_id: str
    column: str
    title: str
    body: Optional[str] = ""
    linked_customer_id: Optional[str] = None
    linked_job_id: Optional[str] = None


class BoardCardMove(BaseModel):
    column: str


@router.get("/leanboards")
async def list_leanboards(admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    return await db.leanboards.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(50)


@router.get("/leanboards/{bid}/cards")
async def list_board_cards(bid: str, admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    return await db.leanboard_cards.find(
        {"tenant_id": tenant["id"], "board_id": bid}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)


@router.post("/leanboards/{bid}/cards")
async def create_board_card(bid: str, body: BoardCardIn,
                             admin: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    board = await db.leanboards.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not board:
        raise HTTPException(404, "Board not found")
    if body.column not in board.get("columns", []):
        raise HTTPException(400, "Invalid column for this board")
    doc = {"id": new_id(), "tenant_id": tenant["id"], "board_id": bid,
           "column": body.column, "title": body.title, "body": body.body or "",
           "linked_customer_id": body.linked_customer_id,
           "linked_job_id": body.linked_job_id,
           "created_at": now_iso()}
    await db.leanboard_cards.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/leanboards/cards/{cid}/move")
async def move_card(cid: str, body: BoardCardMove,
                    admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    card = await db.leanboard_cards.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not card:
        raise HTTPException(404, "Card not found")
    board = await db.leanboards.find_one(
        {"id": card["board_id"], "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if body.column not in (board or {}).get("columns", []):
        raise HTTPException(400, "Invalid column")
    await db.leanboard_cards.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"column": body.column, "moved_at": now_iso()}},
    )
    return {"ok": True, "column": body.column}


@router.delete("/leanboards/cards/{cid}")
async def delete_card(cid: str, admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    await db.leanboard_cards.delete_one(
        {"id": cid, "tenant_id": tenant["id"]}
    )
    return {"ok": True}


# ─── Item F · Sprint Planner ───────────────────────────────────────────────
class SprintIn(BaseModel):
    week_start: str  # YYYY-MM-DD (Monday)
    theme: Optional[str] = ""
    goals: Optional[List[str]] = []


class SprintReviewIn(BaseModel):
    wins: Optional[List[str]] = []
    misses: Optional[List[str]] = []
    retro_kaizen: Optional[List[str]] = []
    score: Optional[int] = None  # 1-10 self-rating


@router.get("/sprints")
async def list_sprints(admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    return await db.sprints.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("week_start", -1).to_list(60)


@router.post("/sprints")
async def create_sprint(body: SprintIn, admin: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    doc = {"id": new_id(), "tenant_id": tenant["id"],
           "state": "planned", "created_at": now_iso(),
           **body.dict()}
    await db.sprints.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/sprints/{sid}")
async def get_sprint(sid: str, admin: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    doc = await db.sprints.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Sprint not found")
    return doc


@router.put("/sprints/{sid}/review")
async def save_review(sid: str, body: SprintReviewIn,
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    r = await db.sprints.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"review": body.dict(), "state": "reviewed",
                  "reviewed_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Sprint not found")
    return await db.sprints.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.post("/sprints/{sid}/retro-ai")
async def draft_retro(sid: str, admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    s = await db.sprints.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not s:
        raise HTTPException(404, "Sprint not found")
    prompt = (
        f"Draft a weekly retrospective for week of {s.get('week_start')} "
        f"theme='{s.get('theme') or 'n/a'}'.\n"
        f"Planned goals: {s.get('goals') or []}\n"
        f"Wins so far: {s.get('review', {}).get('wins') or []}\n"
        f"Misses: {s.get('review', {}).get('misses') or []}\n"
        f"Return three sections: 'Keep', 'Stop', 'Start' — 3 bullets each."
    )
    text = await _ai_generate(LANA_SYSTEM, prompt, max_tokens=400)
    await db.sprints.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"retro_ai": text, "retro_ai_at": now_iso()}},
    )
    return {"retro": text}


# ─── Item G · Four Pillars overview ────────────────────────────────────────
@router.get("/os/overview")
async def four_pillars(admin: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Roll up the four pillars: Ops / Finance / People / Customer.
    Aggregated view for the /os landing page."""
    tid = tenant["id"]
    open_jobs = await db.jobs.count_documents(
        {"tenant_id": tid, "status": {"$in": ["pending", "active"]}}
    )
    completed_jobs = await db.jobs.count_documents(
        {"tenant_id": tid, "status": "completed"}
    )
    unpaid_invoices = await db.quotes.count_documents(
        {"tenant_id": tid, "doc_type": "invoice", "payment_status": "unpaid"}
    )
    paid_invoices = await db.quotes.count_documents(
        {"tenant_id": tid, "doc_type": "invoice", "payment_status": "paid"}
    )
    total_customers = await db.customers.count_documents({"tenant_id": tid})
    total_techs = await db.technicians.count_documents({"tenant_id": tid})
    open_tasks = await db.tasks.count_documents(
        {"tenant_id": tid, "status": {"$ne": "done"}}
    )
    latest_sprint = await db.sprints.find_one(
        {"tenant_id": tid}, {"_id": 0}, sort=[("week_start", -1)]
    )
    latest_huddle = await db.huddles.find_one(
        {"tenant_id": tid}, {"_id": 0}, sort=[("date", -1)]
    )
    # CSAT — try tenant-scoped; skip silently if collection empty.
    try:
        csat_docs = await db.csat_surveys.find(
            {"tenant_id": tid, "score": {"$exists": True}},
            {"_id": 0, "score": 1}
        ).to_list(500)
        csat_avg = round(sum(d["score"] for d in csat_docs) / len(csat_docs), 2) if csat_docs else None
    except Exception:
        csat_avg = None
    return {
        "ops": {
            "open_jobs": open_jobs, "completed_jobs": completed_jobs,
            "open_tasks": open_tasks,
            "latest_sprint": latest_sprint, "latest_huddle": latest_huddle,
        },
        "finance": {
            "unpaid_invoices": unpaid_invoices,
            "paid_invoices": paid_invoices,
        },
        "people": {
            "technicians": total_techs,
            "roles_defined": await db.role_definitions.count_documents({"tenant_id": tid}),
            "sops": await db.sops.count_documents({"tenant_id": tid}),
        },
        "customer": {
            "total_customers": total_customers,
            "csat_avg": csat_avg,
        },
    }


# ─── Item C+ · KPI auto-recompute ──────────────────────────────────────────
async def _tenant_kpi_actuals(tenant_id: str) -> dict:
    """Compute a small canonical set of live KPI values from real collections.
    Only the labels that match are auto-populated; the rest keep their manual value."""
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    month_ago = (now - _td(days=30)).isoformat()
    seven_ago = (now - _td(days=7)).isoformat()

    completed_last30 = await db.jobs.count_documents(
        {"tenant_id": tenant_id, "status": "completed",
         "updated_at": {"$gte": month_ago}}
    )
    # On-time %: jobs completed on or before scheduled_date over last 30d.
    on_time_ok = await db.jobs.count_documents(
        {"tenant_id": tenant_id, "status": "completed",
         "updated_at": {"$gte": month_ago},
         "$expr": {"$lte": ["$updated_at", "$scheduled_date"]}}
    )
    on_time_pct = round(100 * on_time_ok / completed_last30, 1) if completed_last30 else 0

    # Revenue last 30d (from paid invoices)
    paid_cursor = db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice",
         "payment_status": "paid", "paid_at": {"$gte": month_ago}},
        {"_id": 0, "total": 1},
    )
    revenue_30 = round(sum([(d.get("total") or 0) async for d in paid_cursor]), 2)

    # Callbacks: any job in last 7d flagged as callback (best-effort — some tenants tag it).
    callbacks = await db.jobs.count_documents(
        {"tenant_id": tenant_id, "callback": True, "updated_at": {"$gte": seven_ago}}
    )
    # CSAT avg
    csat_avg = 0.0
    try:
        csat_docs = await db.csat_surveys.find(
            {"tenant_id": tenant_id, "score": {"$exists": True}},
            {"_id": 0, "score": 1}
        ).to_list(500)
        if csat_docs:
            csat_avg = round(sum(d["score"] for d in csat_docs) / len(csat_docs), 2)
    except Exception:
        pass

    return {
        "Net profit %": None,          # left manual
        "On-time %": on_time_pct,
        "First-visit fix %": None,
        "Callback rate": callbacks,
        "CSAT ≥ 4.7": csat_avg,
        "CSAT ≥ 4.6": csat_avg,
        "Hours billable": None,
        "Stops/day": None,
        "Close rate": None,
        "Avg ticket": None,
        "MQL/month": None,
        "Blog rank ≥ #10": None,
        "Review rate ≥ 20%": None,
        "Route density": None,
        "Owner hours/week": None,
        "Cash-on-hand": None,
        "Photo compliance %": None,
        "Speed-to-lead ≤ 5 min": None,
        "First-response ≤ 10 min": None,
        "Tickets closed/day": None,
        "Portal usage %": None,
        "AR aging ≤ 45d avg": None,
        "Invoices sent ≤ 24hr": None,
        "_revenue_30": revenue_30,
        "_completed_last30": completed_last30,
    }


@router.post("/business-os/kpis/recompute")
async def kpi_recompute(admin: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Pull actuals from `jobs`, `quotes`, `csat_surveys` and update every
    KPI scorecard row where the metric label matches a known auto-source."""
    tid = tenant["id"]
    actuals = await _tenant_kpi_actuals(tid)
    scorecards = await db.kpi_scorecards.find({"tenant_id": tid}, {"_id": 0}).to_list(500)
    updated = 0
    for row in scorecards:
        dirty = False
        for m in row.get("metrics", []):
            val = actuals.get(m.get("label"))
            if val is not None:
                m["actual"] = float(val)
                dirty = True
        if dirty:
            await db.kpi_scorecards.update_one(
                {"tenant_id": tid, "role_slug": row["role_slug"]},
                {"$set": {"metrics": row["metrics"],
                          "auto_recomputed_at": now_iso()}},
            )
            updated += 1
    return {"ok": True, "updated_scorecards": updated,
            "revenue_30d": actuals.get("_revenue_30"),
            "completed_30d": actuals.get("_completed_last30")}


# ─── Item H · Lana AI chat ────────────────────────────────────────────────
class LanaScheduleCommitIn(BaseModel):
    customer_id: str
    service_type: str
    scheduled_date: str
    title: Optional[str] = None


@router.post("/business-os/lana/schedule/commit")
async def lana_schedule_commit(body: LanaScheduleCommitIn,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    """Phase 49 · Feb-2026 — write a job Lana previewed in a prior
    turn. Split from ``/lana/chat`` so the mobile UI can render an
    explicit "Confirm / Cancel" step (per Phase 49 scope: no
    single-turn write)."""
    from services.lana import schedule_intent as _sched
    out = await _sched.commit(
        db,
        tenant_id=tenant["id"],
        actor_user_id=user.get("id"),
        customer_id=body.customer_id,
        service_type=body.service_type,
        scheduled_date=body.scheduled_date,
        title=body.title,
    )
    return out


class LanaChatIn(BaseModel):
    message: str
    conversation_id: Optional[str] = None


@router.post("/business-os/lana/chat")
async def lana_chat(body: LanaChatIn,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    """Chat with Lana — the "COO in a box" AI persona scoped to business ops.

    Phase 49 · Feb-2026 — before the chat round-trip, classify the user
    turn against a small intent taxonomy (see
    :mod:`services.lana.intent`). Non-chat intents short-circuit into
    the todo / reminder services or, for schedule_job, return a
    preview card the caller confirms via a second call to
    ``/business-os/lana/schedule/commit``.
    """
    # ── Phase 49 intent routing ───────────────────────────────────────
    from services.lana import intent as _intent
    from services.lana import todos as _todos_svc
    from services.lana import reminders as _reminders_svc
    from services.lana import schedule_intent as _sched
    if _intent.looks_destructive(body.message):
        return {
            "reply": "For deletes / cancels / refunds please use the admin console — "
                     "I only create and schedule.",
            "intent": {"kind": "chat"},
            "mocked": False,
        }
    parsed = _intent.classify(body.message)
    if parsed.kind == "add_todo":
        row = await _todos_svc.create_todo(
            db, tenant_id=tenant["id"], user_id=user["id"],
            text=parsed.args["text"],
        )
        return {
            "reply": f'Added todo: "{row["text"]}"',
            "intent": {"kind": "add_todo", "todo": row},
        }
    if parsed.kind == "set_reminder":
        row = await _reminders_svc.create_reminder(
            db, tenant_id=tenant["id"], user_id=user["id"],
            text=parsed.args["text"],
            remind_at=parsed.args["remind_at"],
            phone=user.get("phone"),
        )
        return {
            "reply": f'Reminder set for {row["remind_at"]}: "{row["text"]}"',
            "intent": {"kind": "set_reminder", "reminder": row},
        }
    if parsed.kind == "schedule_job":
        preview = await _sched.preview(
            db, tenant_id=tenant["id"],
            customer_name=parsed.args["customer_name"],
            service_type=parsed.args["service_type"],
            scheduled_date=parsed.args["scheduled_date"],
        )
        if not preview.get("ok"):
            return {
                "reply": f"I couldn't find a customer matching "
                          f"\"{parsed.args['customer_name']}\". "
                          "Please try the full name or create the customer first.",
                "intent": {"kind": "schedule_job", "preview": preview},
            }
        p = preview["preview"]
        return {
            "reply": (
                f"Ready to book {p['service_type']} for {p['customer_name']} "
                f"on {p['scheduled_date']}. Say Confirm to write it."
            ),
            "intent": {"kind": "schedule_job", "preview": {
                "ok": True,
                **p,
            }},
        }

    # ── Falls through to the existing chat path ───────────────────────
    conv_id = body.conversation_id or new_id()
    thread = await db.lana_conversations.find_one(
        {"id": conv_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    history: List[dict] = (thread or {}).get("messages", [])
    history.append({"role": "user", "text": body.message, "ts": now_iso()})

    # Load tenant context so Lana speaks from your data.
    open_jobs = await db.jobs.count_documents(
        {"tenant_id": tenant["id"], "status": {"$in": ["pending", "active"]}}
    )
    open_tasks = await db.tasks.count_documents(
        {"tenant_id": tenant["id"], "status": {"$ne": "done"}}
    )
    sop_titles = [s["title"] for s in await db.sops.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "title": 1}).to_list(30)]
    role_titles = [r["title"] for r in await db.role_definitions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "title": 1}).to_list(20)]

    system = (
        f"{LANA_SYSTEM}\n\n"
        # Feb-2026 · P22 — Do NOT interpolate the operator's real name
        # or email into the LLM system prompt. Role is sufficient
        # context for Lana to answer operational questions. The
        # tenant business name is public (GBP / website) and safe.
        f"You are speaking with a {user.get('role') or 'staff member'} "
        f"at tenant {tenant.get('name')}.\n"
        f"Live context: {open_jobs} open jobs, {open_tasks} open tasks.\n"
        f"Known SOPs: {sop_titles or 'none'}.\n"
        f"Defined roles: {role_titles or 'none'}.\n"
        f"When asked to draft SOPs, role docs, or huddle agendas, respond in bullets."
    )

    mocked = False
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        reply = ("(Lana is running in MOCK mode — set EMERGENT_LLM_KEY to "
                 "enable real answers.) I noted your question: "
                 f"\"{body.message}\". In production I would draft a response "
                 "using your tenant's live SOPs, roles, KPIs, and huddle history.")
        mocked = True
    else:
        try:
            # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
            # central AI chokepoint so per-tenant BYO keys + AI spend
            # caps apply. Plaintext (``parse_json=False``) preserves
            # the legacy string return for the Lana chat surface.
            from services.llm_provider import call_llm_with_fallback
            from services.ai.cap_http import is_ai_cap_exceeded
            result = await call_llm_with_fallback(
                system_prompt=system, user_text=body.message,
                provider="anthropic", model="claude-sonnet-4-5",
                tenant_id=tenant["id"],
                parse_json=False,
            )
            if is_ai_cap_exceeded(result):
                reply = "(Lana AI unavailable — monthly spend cap reached.)"
                mocked = True
            elif result.get("error"):
                reply = f"(Lana AI unavailable — {result.get('error')})"
                mocked = True
            else:
                reply = ((result.get("raw") or {}).get("text") or "").strip()
        except Exception as e:
            logger.warning(f"Lana chat error: {e}")
            reply = f"(Lana AI unavailable — {e})"
            mocked = True

    history.append({"role": "assistant", "text": reply, "ts": now_iso()})
    await db.lana_conversations.update_one(
        {"id": conv_id, "tenant_id": tenant["id"]},
        {"$set": {"messages": history, "updated_at": now_iso(),
                  "user_id": user["id"]},
         "$setOnInsert": {"id": conv_id, "tenant_id": tenant["id"],
                          "created_at": now_iso()}},
        upsert=True,
    )
    return {
        "conversation_id": conv_id,
        "reply": reply,
        "mocked": mocked,
        "messages": history,
    }


@router.get("/business-os/lana/conversations")
async def lana_list_conversations(user: dict = Depends(get_current_user),
                                   tenant: dict = Depends(get_current_tenant)):
    rows = await db.lana_conversations.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "updated_at": 1, "messages": 1}
    ).sort("updated_at", -1).to_list(50)
    for r in rows:
        msgs = r.get("messages") or []
        r["last_message"] = msgs[-1]["text"] if msgs else ""
        r["message_count"] = len(msgs)
        r.pop("messages", None)
    return rows
