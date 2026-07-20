"""QuoteIQ Phase Q1 · Sub-scope C — Pipelines CRM (Kanban).

Three collections, all tenant-scoped:

* ``deal_pipelines`` — the Kanban boards. Each has an ordered list of
  stages with color + probability. Every tenant gets a default pipeline
  seeded lazily on first read.
* ``deals`` — cards on the board. Carry title, value, contact,
  probability, owner, stage, and status (``open|won|lost``).
* ``deal_events`` — append-only timeline: stage_change, note,
  value_change, owner_change, won, lost.

RBAC follows the platform convention — admin + super_admin write, all
authenticated users of the tenant read. No dedicated sales roles exist
today (per audit), so we fall back to ``require_admin`` for writes as
the brief allowed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, require_admin, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["Pipelines CRM"])


DEFAULT_PIPELINE_STAGES = [
    {"name": "New Lead", "color": "#94A3B8", "probability_pct": 10},
    {"name": "Contacted", "color": "#38BDF8", "probability_pct": 25},
    {"name": "Qualified", "color": "#0EA5E9", "probability_pct": 50},
    {"name": "Estimate Sent", "color": "#F59E0B", "probability_pct": 70},
    {"name": "Won", "color": "#22C55E", "probability_pct": 100},
    {"name": "Lost", "color": "#EF4444", "probability_pct": 0},
]


def _slugify(name: str) -> str:
    s = "".join(c if c.isalnum() or c == " " else "" for c in (name or ""))
    return s.strip().lower().replace(" ", "-") or f"pipeline-{new_id()[:8]}"


def _build_default_pipeline(tenant_id: str) -> Dict[str, Any]:
    stages = []
    for i, s in enumerate(DEFAULT_PIPELINE_STAGES):
        stages.append({
            "id": new_id(),
            "name": s["name"],
            "order": i,
            "color": s["color"],
            "probability_pct": s["probability_pct"],
        })
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "name": "Default Sales Pipeline",
        "slug": "default-sales-pipeline",
        "stages": stages,
        "is_default": True,
        "archived_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


async def _ensure_default_pipeline(tenant_id: str) -> None:
    existing = await db.deal_pipelines.find_one(
        {"tenant_id": tenant_id, "is_default": True}, {"_id": 0})
    if existing:
        return
    await db.deal_pipelines.insert_one(_build_default_pipeline(tenant_id))


# ═════════════════════════════════════════════════════════════════════
# Pipeline models + endpoints
# ═════════════════════════════════════════════════════════════════════

class StageIn(BaseModel):
    id: Optional[str] = None
    name: str
    order: int
    color: Optional[str] = "#94A3B8"
    probability_pct: int = Field(0, ge=0, le=100)


class PipelineIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: Optional[str] = None
    stages: List[StageIn] = Field(default_factory=list)


class PipelinePatch(BaseModel):
    name: Optional[str] = None
    stages: Optional[List[StageIn]] = None
    archived_at: Optional[str] = None


@router.get("/deal-pipelines")
async def list_pipelines(user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    await _ensure_default_pipeline(tenant["id"])
    rows = await db.deal_pipelines.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return {"count": len(rows), "pipelines": rows}


@router.post("/deal-pipelines", status_code=201)
async def create_pipeline(body: PipelineIn,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    slug = body.slug or _slugify(body.name)
    if await db.deal_pipelines.find_one(
            {"tenant_id": tenant["id"], "slug": slug}, {"_id": 0}):
        raise HTTPException(409, "pipeline slug already exists")
    stages = []
    for i, s in enumerate(body.stages or []):
        stages.append({
            "id": s.id or new_id(),
            "name": s.name, "order": s.order,
            "color": s.color or "#94A3B8",
            "probability_pct": int(s.probability_pct),
        })
    if not stages:
        stages = _build_default_pipeline(tenant["id"])["stages"]
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": body.name,
        "slug": slug,
        "stages": stages,
        "is_default": False,
        "archived_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.deal_pipelines.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/deal-pipelines/{pid}")
async def get_pipeline(pid: str,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    row = await db.deal_pipelines.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "pipeline not found")
    return row


@router.patch("/deal-pipelines/{pid}")
async def patch_pipeline(pid: str, body: PipelinePatch,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    row = await db.deal_pipelines.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "pipeline not found")
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if body.name is not None:
        upd["name"] = body.name
    if body.stages is not None:
        stages = []
        for i, s in enumerate(body.stages):
            stages.append({
                "id": s.id or new_id(),
                "name": s.name, "order": s.order,
                "color": s.color or "#94A3B8",
                "probability_pct": int(s.probability_pct),
            })
        upd["stages"] = stages
    if body.archived_at is not None:
        upd["archived_at"] = body.archived_at
    await db.deal_pipelines.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.deal_pipelines.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/deal-pipelines/{pid}", status_code=204)
async def delete_pipeline(pid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.deal_pipelines.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "pipeline not found")
    if row.get("is_default"):
        raise HTTPException(400, "default pipeline cannot be deleted")
    # Reject if deals reference this pipeline.
    ndeals = await db.deals.count_documents(
        {"tenant_id": tenant["id"], "pipeline_id": pid})
    if ndeals:
        raise HTTPException(400, f"pipeline has {ndeals} deals attached")
    await db.deal_pipelines.delete_one({"id": pid, "tenant_id": tenant["id"]})
    return None


# ═════════════════════════════════════════════════════════════════════
# Deal models + endpoints
# ═════════════════════════════════════════════════════════════════════

class DealIn(BaseModel):
    pipeline_id: Optional[str] = None
    stage_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=200)
    customer_id: Optional[str] = None
    contact_name: Optional[str] = ""
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    value_cents: Optional[int] = 0
    expected_close_date: Optional[str] = None
    probability_pct: Optional[int] = None
    owner_user_id: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = ""
    source: Optional[str] = ""


class DealPatch(BaseModel):
    title: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    value_cents: Optional[int] = None
    expected_close_date: Optional[str] = None
    probability_pct: Optional[int] = None
    owner_user_id: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class MoveIn(BaseModel):
    stage_id: str
    note: Optional[str] = ""


class LostIn(BaseModel):
    lost_reason: Optional[str] = ""


async def _log_event(tenant_id: str, deal_id: str, kind: str, *,
                       from_value: Any = None, to_value: Any = None,
                       actor_user_id: Optional[str] = None,
                       meta: Optional[Dict[str, Any]] = None) -> None:
    await db.deal_events.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "deal_id": deal_id,
        "type": kind,
        "from_value": from_value,
        "to_value": to_value,
        "actor_user_id": actor_user_id,
        "meta": meta or {},
        "created_at": now_iso(),
    })


async def _resolve_pipeline_and_stage(tenant_id: str,
                                        pipeline_id: Optional[str],
                                        stage_id: Optional[str]
                                        ) -> Dict[str, Any]:
    """Return the pipeline doc + the resolved stage dict. If either is
    None, pick the default pipeline + its first stage."""
    if pipeline_id:
        pipeline = await db.deal_pipelines.find_one(
            {"id": pipeline_id, "tenant_id": tenant_id}, {"_id": 0})
        if not pipeline:
            raise HTTPException(422, "pipeline_id not found for this tenant")
    else:
        await _ensure_default_pipeline(tenant_id)
        pipeline = await db.deal_pipelines.find_one(
            {"tenant_id": tenant_id, "is_default": True}, {"_id": 0})
    stages = pipeline.get("stages") or []
    stage = None
    if stage_id:
        stage = next((s for s in stages if s["id"] == stage_id), None)
        if not stage:
            raise HTTPException(422, "stage_id not found on pipeline")
    else:
        stage = stages[0] if stages else None
    return {"pipeline": pipeline, "stage": stage}


@router.get("/deals")
async def list_deals(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant),
                       pipeline_id: Optional[str] = Query(None),
                       stage_id: Optional[str] = Query(None),
                       owner_user_id: Optional[str] = Query(None),
                       customer_id: Optional[str] = Query(None),
                       status: Optional[str] = Query(None),
                       tag: Optional[str] = Query(None),
                       q: Optional[str] = Query(None),
                       limit: int = Query(200, ge=1, le=1000)):
    query: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if pipeline_id:
        query["pipeline_id"] = pipeline_id
    if stage_id:
        query["stage_id"] = stage_id
    if owner_user_id:
        query["owner_user_id"] = owner_user_id
    if customer_id:
        query["customer_id"] = customer_id
    if status:
        query["status"] = status
    if tag:
        query["tags"] = tag
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [{"title": rx}, {"contact_name": rx},
                         {"contact_email": rx}, {"notes": rx}]
    rows = await db.deals.find(query, {"_id": 0}) \
        .sort("updated_at", -1).to_list(limit)
    return {"count": len(rows), "deals": rows}


@router.post("/deals", status_code=201)
async def create_deal(body: DealIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    resolved = await _resolve_pipeline_and_stage(
        tenant["id"], body.pipeline_id, body.stage_id)
    pipeline = resolved["pipeline"]
    stage = resolved["stage"]
    if not stage:
        raise HTTPException(422, "pipeline has no stages")
    prob = body.probability_pct
    if prob is None:
        prob = int(stage.get("probability_pct") or 0)
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "pipeline_id": pipeline["id"],
        "stage_id": stage["id"],
        "title": body.title,
        "customer_id": body.customer_id,
        "contact_name": body.contact_name or "",
        "contact_email": (body.contact_email or "").lower() or None,
        "contact_phone": body.contact_phone or None,
        "value_cents": int(body.value_cents or 0),
        "expected_close_date": body.expected_close_date,
        "probability_pct": int(prob),
        "owner_user_id": body.owner_user_id or user.get("id"),
        "tags": list(body.tags or []),
        "notes": body.notes or "",
        "source": body.source or "",
        "lost_reason": None,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "stage_entered_at": now,
    }
    await db.deals.insert_one(doc)
    await _log_event(tenant["id"], doc["id"], "created",
                      to_value={"stage_id": stage["id"],
                                "stage_name": stage.get("name")},
                      actor_user_id=user.get("id"))
    doc.pop("_id", None)
    return doc


@router.get("/deals/pipeline-view")
async def pipeline_view(user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant),
                          pipeline_id: Optional[str] = Query(None)):
    await _ensure_default_pipeline(tenant["id"])
    if pipeline_id:
        pipeline = await db.deal_pipelines.find_one(
            {"id": pipeline_id, "tenant_id": tenant["id"]}, {"_id": 0})
    else:
        pipeline = await db.deal_pipelines.find_one(
            {"tenant_id": tenant["id"], "is_default": True}, {"_id": 0})
    if not pipeline:
        raise HTTPException(404, "pipeline not found")
    stages = pipeline.get("stages") or []
    deals = await db.deals.find(
        {"tenant_id": tenant["id"], "pipeline_id": pipeline["id"],
          "status": "open"}, {"_id": 0}
    ).sort("updated_at", -1).to_list(2000)
    by_stage: Dict[str, List[Dict[str, Any]]] = {s["id"]: [] for s in stages}
    for d in deals:
        by_stage.setdefault(d.get("stage_id"), []).append(d)
    columns = []
    for s in stages:
        col_deals = by_stage.get(s["id"], [])
        columns.append({
            "stage": s,
            "deal_count": len(col_deals),
            "total_value_cents": sum(int(d.get("value_cents") or 0)
                                       for d in col_deals),
            "deals": col_deals,
        })
    return {"pipeline": pipeline, "columns": columns}


@router.get("/deals/{did}/events")
async def deal_events(did: str,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant),
                        limit: int = Query(200, ge=1, le=1000)):
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1})
    if not row:
        raise HTTPException(404, "deal not found")
    rows = await db.deal_events.find(
        {"tenant_id": tenant["id"], "deal_id": did}, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return {"count": len(rows), "events": rows}


@router.get("/deals/{did}")
async def get_deal(did: str,
                     user: dict = Depends(get_current_user),
                     tenant: dict = Depends(get_current_tenant)):
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "deal not found")
    return row


@router.patch("/deals/{did}")
async def patch_deal(did: str, body: DealPatch,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "deal not found")
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if body.title is not None:
        upd["title"] = body.title
    if body.contact_name is not None:
        upd["contact_name"] = body.contact_name
    if body.contact_email is not None:
        upd["contact_email"] = (body.contact_email or "").lower() or None
    if body.contact_phone is not None:
        upd["contact_phone"] = body.contact_phone or None
    if body.expected_close_date is not None:
        upd["expected_close_date"] = body.expected_close_date
    if body.probability_pct is not None:
        upd["probability_pct"] = int(body.probability_pct)
    if body.tags is not None:
        upd["tags"] = list(body.tags)
    if body.notes is not None:
        upd["notes"] = body.notes
    if body.value_cents is not None:
        new_val = int(body.value_cents)
        old_val = int(row.get("value_cents") or 0)
        upd["value_cents"] = new_val
        if new_val != old_val:
            await _log_event(tenant["id"], did, "value_change",
                              from_value=old_val, to_value=new_val,
                              actor_user_id=user.get("id"))
    if body.owner_user_id is not None:
        old_owner = row.get("owner_user_id")
        new_owner = body.owner_user_id
        upd["owner_user_id"] = new_owner
        if new_owner != old_owner:
            await _log_event(tenant["id"], did, "owner_change",
                              from_value=old_owner, to_value=new_owner,
                              actor_user_id=user.get("id"))
    await db.deals.update_one(
        {"id": did, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/deals/{did}", status_code=204)
async def delete_deal(did: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.deals.delete_one({"id": did, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "deal not found")
    await db.deal_events.delete_many(
        {"tenant_id": tenant["id"], "deal_id": did})
    return None


@router.post("/deals/{did}/move")
async def move_deal(did: str, body: MoveIn,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "deal not found")
    pipeline = await db.deal_pipelines.find_one(
        {"id": row["pipeline_id"], "tenant_id": tenant["id"]}, {"_id": 0})
    stages = (pipeline or {}).get("stages") or []
    target = next((s for s in stages if s["id"] == body.stage_id), None)
    if not target:
        raise HTTPException(422, "stage_id not on this deal's pipeline")
    old_stage_id = row["stage_id"]
    old_stage = next((s for s in stages if s["id"] == old_stage_id), {})
    now = now_iso()
    upd = {
        "stage_id": target["id"],
        "probability_pct": int(target.get("probability_pct") or 0),
        "stage_entered_at": now,
        "updated_at": now,
    }
    await db.deals.update_one(
        {"id": did, "tenant_id": tenant["id"]}, {"$set": upd})
    await _log_event(tenant["id"], did, "stage_change",
                      from_value={"stage_id": old_stage_id,
                                    "name": old_stage.get("name")},
                      to_value={"stage_id": target["id"],
                                  "name": target.get("name")},
                      actor_user_id=user.get("id"),
                      meta={"note": body.note or ""})
    return await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/deals/{did}/won")
async def won_deal(did: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "deal not found")
    now = now_iso()
    await db.deals.update_one(
        {"id": did, "tenant_id": tenant["id"]},
        {"$set": {"status": "won", "probability_pct": 100,
                  "updated_at": now, "won_at": now}},
    )
    await _log_event(tenant["id"], did, "won",
                      from_value=row.get("status"),
                      to_value="won",
                      actor_user_id=user.get("id"))
    return await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/deals/{did}/lost")
async def lost_deal(did: str, body: LostIn,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "deal not found")
    now = now_iso()
    await db.deals.update_one(
        {"id": did, "tenant_id": tenant["id"]},
        {"$set": {"status": "lost", "probability_pct": 0,
                  "lost_reason": body.lost_reason or "",
                  "updated_at": now, "lost_at": now}},
    )
    await _log_event(tenant["id"], did, "lost",
                      from_value=row.get("status"),
                      to_value="lost",
                      actor_user_id=user.get("id"),
                      meta={"lost_reason": body.lost_reason or ""})
    return await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/deals/{did}/convert-to-job")
async def convert_to_job(did: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Mark the deal as won + create a jobs.<id> row referencing it.
    Keeps job creation minimal — the ops team can enrich later. If the
    deal has no ``customer_id``, we skip job creation and surface the
    reason (deal-only workflow completed as "won" regardless)."""
    row = await db.deals.find_one(
        {"id": did, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "deal not found")
    now = now_iso()
    # Won transition.
    await db.deals.update_one(
        {"id": did, "tenant_id": tenant["id"]},
        {"$set": {"status": "won", "probability_pct": 100,
                  "updated_at": now, "won_at": now}},
    )
    await _log_event(tenant["id"], did, "won",
                      from_value=row.get("status"), to_value="won",
                      actor_user_id=user.get("id"),
                      meta={"via": "convert_to_job"})

    if not row.get("customer_id"):
        return {"ok": True, "won": True, "job_id": None,
                "reason": "deal has no customer_id; skipped job creation"}

    job_id = new_id()
    job_doc = {
        "id": job_id,
        "tenant_id": tenant["id"],
        "customer_id": row["customer_id"],
        "title": row.get("title") or "Converted deal",
        "notes": row.get("notes") or "",
        "estimated_value_cents": int(row.get("value_cents") or 0),
        "status": "scheduled",
        "source_deal_id": did,
        "created_at": now,
        "updated_at": now,
    }
    await db.jobs.insert_one(job_doc)
    await _log_event(tenant["id"], did, "converted_to_job",
                      to_value={"job_id": job_id},
                      actor_user_id=user.get("id"))
    return {"ok": True, "won": True, "job_id": job_id}
