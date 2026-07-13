import base64
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

router = APIRouter()

RENDER_MODEL = "gemini-3.1-flash-image-preview"


def _strip_prefix(b64: str) -> str:
    return b64.split(",", 1)[1] if b64.startswith("data:") else b64


class RenderIn(BaseModel):
    image_base64: str          # raw base64 (no data: prefix) of the yard photo
    style: Optional[str] = ""
    elements: List[str] = []
    prompt: Optional[str] = ""
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None


def _build_prompt(style: str, elements: List[str], extra: str) -> str:
    parts = ["Transform this yard/property into a professional, photorealistic landscape design."]
    parts.append("Keep the existing house, buildings, fences and camera perspective exactly the same; only redesign the landscaping.")
    if style:
        parts.append(f"Design style: {style}.")
    if elements:
        parts.append("Add these features: " + ", ".join(elements) + ".")
    if extra and extra.strip():
        parts.append(extra.strip())
    parts.append("Ultra photorealistic, natural daylight, high detail, realistic plants and materials. Output only the edited image.")
    return " ".join(parts)


@router.post("/landscape/render")
async def render_landscape(body: RenderIn,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    img = _strip_prefix(body.image_base64 or "")
    if not img:
        raise HTTPException(400, "A yard photo is required")
    prompt = _build_prompt(body.style or "", body.elements or [], body.prompt or "")
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"landscape-{new_id()}",
                       system_message="You are an expert landscape designer that produces photorealistic yard redesigns.")
        chat.with_model("gemini", RENDER_MODEL).with_params(modalities=["image", "text"])
        msg = UserMessage(text=prompt, file_contents=[ImageContent(img)])
        text, images = await chat.send_message_multimodal_response(msg)
    except Exception as e:
        logger.error(f"landscape render failed: {e}")
        raise HTTPException(502, "Rendering failed. Please try again.")
    if not images:
        raise HTTPException(502, "No image was generated. Try a clearer photo or different options.")
    out = images[0]["data"]  # base64 string
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "created_by": user["id"], "created_by_name": user.get("name", ""),
        "customer_id": body.customer_id, "lead_id": body.lead_id,
        "style": body.style or "", "elements": body.elements or [], "prompt": body.prompt or "",
        "input_image": img, "output_image": out, "created_at": now_iso(),
    }
    await db.landscape_renders.insert_one(doc)
    # ── description + shopping list (best-effort, non-blocking on failure)
    description = ""
    shopping_list: list = []
    try:
        import json as _json, re as _re
        chat2 = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"landscape-desc-{doc['id'][:8]}",
                        system_message="You are a landscape designer that returns ONLY valid JSON, no prose fences.")
        desc_prompt = (
            f"For a Peoria AZ yard redesigned in '{body.style or 'Desert Contemporary'}' style "
            f"with features [{', '.join(body.elements or [])}], write:\n"
            "1) description: 2-3 sentence rationale for the design choices\n"
            "2) shopping_list: 6-10 items in the format [{item, category, estimated_cost}] "
            "covering plants, hardscape, and lighting.\n"
            'Return JSON exactly like {"description": "...", "shopping_list": [{"item":"", "category":"", "estimated_cost":0}]}.'
        )
        chat2.with_model("anthropic", "claude-sonnet-4-5")
        raw = await chat2.send_message(UserMessage(text=desc_prompt))
        text = (raw if isinstance(raw, str) else str(raw)).strip()
        if text.startswith("```"):
            text = _re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            parsed = _json.loads(text)
        except Exception:
            m = _re.search(r"\{.*\}", text, _re.S)
            parsed = _json.loads(m.group(0)) if m else {}
        description = (parsed.get("description") or "").strip()
        shopping_list = parsed.get("shopping_list") or []
        await db.landscape_renders.update_one(
            {"id": doc["id"], "tenant_id": tenant["id"]},
            {"$set": {"description": description, "shopping_list": shopping_list}},
        )
    except Exception as e:
        logger.warning(f"landscape description/list generation skipped: {e}")

    return {"id": doc["id"], "output_image": out, "description": description,
            "shopping_list": shopping_list, "created_at": doc["created_at"]}


@router.get("/landscape/renders")
async def list_renders(customer_id: Optional[str] = Query(None), lead_id: Optional[str] = Query(None),
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if lead_id:
        q["lead_id"] = lead_id
    docs = await db.landscape_renders.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return docs


@router.delete("/landscape/renders/{rid}")
async def delete_render(rid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    await db.landscape_renders.delete_one({"id": rid, "tenant_id": tenant["id"]})
    return {"ok": True}
