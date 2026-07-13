"""Chemicals catalog + AI-dosing recommendation (Phase 2).

The catalog piggybacks on the existing `items` collection (with `category='Chemical'`),
so nothing extra is needed on the data model side.  The dosing endpoint calls the
Emergent LLM (Claude Sonnet) with a strict system prompt that returns JSON only.

If EMERGENT_LLM_KEY is missing the endpoint returns HTTP 424 with a friendly message —
no stack trace, no crash.
"""
import json
import re
from fastapi import APIRouter, HTTPException, Depends

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin, get_current_user

router = APIRouter()


@router.get("/chemicals/catalog")
async def chemicals_catalog(user: dict = Depends(get_current_user)):
    """Every price-book item flagged as a chemical."""
    docs = await db.items.find(
        {"category": {"$regex": "^chemical$", "$options": "i"}}, {"_id": 0}
    ).sort("name", 1).to_list(500)
    return docs


@router.post("/chemicals/dosing-recommendation")
async def chemicals_dosing(body: dict, user: dict = Depends(get_current_user)):
    """AI-powered dosing recommendation.
    body: { volume_gal: float, readings: { fc, ph, ta, cya, salt? } }
    Returns { recommendations: [{chemical, amount_oz, reason}], warnings: [...] }.
    """
    volume = float(body.get("volume_gal") or 0)
    readings = body.get("readings") or {}
    if volume <= 0:
        raise HTTPException(400, "volume_gal must be > 0")

    if not EMERGENT_LLM_KEY:
        raise HTTPException(
            status_code=424,
            detail="AI dosing unavailable — EMERGENT_LLM_KEY not configured.",
        )

    # Lazy import — the library ships with the base image.
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    system = (
        "You are a certified pool chemistry assistant. Given a pool volume in "
        "gallons and current water readings, output ONLY valid JSON matching this "
        "TypeScript type:\n\n"
        "type Result = { recommendations: { chemical: string; amount_oz: number; "
        "reason: string }[]; warnings: string[] };\n\n"
        "Target ranges: FC 1-4 ppm, pH 7.4-7.6, TA 80-120 ppm, CYA 30-50 ppm. "
        "Only recommend commonly available residential chemicals (liquid chlorine 12.5%, "
        "muriatic acid 31.45%, sodium bicarb, cyanuric acid, calcium hypochlorite). "
        "For safety, cap any single dose at 32 oz. If a reading is missing, DO NOT "
        "guess — omit that chemical and add a warning. Return raw JSON only, no markdown."
    )

    prompt = (
        f"Pool volume: {volume:.0f} gallons.\n"
        f"Current readings: FC={readings.get('fc', 'unknown')} ppm, "
        f"pH={readings.get('ph', 'unknown')}, "
        f"TA={readings.get('ta', 'unknown')} ppm, "
        f"CYA={readings.get('cya', 'unknown')} ppm, "
        f"Salt={readings.get('salt', 'unknown')} ppm.\n"
        f"Return the JSON."
    )

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"dosing-{new_id()[:8]}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-5")
        raw = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.warning(f"Dosing LLM call failed: {e}")
        raise HTTPException(status_code=424, detail="AI dosing service unavailable right now.")

    # Extract the first JSON object from the response.
    text = raw if isinstance(raw, str) else str(raw)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise HTTPException(500, "AI returned an unparseable response")
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise HTTPException(500, "AI returned invalid JSON")

    # Persist audit trail (best effort).
    try:
        await db.dosing_logs.insert_one({
            "id": new_id(),
            "user_id": user.get("id"),
            "volume_gal": volume,
            "readings": readings,
            "result": parsed,
            "at": now_iso(),
        })
    except Exception:
        pass
    return parsed
