"""Feb-2026 · Media generation adapter (post-K55.b).

Historical context — this module previously exposed two providers
(``SupercoolProvider`` primary, ``EmergentFallbackProvider`` fallback)
with a ``pick_provider(tenant_id)`` router selecting between them.

Feb-2026 · K55.b · sunset — the SuperCool integration was retired
(see ``/app/memory/PHASE_K55_b_BACKEND_REMOVAL.md``).  The
``SupercoolProvider`` class + ``_tenant_supercool_connected`` +
``_normalize_supercool_image_result`` helper + the SuperCool
env vars are gone.  ``pick_provider(tenant_id)`` now returns
``EmergentFallbackProvider()`` unconditionally.

The K56 diagnosis (see ``PHASE_K56_AI_MEDIA_GEN_MIGRATION_DIAGNOSIS.md``)
notes this is intentional: Emergent's ``nano-banana-2`` via the
Emergent Universal LLM Key is the sole live provider going forward.
Historical ``db.generated_media`` rows with ``provider="supercool"``
are preserved intact.
"""
from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import logger


UPLOAD_ROOT = Path("/app/backend/uploads/generated")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

HTTP_DOWNLOAD_TIMEOUT = 60.0


class ProviderError(RuntimeError):
    """Any provider-level failure. Router turns this into a 502 with the
    reason string attached."""


# ─────────────────────────────────────────────────────────────────────
# Result normalization
# ─────────────────────────────────────────────────────────────────────
# Feb-2026 · K55.b — ``_normalize_supercool_image_result`` deleted as
# part of the SuperCool sunset.  The Emergent fallback normalizes
# its own response inline in ``EmergentFallbackProvider.generate``
# below.


async def _persist_image(url_or_datauri: str) -> Tuple[str, str]:
    """Save an image (fetched from a URL or decoded from a data URI) into
    ``UPLOAD_ROOT`` and return ``(image_id, public_url)``. The public URL
    is a relative path under ``/uploads/generated/...`` — the frontend
    concatenates it with ``REACT_APP_BACKEND_URL`` when displaying."""
    image_id = uuid.uuid4().hex
    ext = "png"
    if url_or_datauri.startswith("data:"):
        header, _, b64 = url_or_datauri.partition(",")
        if "jpeg" in header: ext = "jpg"
        elif "webp" in header: ext = "webp"
        elif "gif" in header: ext = "gif"
        try:
            data = base64.b64decode(b64)
        except Exception as e:
            raise ProviderError(f"invalid_base64: {e}")
    else:
        for e in ("png", "jpg", "jpeg", "webp", "gif"):
            if url_or_datauri.lower().endswith("." + e):
                ext = "jpg" if e == "jpeg" else e
                break
        try:
            async with httpx.AsyncClient(timeout=HTTP_DOWNLOAD_TIMEOUT,
                                            follow_redirects=True) as c:
                r = await c.get(url_or_datauri)
        except Exception as e:
            raise ProviderError(f"download_failed: {e}")
        if r.status_code >= 400:
            raise ProviderError(
                f"download_http_error: HTTP {r.status_code}")
        data = r.content
    # Feb 2026 · Deployment fix — route ALL generated media through
    # Emergent Object Storage. The prior pod-local ``UPLOAD_ROOT``
    # write path was flagged as an ephemeral-storage deployment
    # blocker (pod-local files don't survive redeployment). Object
    # storage is initialised at server boot; if it isn't ready we
    # surface a clear ProviderError rather than silently writing to
    # an ephemeral pod path.
    filename = f"{image_id}.{ext}"
    try:
        from services import object_storage as _obj
    except Exception as _imp_exc:  # noqa: BLE001
        raise ProviderError(f"object_storage_import_failed: {_imp_exc}")
    if not _obj.is_ready():
        try:
            _obj.init_storage()
        except Exception:  # noqa: BLE001
            pass
    if not _obj.is_ready():
        raise ProviderError("object_storage_not_initialised")
    storage_path = _obj.build_path(
        tenant_id="global", entity_kind="generated",
        entity_id="media", filename=filename,
    )
    content_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
    try:
        _obj.put_object(storage_path, data, content_type)
    except Exception as _put_exc:  # noqa: BLE001
        raise ProviderError(f"object_storage_put_failed: {_put_exc}")
    # Feb 2026 · Object-Storage streaming — retrieval goes through
    # ``/api/objects/{path}`` (routers/objects.py) which resolves the
    # bytes via ``object_storage.get_object``. The prior ``/objects/*``
    # prefix without ``/api`` would be dropped by Kubernetes ingress
    # (only ``/api/*`` forwards to the backend).
    return image_id, f"/api/objects/{storage_path}"


# ─────────────────────────────────────────────────────────────────────
# Provider selection
# ─────────────────────────────────────────────────────────────────────
# Feb-2026 · K55.b — ``_tenant_supercool_connected`` +
# ``SupercoolProvider`` deleted as part of the SuperCool sunset.
# ``pick_provider(tenant_id)`` at the bottom of this module now
# returns ``EmergentFallbackProvider()`` unconditionally.


class EmergentFallbackProvider:
    # Feb-2026 · K55.b — this is now the SOLE image-gen provider.
    # ``provider_name`` retained for schema compat with historical
    # ``db.generated_media`` rows; a future K56 tweak may rename
    # it to ``"emergent"`` outright.
    provider_name = "emergent_fallback"

    async def generate(self, *, tenant_id: str, prompt: str,
                          aspect_ratio: Optional[str] = None,
                          image_url: Optional[str] = None,
                          num_images: int = 1) -> Dict[str, Any]:
        key = os.environ.get("EMERGENT_LLM_KEY", "").strip()
        if not key:
            raise ProviderError("emergent_key_missing")
        try:
            from emergentintegrations.llm.chat import (
                LlmChat, UserMessage, ImageContent, FileContent,
            )
        except Exception as e:
            raise ProviderError(f"emergent_import_failed: {e}")
        try:
            chat = (LlmChat(api_key=key,
                              session_id=f"phaseb-{uuid.uuid4().hex[:8]}",
                              system_message="You are an image generator.")
                    .with_model("google", "nano-banana-2"))
            file_contents = []
            if image_url:
                # Fetch the reference image and pass as base64.
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.get(image_url)
                if r.status_code < 400:
                    b64 = base64.b64encode(r.content).decode("ascii")
                    file_contents.append(ImageContent(image_base64=b64))
            msg = UserMessage(text=prompt,
                                file_contents=file_contents or None)
            resp = await chat.send_message(msg)
        except Exception as e:
            raise ProviderError(f"emergent_call_failed: {e}")
        # Emergent nano-banana returns a data URI in the string response.
        text = str(resp).strip()
        urls: List[str] = []
        if text.startswith("data:"):
            urls.append(text)
        elif text.startswith("http"):
            urls.append(text)
        else:
            # Sometimes it embeds the URL in a longer string.
            for tok in text.split():
                if tok.startswith("data:") or tok.startswith("http"):
                    urls.append(tok.strip('"),.'))
                    break
        if not urls:
            raise ProviderError("emergent_no_image_in_response")
        return {"provider": self.provider_name,
                 "tool_used": "nano-banana-2",
                 "image_urls": urls, "raw": {"text": text[:400]}}

    async def search(self, **_: Any) -> Dict[str, Any]:
        raise ProviderError("emergent_fallback_no_search_support")

    async def remove_background(self, **_: Any) -> Dict[str, Any]:
        raise ProviderError("emergent_fallback_no_remove_bg_support")


async def pick_provider(tenant_id: str):
    """Feb-2026 · K55.b — single-provider return.

    The pre-K55.b implementation had two providers (Supercool primary,
    Emergent fallback).  After the sunset, Emergent's ``nano-banana-2``
    is the sole live image-gen provider — see
    ``/app/memory/PHASE_K56_AI_MEDIA_GEN_MIGRATION_DIAGNOSIS.md``.
    The ``tenant_id`` argument is kept in the signature for
    consumer-compat (soshie/ai_image_gen, routers/media_gen call
    ``await pick_provider(tid)``); it is currently unused.
    """
    del tenant_id  # kept for signature stability
    return EmergentFallbackProvider()
