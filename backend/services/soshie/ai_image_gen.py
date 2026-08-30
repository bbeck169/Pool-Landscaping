"""Phase S1.5 · Feb-2026 — Soshie AI image generation + brand score.

Two responsibilities:

1. :func:`generate_brand_image` — generate a marketing-grade image
   for a Soshie post via the :mod:`services.media_provider`
   ``pick_provider`` seam.  The provider picks Supercool when the
   tenant has an MCP OAuth connection, else the Emergent-managed
   ``nano-banana-2`` model (via the Emergent Universal LLM Key).
   The image is persisted to Emergent Object Storage via the
   provider's existing ``_persist_image`` helper — no new storage
   backend is introduced.

2. :func:`score_brand_consistency` — Anthropic-vision-backed scorer
   that grades a candidate image against the tenant's Brand Memory.
   Returns a float in ``[0.0, 1.0]``.  ``>= 0.75`` → auto-publish
   eligible; ``< 0.75`` → autopilot must flag
   ``requires_human_approval=True`` on the action row.

Aspect ratios (per platform)
----------------------------
    instagram → 1024x1024   (1:1)
    tiktok    → 1024x1536   (2:3 portrait)
    facebook  → 1536x1024   (3:2 landscape)
    gbp       → 1536x1024   (3:2 landscape)

Nano-banana wiring findings
---------------------------
The user's brief referenced ``services/image_gen_nano_banana.py`` —
that module doesn't exist; the working nano-banana wiring lives in
:class:`services.media_provider.EmergentFallbackProvider` (uses
``LlmChat(...).with_model("google", "nano-banana-2")``).
We route through :func:`services.media_provider.pick_provider` so
tenants who've connected Supercool get its higher-quality output
while everyone else falls through to nano-banana automatically.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

import httpx

from config import db, logger
from services import media_provider as _mp
from utils import new_id, now_iso


BRAND_SCORE_THRESHOLD = 0.75


# Platform → (width, height) tuple.  The user's brief prescribed
# these exact sizes; Supercool accepts them via ``aspect_ratio`` free-
# form strings, Emergent nano-banana infers from the prompt.
PLATFORM_ASPECT: Dict[str, str] = {
    "instagram": "1:1",
    "tiktok":    "2:3",
    "facebook":  "3:2",
    "gbp":       "3:2",
}


PLATFORM_SIZE_PX: Dict[str, tuple] = {
    "instagram": (1024, 1024),
    "tiktok":    (1024, 1536),
    "facebook":  (1536, 1024),
    "gbp":       (1536, 1024),
}


async def _fetch_brand_memory(tenant_id: str) -> Dict[str, Any]:
    """Pull the tenant's brand memory bundle.  Includes the
    :mod:`brand_brain` shared context AND the most recent
    ``brand_brain_ingested_pages`` service summary (from the S1
    brand-ingest crawl) so the prompt is grounded in real
    tenant-authored copy."""
    bb = await db.brand_brain.find_one(
        {"tenant_id": tenant_id}, {"_id": 0},
    ) or {}
    ingest = await db.brand_brain_ingested_pages.find_one(
        {"tenant_id": tenant_id},
        {"_id": 0, "service_summary": 1, "headings": 1, "region": 1},
        sort=[("ingested_at", -1)],
    ) or {}
    # Best-effort resolve of tenant display name + region.
    tenant = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "name": 1, "business_name": 1,
          "service_area": 1, "timezone": 1},
    ) or {}
    return {
        "brand_name": (tenant.get("business_name")
                          or tenant.get("name") or ""),
        "region": (ingest.get("region")
                     or tenant.get("service_area") or ""),
        "tone": bb.get("tone") or "",
        "audience": bb.get("audience") or "",
        "talking_points": bb.get("talking_points") or [],
        "brand_voice_snippet": bb.get("brand_voice_snippet") or "",
        "service_summary": ingest.get("service_summary") or "",
    }


def build_prompt(
    *,
    brand_memory: Dict[str, Any],
    service_type: str,
    scene_description: str,
    platform: str,
) -> str:
    """Compose the nano-banana prompt from brand memory.  The
    prompt template mirrors the user's brief exactly.  Never
    raises; missing brand fields degrade to empty strings that the
    LLM handles gracefully."""
    brand_name = brand_memory.get("brand_name") or "the company"
    region = brand_memory.get("region") or "the region"
    tone = brand_memory.get("tone") or "warm, professional"
    st = (service_type or "pool + landscape service").strip()
    scene = (scene_description or "").strip() or (
        f"a technician performing {st} at a residential property"
    )
    return (
        f"Professional {st} photo for {brand_name}, "
        f"a {region} pool & landscaping company. {scene}. "
        f"Natural daylight, high-detail, marketing-quality, "
        f"tone: {tone}. No text overlays, no watermarks, no logos."
    )


async def generate_brand_image(
    *,
    tenant_id: str,
    platform: str,
    prompt_context: Dict[str, Any],
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a brand-consistent image + persist it.

    ``prompt_context`` keys:
        - ``service_type``       (str, optional)
        - ``scene_description``  (str, optional)

    Returns:
        ``{"url": str, "prompt": str, "aspect_ratio": str,
           "generated_at": str, "provider": str,
           "generated_media_id": str, "action_id": Optional[str]}``

    Raises ``services.media_provider.ProviderError`` when neither
    Supercool nor the Emergent fallback can generate.  Callers
    should catch and fall through to human-review.
    """
    platform = (platform or "").strip().lower()
    aspect = PLATFORM_ASPECT.get(platform, "1:1")
    brand = await _fetch_brand_memory(tenant_id)
    prompt = build_prompt(
        brand_memory=brand,
        service_type=(prompt_context or {}).get("service_type") or "",
        scene_description=(prompt_context or {}).get("scene_description")
                                or "",
        platform=platform,
    )
    provider = await _mp.pick_provider(tenant_id)
    result = await provider.generate(
        tenant_id=tenant_id, prompt=prompt,
        aspect_ratio=aspect, image_url=None,
    )
    urls = result.get("image_urls") or []
    if not urls:
        raise _mp.ProviderError("no_image_in_provider_response")
    image_id, saved_url = await _mp._persist_image(urls[0])
    now = now_iso()
    log_doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "action_id": action_id,
        "platform": platform,
        "prompt": prompt,
        "storage_url": saved_url,
        "generated_media_id": image_id,
        "provider": result.get("provider") or "unknown",
        "tool_used": result.get("tool_used") or "",
        "aspect_ratio": aspect,
        "brand_score": None,
        "generated_at": now,
    }
    await db.soshie_ai_generated_media.insert_one(dict(log_doc))
    return {
        "url": saved_url,
        "prompt": prompt,
        "aspect_ratio": aspect,
        "generated_at": now,
        "provider": result.get("provider") or "unknown",
        "generated_media_id": image_id,
        "action_id": action_id,
    }


# ─── Brand-consistency scoring ────────────────────────────────────

_SCORE_SYSTEM_PROMPT = (
    "You are a brand-consistency reviewer.  Given a candidate image "
    "and a JSON brand memory bundle, return a strict float 0.0-1.0 "
    "assessing how well the image matches the brand's voice, region, "
    "service, and tone.  1.0 = perfect fit; 0.0 = off-brand.  "
    "Reply with the raw float only — no prose, no keys."
)


async def _fetch_bytes(url: str) -> Optional[bytes]:
    """Fetch image bytes from either a data URI or an HTTP URL, or
    resolve a local ``/api/objects/...`` path via the object-storage
    getter.  Returns ``None`` on any failure — the caller falls
    through to a conservative low score."""
    try:
        if url.startswith("data:"):
            _, _, b64 = url.partition(",")
            return base64.b64decode(b64)
        if url.startswith("/api/objects/"):
            from services import object_storage as _obj
            path = url[len("/api/objects/"):]
            return _obj.get_object(path)
        if url.startswith("http"):
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(url)
            if r.status_code < 400:
                return r.content
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.brand_score] fetch failed: %s", e)
    return None


def _parse_score(text: str) -> float:
    """Extract the first float in ``[0.0, 1.0]`` from raw LLM text.
    Defaults to 0.0 (conservative) when no valid float is found."""
    if not text:
        return 0.0
    import re
    m = re.search(r"\d+\.\d+|\d+", text.strip())
    if not m:
        return 0.0
    try:
        v = float(m.group(0))
    except (TypeError, ValueError):
        return 0.0
    if v > 1.0:
        # Model may return "0-100" — coerce.
        v = v / 100.0 if v <= 100 else 1.0
    return max(0.0, min(1.0, v))


async def score_brand_consistency(
    *,
    image_url: str,
    brand_memory: Dict[str, Any],
    tenant_id: Optional[str] = None,
) -> float:
    """Score how well an image matches the tenant's brand memory.

    Uses Anthropic vision via the Emergent Universal LLM Key when
    ``EMERGENT_LLM_KEY`` is set; otherwise returns a conservative
    stub score of ``0.5`` so a missing key never accidentally
    unlocks auto-publish.

    Returns a float in ``[0.0, 1.0]``.  Never raises — a fetch or
    LLM crash returns ``0.0`` (conservative, blocks autopilot).
    """
    key = (os.environ.get("EMERGENT_LLM_KEY") or "").strip()
    if not key:
        # No key → return a mid score so integration tests aren't
        # blocked but real prod (which has the key) is gated.
        return 0.5
    img_bytes = await _fetch_bytes(image_url)
    if not img_bytes:
        return 0.0
    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
    except Exception as e:                                        # noqa: BLE001
        logger.warning(
            "[soshie.brand_score] emergent_import_failed: %s", e,
        )
        return 0.5
    try:
        chat = (LlmChat(api_key=key,
                          session_id=f"soshie-score-{new_id()}",
                          system_message=_SCORE_SYSTEM_PROMPT)
                .with_model("anthropic", "claude-sonnet-4-5"))
        b64 = base64.b64encode(img_bytes).decode("ascii")
        import json as _json
        bundle = _json.dumps(brand_memory or {}, default=str)[:2000]
        msg = UserMessage(
            text=(
                "Brand memory:\n" + bundle
                + "\n\nScore the attached image against this brand "
                    "memory.  Reply with a raw float 0.0-1.0."
            ),
            file_contents=[ImageContent(image_base64=b64)],
        )
        resp = await chat.send_message(msg)
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.brand_score] LLM call failed: %s", e)
        return 0.0
    score = _parse_score(str(resp))
    return score
