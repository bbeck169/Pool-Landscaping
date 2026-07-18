"""Phase 1 · Templates Library — backend routes.

Data model, RBAC, tenant isolation, and PDF export for 23 seeded system
templates + tenant-custom overrides. See PRD.md `Templates Library`
section for full scope + acceptance criteria.

Reuses:
  * `get_current_user`, `get_current_tenant` — auth/tenant deps
  * `document_generators._get_reportlab` + `_tenant_header` — PDF pipeline

Phase 4 · Batch A additions:
  * Signature fields now accept `{image_data_url, signer_name, signed_at}`
    and are embedded as a PNG flowable in the exported PDF.
  * New `POST /instances/{iid}/share-to-portal` endpoint writes the
    finalized instance's PDF into the shared `db.documents` collection
    (the same one that already backs the customer portal Documents page).

No changes to existing training / autobilling / Zillow / RingCentral /
document-generator code paths beyond registering this router.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, now_iso, notify_customer
from routers.tenants import get_current_tenant
from routers.document_generators import _get_reportlab, _tenant_header


router = APIRouter(prefix="/templates", tags=["templates"])


ALLOWED_CATEGORIES = {
    "pricing_money", "operations_checklists",
    "chemicals_chemistry", "documents",
}


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


def _role_of(user: dict) -> str:
    """Normalize the role for allowed_roles matching."""
    r = (user or {}).get("role") or ""
    if r == "technician":
        dept = (user or {}).get("department") or ""
        return "landscape_tech" if dept == "landscaping" else "pool_tech"
    return r


def _visible_to(user: dict, defn: dict) -> bool:
    roles = defn.get("allowed_roles") or ["admin", "super_admin"]
    return _role_of(user) in roles or user.get("role") in roles


# ─── Definitions ─────────────────────────────────────────────────────
class FieldIn(BaseModel):
    key: str
    label: str
    type: str
    required: bool = False
    help_text: Optional[str] = None
    default: Optional[Any] = None
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[List[str]] = None
    columns: Optional[List[Dict[str, Any]]] = None


class SectionIn(BaseModel):
    title: str
    fields: List[FieldIn] = []


class DefinitionIn(BaseModel):
    code: str
    title: str
    category: str
    description: Optional[str] = None
    schema: List[SectionIn]
    allowed_roles: List[str] = Field(default_factory=lambda: ["admin", "super_admin"])


class DefinitionPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    schema: Optional[List[SectionIn]] = None
    allowed_roles: Optional[List[str]] = None


@router.get("/definitions")
async def list_definitions(
    category: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"$or": [
        {"is_system": True},
        {"tenant_id": tenant["id"]},
    ]}
    if category:
        if category not in ALLOWED_CATEGORIES:
            raise HTTPException(422, f"unknown category: {category}")
        q["category"] = category
    rows = []
    async for d in db.template_definitions.find(q, {"_id": 0}).sort("title", 1):
        if _visible_to(user, d):
            rows.append(d)
    return {"count": len(rows), "rows": rows}


@router.get("/definitions/{code}")
async def get_definition(code: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    d = await db.template_definitions.find_one(
        {"code": code,
         "$or": [{"is_system": True}, {"tenant_id": tenant["id"]}]},
        {"_id": 0})
    if not d:
        raise HTTPException(404, "Template not found")
    if not _visible_to(user, d):
        raise HTTPException(403, "Not allowed to view this template")
    return d


@router.post("/definitions")
async def create_definition(body: DefinitionIn,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    if body.category not in ALLOWED_CATEGORIES:
        raise HTTPException(422, f"category must be one of {sorted(ALLOWED_CATEGORIES)}")
    existing = await db.template_definitions.find_one(
        {"code": body.code, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(409, "Template code already exists for this tenant")
    now = now_iso()
    doc = {
        "id": str(uuid.uuid4()),
        "code": body.code,
        "title": body.title,
        "category": body.category,
        "description": body.description or "",
        "is_system": False,
        "tenant_id": tenant["id"],
        "schema": [s.dict() for s in body.schema],
        "allowed_roles": body.allowed_roles,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    await db.template_definitions.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/definitions/{code}")
async def patch_definition(code: str, body: DefinitionPatch,
                            user: dict = Depends(_require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    d = await db.template_definitions.find_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": False},
        {"_id": 0})
    if not d:
        raise HTTPException(404, "Custom template not found (system templates cannot be edited)")
    upd: Dict[str, Any] = {"updated_at": now_iso(),
                             "version": (d.get("version") or 1) + 1}
    if body.title is not None: upd["title"] = body.title
    if body.description is not None: upd["description"] = body.description
    if body.schema is not None: upd["schema"] = [s.dict() for s in body.schema]
    if body.allowed_roles is not None: upd["allowed_roles"] = body.allowed_roles
    await db.template_definitions.update_one(
        {"code": code, "tenant_id": tenant["id"]}, {"$set": upd})
    fresh = await db.template_definitions.find_one(
        {"code": code, "tenant_id": tenant["id"]}, {"_id": 0})
    return fresh


@router.delete("/definitions/{code}")
async def delete_definition(code: str,
                             user: dict = Depends(_require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    sys = await db.template_definitions.find_one({"code": code, "is_system": True})
    if sys:
        raise HTTPException(403, "System templates cannot be deleted")
    r = await db.template_definitions.delete_one(
        {"code": code, "tenant_id": tenant["id"], "is_system": False})
    if not r.deleted_count:
        raise HTTPException(404, "Custom template not found")
    return {"deleted": code}


# ─── Instances ───────────────────────────────────────────────────────
class InstanceCreate(BaseModel):
    template_code: str
    title: Optional[str] = None
    values: Dict[str, Any] = Field(default_factory=dict)


class InstancePatch(BaseModel):
    title: Optional[str] = None
    values: Optional[Dict[str, Any]] = None


@router.get("/instances")
async def list_instances(
    template_code: Optional[str] = None,
    status: Optional[str] = None,
    mine: bool = False,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if template_code: q["template_code"] = template_code
    if status: q["status"] = status
    if mine: q["created_by"] = user["id"]
    rows = []
    async for r in db.template_instances.find(q, {"_id": 0}).sort("updated_at", -1):
        rows.append(r)
    return {"count": len(rows), "rows": rows}


@router.get("/instances/{iid}")
async def get_instance(iid: str,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Instance not found")
    return r


async def _load_def_for_tenant(code: str, tenant_id: str) -> dict:
    d = await db.template_definitions.find_one(
        {"code": code,
         "$or": [{"is_system": True}, {"tenant_id": tenant_id}]},
        {"_id": 0})
    if not d:
        raise HTTPException(404, f"Template definition '{code}' not found")
    return d


@router.post("/instances")
async def create_instance(body: InstanceCreate,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    defn = await _load_def_for_tenant(body.template_code, tenant["id"])
    if not _visible_to(user, defn):
        raise HTTPException(403, "Not allowed to fill this template")
    now = now_iso()
    title = body.title or f"{defn['title']} — {now[:10]}"
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "template_code": body.template_code,
        "template_version": defn.get("version", 1),
        "title": title,
        "values": body.values or {},
        "status": "draft",
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
        "finalized_at": None,
        "pdf_last_generated_at": None,
        "pdf_object_key": None,
    }
    await db.template_instances.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/instances/{iid}")
async def patch_instance(iid: str, body: InstancePatch,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    r = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Instance not found")
    if r.get("status") == "finalized":
        raise HTTPException(409, "Cannot edit a finalized instance")
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if body.title is not None: upd["title"] = body.title
    if body.values is not None: upd["values"] = body.values
    await db.template_instances.update_one({"id": iid}, {"$set": upd})
    return await db.template_instances.find_one({"id": iid}, {"_id": 0})


@router.post("/instances/{iid}/finalize")
async def finalize_instance(iid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    r = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Instance not found")
    if r.get("status") == "finalized":
        return r
    now = now_iso()
    await db.template_instances.update_one(
        {"id": iid},
        {"$set": {"status": "finalized", "finalized_at": now, "updated_at": now}})
    return await db.template_instances.find_one({"id": iid}, {"_id": 0})


@router.post("/instances/{iid}/duplicate")
async def duplicate_instance(iid: str,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    r = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Instance not found")
    now = now_iso()
    dup = {**r, "id": str(uuid.uuid4()),
             "title": (r.get("title") or "Untitled") + " (copy)",
             "status": "draft",
             "created_by": user["id"],
             "created_at": now, "updated_at": now,
             "finalized_at": None,
             "pdf_last_generated_at": None, "pdf_object_key": None}
    dup.pop("_id", None)
    await db.template_instances.insert_one(dup)
    dup.pop("_id", None)
    return dup


@router.delete("/instances/{iid}")
async def delete_instance(iid: str,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    r = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Instance not found")
    if user.get("role") not in ("admin", "super_admin") and r.get("created_by") != user["id"]:
        raise HTTPException(403, "Only owner or admin can delete")
    await db.template_instances.delete_one({"id": iid})
    return {"deleted": iid}


# ─── PDF export ──────────────────────────────────────────────────────
def _decode_signature_png(data_url: str) -> Optional[bytes]:
    """Return raw PNG bytes if `data_url` is a data-url PNG we can embed.

    Signatures may arrive as `data:image/png;base64,<...>` (from the web
    signature-pad modal) OR as a plain stamp with no image. We only
    decode the former; a decode failure returns None and the renderer
    falls back to the text stamp.
    """
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return None
    try:
        _, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64)
        # Guard: PNG magic bytes only. JPEGs / other formats fall through
        # to the text stamp to keep the surface tiny.
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return raw
    except Exception:
        return None


def _render_pdf(tenant: dict, defn: dict, inst: dict) -> bytes:
    r = _get_reportlab()
    # Image flowable isn't in the shared helper; import inline.
    from reportlab.platypus import Image as RLImage  # type: ignore
    buf = BytesIO()
    doc = r["SimpleDocTemplate"](buf, pagesize=r["letter"], title=inst.get("title") or defn["title"])
    story = []
    _tenant_header(story, r, tenant)
    story.append(r["Paragraph"](f"<b>{inst.get('title') or defn['title']}</b>", r["styles"]["Title"]))
    story.append(r["Paragraph"](
        f'<font color="#888888" size="9">{defn.get("category","").replace("_"," ")} · '
        f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</font>',
        r["styles"]["Normal"]))
    story.append(r["Spacer"](1, 10))
    values = inst.get("values") or {}
    for section in defn.get("schema") or []:
        story.append(r["Paragraph"](f"<b>{section.get('title','')}</b>", r["styles"]["Heading3"]))
        for f in section.get("fields") or []:
            ftype = f.get("type"); key = f.get("key"); label = f.get("label", key)
            val = values.get(key)
            if ftype == "header":
                story.append(r["Paragraph"](f"<i>{label}</i>", r["styles"]["Normal"]))
                continue
            if ftype == "signature":
                sig = val if isinstance(val, dict) else {}
                # New signer_name key (Phase 4) with legacy `name` fallback.
                signed_by = sig.get("signer_name") or sig.get("name") or "—"
                signed_at = sig.get("signed_at") or sig.get("date") or "—"
                png = _decode_signature_png(sig.get("image_data_url", ""))
                if png:
                    try:
                        img = RLImage(BytesIO(png), width=180, height=70, kind="proportional")
                        story.append(r["Paragraph"](f"<b>{label}:</b>", r["styles"]["Normal"]))
                        story.append(img)
                        story.append(r["Paragraph"](
                            f'<font color="#666666" size="9">Signed by {signed_by} on {signed_at}</font>',
                            r["styles"]["Normal"]))
                        story.append(r["Spacer"](1, 4))
                        continue
                    except Exception:
                        # Fall through to text stamp if image embed fails.
                        pass
                story.append(r["Paragraph"](
                    f"<b>{label}:</b> [Signed by {signed_by} on {signed_at}]",
                    r["styles"]["Normal"]))
                continue
            if ftype == "table" and isinstance(val, list) and val:
                cols = f.get("columns") or []
                col_keys = [c.get("key") for c in cols]
                col_labels = [c.get("label", c.get("key")) for c in cols]
                data = [col_labels] + [
                    [str(row.get(k, "")) for k in col_keys] for row in val
                ]
                tbl = r["Table"](data)
                tbl.setStyle(r["TableStyle"]([
                    ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                    ("BACKGROUND", (0, 0), (-1, 0), r["rlcolors"].HexColor("#F4F4F5")),
                    ("GRID", (0, 0), (-1, -1), 0.25, r["rlcolors"].HexColor("#E4E4E7")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.append(r["Paragraph"](f"<b>{label}</b>", r["styles"]["Normal"]))
                story.append(tbl)
                story.append(r["Spacer"](1, 6))
                continue
            display = "—" if val in (None, "", []) else (
                "✓" if val is True else "✗" if val is False else str(val))
            story.append(r["Paragraph"](
                f"<b>{label}:</b> {display}", r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 8))
    doc.build(story)
    return buf.getvalue()


@router.post("/instances/{iid}/pdf")
async def instance_pdf(iid: str,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    inst = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not inst:
        raise HTTPException(404, "Instance not found")
    defn = await _load_def_for_tenant(inst["template_code"], tenant["id"])
    pdf = _render_pdf(tenant, defn, inst)
    await db.template_instances.update_one(
        {"id": iid}, {"$set": {"pdf_last_generated_at": now_iso()}})
    fname = f"{inst['template_code']}-{iid[:8]}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


async def ensure_indexes():
    """Called once at startup — idempotent."""
    try:
        await db.template_definitions.create_index("code")
        await db.template_definitions.create_index([("tenant_id", 1), ("code", 1)])
        await db.template_instances.create_index([("tenant_id", 1), ("status", 1)])
        await db.template_instances.create_index([("tenant_id", 1), ("template_code", 1)])
        # Phase 4 · Batch A — share-to-portal provenance
        await db.documents.create_index(
            [("tenant_id", 1), ("source_type", 1), ("source_id", 1), ("customer_id", 1)])
    except Exception:
        pass


# ─── Phase 4 · Batch A — Share finalized instance to Customer Portal ─
class ShareToPortalIn(BaseModel):
    customer_id: str


@router.post("/instances/{iid}/share-to-portal")
async def share_to_portal(iid: str, body: ShareToPortalIn,
                           user: dict = Depends(_require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    """Push the finalized instance's PDF into the shared customer portal
    document store (`db.documents` — same collection that already backs
    `/api/portal/*/documents`).

    Rules:
      * Admin / super_admin only.
      * Instance must be finalized (409 otherwise).
      * Customer must belong to caller's tenant (404 otherwise).
      * Idempotent per `(tenant_id, source_type='template_instance',
        source_id=iid, customer_id)` — re-sharing overwrites the same
        portal doc and bumps its `version` int.
    """
    inst = await db.template_instances.find_one(
        {"id": iid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not inst:
        raise HTTPException(404, "Instance not found")
    if inst.get("status") != "finalized":
        raise HTTPException(409, "Only finalized instances can be shared to the customer portal")
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")

    defn = await _load_def_for_tenant(inst["template_code"], tenant["id"])
    pdf_bytes = _render_pdf(tenant, defn, inst)
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    data_url = f"data:application/pdf;base64,{b64}"

    doc_name = f"{inst.get('title') or defn['title']}.pdf"
    now = now_iso()

    existing = await db.documents.find_one(
        {"tenant_id": tenant["id"],
         "customer_id": body.customer_id,
         "source_type": "template_instance",
         "source_id": iid}, {"_id": 0})

    if existing:
        new_version = int(existing.get("version") or 1) + 1
        await db.documents.update_one(
            {"id": existing["id"]},
            {"$set": {
                "name": doc_name,
                "type": "template_pdf",
                "data": data_url,
                "uploaded_by": user.get("name") or user.get("email") or "Admin",
                "version": new_version,
                "updated_at": now,
            }})
        doc_id = existing["id"]
    else:
        doc_id = str(uuid.uuid4())
        await db.documents.insert_one({
            "id": doc_id,
            "tenant_id": tenant["id"],
            "customer_id": body.customer_id,
            "name": doc_name,
            "type": "template_pdf",
            "data": data_url,
            "uploaded_by": user.get("name") or user.get("email") or "Admin",
            "source_type": "template_instance",
            "source_id": iid,
            "template_code": inst["template_code"],
            "version": 1,
            "created_at": now,
            "updated_at": now,
        })

    # Best-effort customer notification. `notify_customer` no-ops if the
    # customer has no login / notification channel set up.
    try:
        await notify_customer(
            body.customer_id,
            "New document",
            f"'{doc_name}' was shared with you.")
    except Exception:
        pass

    return {
        "document_id": doc_id,
        "customer_id": body.customer_id,
        "shared_at": now,
        "portal_link": f"/portal/documents",
    }
