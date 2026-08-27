"""Feb-2026 · Phase B · Supercool image generation adapter.

Two providers with graceful fallback:

* ``SupercoolProvider`` — primary. Talks to Supercool via the Phase 26
  MCP OAuth client (``services.mcp_oauth_client.call_mcp_tool``). Uses
  the real Supercool tool schemas (introspected from ``mcp_tool_catalog``):

    - ``image_generate``  → text-to-image + image editing
    - ``image_search``    → Unsplash + Pexels stock lookup
    - ``remove_image_background`` → PhotoRoom passthrough

* ``EmergentFallbackProvider`` — fallback when Supercool is disconnected
  or the MCP call fails. Uses the Emergent-managed ``nano_banana`` /
  ``gpt-image-1`` route via the Emergent Universal LLM Key. Text-to-image
  only — search + remove-bg gracefully error.

The public ``pick_provider(tenant_id)`` helper returns whichever provider
should be used for that tenant right now. All Phase B endpoints route
through it so the frontend never has to know which backend served the
image.
"""
from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import logger
from services import mcp_oauth_client as _mcp


SUPERCOOL_URL = os.environ.get(
    "SUPERCOOL_MCP_URL", "https://mcp.supercool.com/mcp").rstrip("/")

UPLOAD_ROOT = Path("/app/backend/uploads/generated")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

HTTP_DOWNLOAD_TIMEOUT = 60.0


class ProviderError(RuntimeError):
    """Any provider-level failure. Router turns this into a 502 with the
    reason string attached."""


# ─────────────────────────────────────────────────────────────────────
# Result normalization
# ─────────────────────────────────────────────────────────────────────
def _normalize_supercool_image_result(raw: Dict[str, Any]) -> List[str]:
    """Supercool's ``image_generate`` returns a JSON-RPC result with a
    ``content`` array. Each entry is either ``{type:"text", text:"..."}``
    (metadata / rationale) or ``{type:"image", data:"<b64>", mimeType:"..."}``
    (the image bytes) or ``{type:"resource", resource:{uri, mimeType, ...}}``
    (a hosted URL). We pull out URLs first, then fall back to base64 data.
    Returns a list of URLs and/or ``data:`` URIs; empty when nothing usable.
    """
    urls: List[str] = []
    content = raw.get("content") or []
    if not isinstance(content, list):
        return urls
    for entry in content:
        if not isinstance(entry, dict):
            continue
        etype = entry.get("type")
        if etype == "resource":
            res = entry.get("resource") or {}
            uri = res.get("uri")
            if uri and (uri.startswith("http://") or uri.startswith("https://")):
                urls.append(uri)
        elif etype == "image":
            data = entry.get("data")
            mime = entry.get("mimeType") or "image/png"
            if data:
                urls.append(f"data:{mime};base64,{data}")
        elif etype == "text":
            # Sometimes Supercool embeds URLs in the text — try to extract.
            txt = entry.get("text") or ""
            for token in txt.split():
                if token.startswith("https://") and any(
                    token.lower().endswith(ext)
                    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    urls.append(token.strip('"),.'))
    return urls


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
async def _tenant_supercool_connected(tenant_id: str) -> bool:
    """Cheap check — does this tenant have a non-null access token in
    ``mcp_connections`` for the Supercool server URL?"""
    from config import db
    conn = await db.mcp_connections.find_one({
        "tenant_id": tenant_id,
        "server_url": SUPERCOOL_URL,
        "access_token_enc": {"$ne": None},
    }, {"_id": 0, "access_token_enc": 1})
    return bool(conn)


class SupercoolProvider:
    provider_name = "supercool"

    async def generate(self, *, tenant_id: str, prompt: str,
                          aspect_ratio: Optional[str] = None,
                          image_url: Optional[str] = None,
                          num_images: int = 1) -> Dict[str, Any]:
        args: Dict[str, Any] = {"prompt": prompt,
                                  "num_images": max(1, min(4, int(num_images))),
                                  "fresh": image_url is None}
        if aspect_ratio:
            args["aspect_ratio"] = aspect_ratio
        if image_url:
            args["image_url"] = image_url
            args["fresh"] = False
        try:
            raw = await _mcp.call_mcp_tool(
                tenant_id, SUPERCOOL_URL, "image_generate", args)
        except RuntimeError as e:
            raise ProviderError(f"supercool_call_failed: {e}")
        urls = _normalize_supercool_image_result(raw)
        if not urls:
            raise ProviderError("supercool_no_image_in_response")
        return {"provider": self.provider_name,
                 "tool_used": "image_generate",
                 "image_urls": urls, "raw": raw}

    async def search(self, *, tenant_id: str, query: str,
                        count: int = 6,
                        provider: str = "both") -> Dict[str, Any]:
        args = {"query": query,
                 "count": max(1, min(10, int(count))),
                 "provider": provider}
        try:
            raw = await _mcp.call_mcp_tool(
                tenant_id, SUPERCOOL_URL, "image_search", args)
        except RuntimeError as e:
            raise ProviderError(f"supercool_call_failed: {e}")
        results: List[Dict[str, Any]] = []
        content = raw.get("content") or []
        for entry in content:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "resource":
                res = entry.get("resource") or {}
                url = res.get("uri")
                if url:
                    results.append({
                        "url": url,
                        "thumb_url": res.get("thumbnail_url") or url,
                        "source": res.get("source") or "supercool",
                        "attribution": res.get("attribution") or "",
                    })
            elif entry.get("type") == "text":
                # Some deployments return a JSON blob as text.
                import json as _j
                try:
                    parsed = _j.loads(entry.get("text") or "{}")
                    for r in (parsed.get("results") or []):
                        results.append({
                            "url": r.get("url") or r.get("full_url"),
                            "thumb_url": r.get("thumb_url") or r.get("small_url") or r.get("url"),
                            "source": r.get("source") or "supercool",
                            "attribution": r.get("attribution") or r.get("photographer") or "",
                        })
                except Exception:
                    pass
        return {"provider": self.provider_name, "tool_used": "image_search",
                "results": [r for r in results if r.get("url")],
                "raw": raw}

    async def remove_background(self, *, tenant_id: str,
                                    source_image_url: str) -> Dict[str, Any]:
        # Supercool's ``remove_image_background`` requires a ``file_id``
        # from its own upload flow — no URL-based fallback is
        # available yet. Surface a clear error until we add an upload
        # bridge tool.
        raise ProviderError(
            "supercool_remove_bg_requires_file_id — this integration "
            "path is not enabled yet. Upload the image via the Content "
            "Studio (which generates a Supercool file_id) then retry.")


class EmergentFallbackProvider:
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
    """Return the Supercool provider when the tenant has a live
    connection, otherwise the Emergent fallback."""
    if await _tenant_supercool_connected(tenant_id):
        return SupercoolProvider()
    return EmergentFallbackProvider()
