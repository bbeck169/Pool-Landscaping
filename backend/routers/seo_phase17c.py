"""Phase 17C · Agentic SEO Suite — Final Layer.

Ships the last three modules of the 9-module SEO suite:
 - 17C.1 · OTTO Auto-Fix   — concrete patches for audit issues (Claude live)
 - 17C.2 · Website Studio  — page builder with AI section auto-fill
 - 17C.3 · White-Label Reports — branded PDF/HTML with Claude exec summary

All admin/marketing-role endpoints go through `require_admin` — tech + customer
get 403. Public preview (`/api/preview/studio/{slug}`) is intentionally
auth-less so a published Studio page can be shared as a URL.

External integrations:
 - `EMERGENT_LLM_KEY` (Claude Sonnet 4.6) for OTTO patch generation, Studio
   auto-fill, and Reports exec summary.
 - Resend for report email delivery (falls back to
   `{sent:false, reason:'resend-not-configured'}` if key absent).
 - `reportlab` for PDF; HTML fallback if any reportlab call fails.
"""
import base64
import io
import json
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# 17C.1 · OTTO Auto-Fix
# ═══════════════════════════════════════════════════════════════════════

class OttoGenerateIn(BaseModel):
    audit_id: str
    max_fixes: int = Field(50, ge=1, le=200)


# Issue → patch_type mapping
_PATCH_TYPE = {
    "TITLE_MISSING": "title", "TITLE_TOO_SHORT": "title", "TITLE_TOO_LONG": "title",
    "META_MISSING": "meta", "META_TOO_SHORT": "meta", "META_TOO_LONG": "meta",
    "H1_MISSING": "h1", "H1_MULTIPLE": "h1",
    "CANONICAL_MISSING": "canonical",
    "ALT_LOW_COVERAGE": "alt",
    "JSONLD_MISSING": "schema",
    "BROKEN_INTERNAL": "broken_link", "BROKEN_EXTERNAL": "broken_link",
    "THIN_CONTENT": "content",
    "OG_MISSING": "og",
    "SITEMAP_MISSING": "sitemap",
}


async def _claude_patch(issue_code: str, page_url: str,
                          current_value: str, page_context: str) -> Dict[str, Any]:
    """Ask Claude for a concrete patch. Returns
    {suggested_value, patch_snippet, rationale, mocked:bool}."""
    if not EMERGENT_LLM_KEY:
        return {"suggested_value": "", "patch_snippet": "",
                "rationale": "LLM key not configured", "mocked": True}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        system = (
            "You are OTTO, an SEO auto-fix agent. Given a page and an issue "
            "code, produce a concrete replacement patch. Respond in STRICT "
            "JSON only: {\"suggested_value\":str,\"patch_snippet\":str,"
            "\"rationale\":str}. `patch_snippet` MUST be valid HTML the user "
            "can paste directly into the affected page."
        )
        prompt = (
            f"Issue code: {issue_code}\n"
            f"Page URL: {page_url}\n"
            f"Current value: {current_value or '(missing)'}\n"
            f"Page context (first 800 chars):\n{page_context[:800]}"
        )
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                        system_message=system)
                .with_model("anthropic", "claude-sonnet-4-6"))
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            data = json.loads(m.group(1)) if m else {"suggested_value": "",
                                                      "patch_snippet": text[:400],
                                                      "rationale": ""}
        return {"suggested_value": data.get("suggested_value") or "",
                "patch_snippet": data.get("patch_snippet") or "",
                "rationale": data.get("rationale") or "",
                "mocked": False}
    except Exception as e:
        logger.warning(f"OTTO Claude patch failed for {issue_code}: {e}")
        return {"suggested_value": "", "patch_snippet": "",
                "rationale": f"AI error: {e}", "mocked": False}


def _static_fallback_patch(issue_code: str, page_url: str,
                             current_value: str) -> Dict[str, str]:
    """Deterministic fallback used when the LLM is silent. Still meaningful."""
    if issue_code == "CANONICAL_MISSING":
        snip = f'<link rel="canonical" href="{page_url}" />'
        return {"suggested_value": page_url, "patch_snippet": snip,
                "rationale": "Add a self-referencing canonical tag."}
    if issue_code == "JSONLD_MISSING":
        obj = {"@context": "https://schema.org", "@type": "WebPage",
               "url": page_url}
        snip = f'<script type="application/ld+json">{json.dumps(obj)}</script>'
        return {"suggested_value": json.dumps(obj), "patch_snippet": snip,
                "rationale": "Add a minimal WebPage schema."}
    if issue_code == "OG_MISSING":
        snip = ('<meta property="og:title" content="Your title" />\n'
                '<meta property="og:description" content="Your description" />\n'
                f'<meta property="og:url" content="{page_url}" />')
        return {"suggested_value": "", "patch_snippet": snip,
                "rationale": "Add core Open Graph tags."}
    if issue_code == "SITEMAP_MISSING":
        return {"suggested_value": "/sitemap.xml",
                "patch_snippet": "Create /sitemap.xml at your web root.",
                "rationale": "Serve a valid XML sitemap at /sitemap.xml."}
    return {"suggested_value": "", "patch_snippet": "",
            "rationale": "No static template — will rely on AI output."}


@router.post("/seo/otto/generate-fixes")
async def otto_generate_fixes(body: OttoGenerateIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    audit = await db.seo_audits.find_one(
        {"id": body.audit_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not audit:
        raise HTTPException(404, "Audit not found")

    pages = await db.seo_audit_pages.find(
        {"audit_id": body.audit_id, "tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(500)

    fixes_created: List[Dict[str, Any]] = []
    any_mocked = False
    for page in pages:
        page_url = page.get("url", "")
        page_context = page.get("title", "") + "\n" + (page.get("meta") or "")
        for iss in page.get("issues", []):
            if len(fixes_created) >= body.max_fixes:
                break
            code = iss.get("code")
            if code not in _PATCH_TYPE:
                continue
            # Skip duplicates for same (page_url, code) that are still pending.
            dup = await db.seo_otto_fixes.find_one({
                "audit_id": body.audit_id, "tenant_id": tenant["id"],
                "page_url": page_url, "issue_code": code,
                "status": {"$in": ["pending", "applied"]},
            })
            if dup:
                continue

            current_value = ""
            if code.startswith("TITLE"):
                current_value = page.get("title") or ""
            elif code.startswith("META"):
                current_value = page.get("meta") or ""
            elif code.startswith("H1"):
                current_value = ""

            ai = await _claude_patch(code, page_url, current_value, page_context)
            if not ai.get("patch_snippet"):
                fb = _static_fallback_patch(code, page_url, current_value)
                if not ai.get("suggested_value"):
                    ai["suggested_value"] = fb["suggested_value"]
                ai["patch_snippet"] = fb["patch_snippet"]
                if not ai.get("rationale"):
                    ai["rationale"] = fb["rationale"]
            if ai.get("mocked"):
                any_mocked = True

            fix_doc = {
                "id": new_id(),
                "tenant_id": tenant["id"],
                "audit_id": body.audit_id,
                "page_url": page_url,
                "issue_code": code,
                "severity": iss.get("severity", "info"),
                "patch_type": _PATCH_TYPE[code],
                "current_value": current_value,
                "suggested_value": ai.get("suggested_value") or "",
                "patch_snippet": ai.get("patch_snippet") or "",
                "rationale": ai.get("rationale") or "",
                "status": "pending",
                "mocked": bool(ai.get("mocked")),
                "created_at": now_iso(),
                "applied_at": None,
                "dismissed_at": None,
            }
            await db.seo_otto_fixes.insert_one(dict(fix_doc))
            fix_doc.pop("_id", None)
            fixes_created.append(fix_doc)

    return {
        "audit_id": body.audit_id,
        "count": len(fixes_created),
        "mocked": bool(any_mocked and not fixes_created),
        "fixes": fixes_created,
    }


@router.get("/seo/otto/fixes/{audit_id}")
async def otto_list_fixes(audit_id: str, status: Optional[str] = None,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    audit = await db.seo_audits.find_one(
        {"id": audit_id, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    )
    if not audit:
        raise HTTPException(404, "Audit not found")
    q: Dict[str, Any] = {"audit_id": audit_id, "tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    rows = await db.seo_otto_fixes.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(500)
    totals = {"pending": 0, "applied": 0, "dismissed": 0}
    for r in rows:
        totals[r.get("status", "pending")] = totals.get(
            r.get("status", "pending"), 0) + 1
    return {"audit_id": audit_id, "fixes": rows, "totals": totals}


@router.post("/seo/otto/fixes/{fix_id}/mark-applied")
async def otto_mark_applied(fix_id: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    fix = await db.seo_otto_fixes.find_one(
        {"id": fix_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not fix:
        raise HTTPException(404, "Fix not found")
    await db.seo_otto_fixes.update_one(
        {"id": fix_id, "tenant_id": tenant["id"]},
        {"$set": {"status": "applied", "applied_at": now_iso()}},
    )
    return {"id": fix_id, "status": "applied"}


@router.post("/seo/otto/fixes/{fix_id}/dismiss")
async def otto_dismiss(fix_id: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    fix = await db.seo_otto_fixes.find_one(
        {"id": fix_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not fix:
        raise HTTPException(404, "Fix not found")
    await db.seo_otto_fixes.update_one(
        {"id": fix_id, "tenant_id": tenant["id"]},
        {"$set": {"status": "dismissed", "dismissed_at": now_iso()}},
    )
    return {"id": fix_id, "status": "dismissed"}


@router.get("/seo/otto/fixes/{fix_id}/patch-file")
async def otto_patch_file(fix_id: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    fix = await db.seo_otto_fixes.find_one(
        {"id": fix_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not fix:
        raise HTTPException(404, "Fix not found")
    content = (
        f"<!-- OTTO Auto-Fix · {fix['issue_code']} -->\n"
        f"<!-- Page: {fix['page_url']} -->\n"
        f"<!-- Rationale: {fix.get('rationale', '')} -->\n\n"
        f"{fix.get('patch_snippet', '')}\n"
    )
    fname = f"otto-{fix['issue_code'].lower()}-{fix_id[:8]}.html"
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ═══════════════════════════════════════════════════════════════════════
# 17C.2 · Website Studio
# ═══════════════════════════════════════════════════════════════════════

_ALLOWED_SECTION_TYPES = {
    "hero", "features", "benefits", "services", "testimonials",
    "faq", "cta", "local_business_schema",
}


class StudioSection(BaseModel):
    type: str
    heading: Optional[str] = ""
    subheading: Optional[str] = ""
    body: Optional[str] = ""
    items: Optional[List[Dict[str, Any]]] = None
    data: Optional[Dict[str, Any]] = None


class StudioPageIn(BaseModel):
    title: str
    slug: str = Field(..., min_length=1, max_length=120)
    target_keyword: Optional[str] = ""
    meta_description: Optional[str] = ""
    business_context: Optional[str] = ""
    sections: List[StudioSection] = []


class StudioPagePatch(BaseModel):
    title: Optional[str] = None
    target_keyword: Optional[str] = None
    meta_description: Optional[str] = None
    business_context: Optional[str] = None
    sections: Optional[List[StudioSection]] = None


class StudioAutoFillIn(BaseModel):
    business_context: str
    target_keyword: str
    section_types: Optional[List[str]] = None


def _slug_ok(slug: str) -> bool:
    return bool(re.match(r"^[a-z0-9][a-z0-9\-]{0,118}[a-z0-9]$", slug or ""))


def _validate_sections(sections: List[Dict[str, Any]]) -> None:
    for s in sections:
        t = (s or {}).get("type")
        if t not in _ALLOWED_SECTION_TYPES:
            raise HTTPException(400, f"Invalid section type: {t}")


@router.post("/seo/studio/pages")
async def studio_create_page(body: StudioPageIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    if not _slug_ok(body.slug):
        raise HTTPException(400,
            "Slug must be lowercase, digits, and hyphens (2-120 chars).")
    # Uniqueness per tenant
    dup = await db.seo_studio_pages.find_one(
        {"tenant_id": tenant["id"], "slug": body.slug}, {"_id": 0, "id": 1}
    )
    if dup:
        raise HTTPException(409, "Slug already exists in this tenant.")
    sections = [s.model_dump() for s in body.sections]
    _validate_sections(sections)
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "title": body.title,
        "slug": body.slug,
        "target_keyword": body.target_keyword or "",
        "meta_description": body.meta_description or "",
        "business_context": body.business_context or "",
        "sections": sections,
        "status": "draft",
        "published_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.seo_studio_pages.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/seo/studio/pages")
async def studio_list_pages(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    rows = await db.seo_studio_pages.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "title": 1, "slug": 1, "status": 1,
         "target_keyword": 1, "published_at": 1, "updated_at": 1,
         "created_at": 1},
    ).sort("updated_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.get("/seo/studio/pages/{pid}")
async def studio_get_page(pid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    p = await db.seo_studio_pages.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not p:
        raise HTTPException(404, "Page not found")
    return p


@router.put("/seo/studio/pages/{pid}")
async def studio_update_page(pid: str, body: StudioPagePatch,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    p = await db.seo_studio_pages.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    )
    if not p:
        raise HTTPException(404, "Page not found")
    updates: Dict[str, Any] = {"updated_at": now_iso()}
    if body.title is not None:
        updates["title"] = body.title
    if body.target_keyword is not None:
        updates["target_keyword"] = body.target_keyword
    if body.meta_description is not None:
        updates["meta_description"] = body.meta_description
    if body.business_context is not None:
        updates["business_context"] = body.business_context
    if body.sections is not None:
        sections = [s.model_dump() for s in body.sections]
        _validate_sections(sections)
        updates["sections"] = sections
    await db.seo_studio_pages.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": updates}
    )
    return await db.seo_studio_pages.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


_STUDIO_AUTOFILL_SYSTEM = (
    "You are a landing-page copy generator. Given a business context and "
    "a target keyword, return STRICT JSON with a `sections` array. Each "
    "section object must have `type` (one of hero, features, benefits, "
    "services, testimonials, faq, cta, local_business_schema), plus "
    "`heading`, `subheading`, `body`, and where applicable an `items` array "
    "of {title, description} (or {question, answer} for faq, or "
    "{quote, author} for testimonials). Return between 5 and 8 sections. "
    "No prose outside the JSON."
)


@router.post("/seo/studio/pages/{pid}/auto-fill")
async def studio_auto_fill(pid: str, body: StudioAutoFillIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    p = await db.seo_studio_pages.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not p:
        raise HTTPException(404, "Page not found")
    if not EMERGENT_LLM_KEY:
        return {"sections": [], "mocked": True,
                "reason": "LLM key not configured"}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                        system_message=_STUDIO_AUTOFILL_SYSTEM)
                .with_model("anthropic", "claude-sonnet-4-6"))
        want_types = body.section_types or list(_ALLOWED_SECTION_TYPES)
        prompt = (
            f"Business context: {body.business_context}\n"
            f"Target keyword: {body.target_keyword}\n"
            f"Preferred section types (subset ok): {', '.join(want_types)}"
        )
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            data = json.loads(m.group(1)) if m else {"sections": []}
        sections = data.get("sections") or []
        # Filter out any invalid section types silently.
        sections = [s for s in sections
                     if (s or {}).get("type") in _ALLOWED_SECTION_TYPES]
        await db.seo_studio_pages.update_one(
            {"id": pid, "tenant_id": tenant["id"]},
            {"$set": {"sections": sections, "updated_at": now_iso(),
                       "target_keyword": body.target_keyword,
                       "business_context": body.business_context}},
        )
        return {"sections": sections, "count": len(sections),
                "mocked": False}
    except Exception as e:
        logger.warning(f"Studio auto-fill failed: {e}")
        return {"sections": [], "mocked": False, "error": str(e)}


@router.post("/seo/studio/pages/{pid}/publish")
async def studio_publish_page(pid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    p = await db.seo_studio_pages.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not p:
        raise HTTPException(404, "Page not found")
    published_at = now_iso()
    await db.seo_studio_pages.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "published",
                    "published_at": published_at,
                    "updated_at": published_at}},
    )
    return {"id": pid, "status": "published",
             "published_at": published_at,
             "slug": p["slug"],
             "preview_url": f"/api/preview/studio/{p['slug']}"}


def _render_section_html(s: Dict[str, Any]) -> str:
    t = s.get("type", "")
    heading = s.get("heading") or ""
    subheading = s.get("subheading") or ""
    body_ = s.get("body") or ""
    items = s.get("items") or []
    if t == "hero":
        return (f'<section class="section hero"><h1>{heading}</h1>'
                f'<p class="lead">{subheading}</p><div>{body_}</div></section>')
    if t == "features":
        it = "".join(
            f'<li><strong>{i.get("title","")}</strong>: {i.get("description","")}</li>'
            for i in items)
        return (f'<section class="section features"><h2>{heading}</h2>'
                f'<p>{subheading}</p><ul>{it}</ul></section>')
    if t == "benefits":
        it = "".join(
            f'<li><strong>{i.get("title","")}</strong>: {i.get("description","")}</li>'
            for i in items)
        return (f'<section class="section benefits"><h2>{heading}</h2>'
                f'<p>{subheading}</p><ul>{it}</ul></section>')
    if t == "services":
        it = "".join(
            f'<div class="svc-card"><h3>{i.get("title","")}</h3>'
            f'<p>{i.get("description","")}</p></div>' for i in items)
        return (f'<section class="section services"><h2>{heading}</h2>'
                f'<p>{subheading}</p><div class="grid">{it}</div></section>')
    if t == "testimonials":
        it = "".join(
            f'<blockquote>“{i.get("quote","")}” '
            f'<cite>— {i.get("author","")}</cite></blockquote>' for i in items)
        return (f'<section class="section testimonials"><h2>{heading}</h2>'
                f'{it}</section>')
    if t == "faq":
        it = "".join(
            f'<details><summary>{i.get("question","")}</summary>'
            f'<p>{i.get("answer","")}</p></details>' for i in items)
        return (f'<section class="section faq"><h2>{heading}</h2>{it}</section>')
    if t == "cta":
        return (f'<section class="section cta"><h2>{heading}</h2>'
                f'<p>{subheading}</p><a class="cta-btn" href="#contact">'
                f'{body_ or "Get in touch"}</a></section>')
    if t == "local_business_schema":
        data = s.get("data") or {}
        obj = {"@context": "https://schema.org", "@type": "LocalBusiness",
               **data}
        return f'<script type="application/ld+json">{json.dumps(obj)}</script>'
    return f'<section class="section"><h2>{heading}</h2><p>{body_}</p></section>'


def _render_full_html(page: Dict[str, Any]) -> str:
    title = page.get("title") or "Untitled"
    meta = page.get("meta_description") or ""
    kw = page.get("target_keyword") or ""
    body_parts = [_render_section_html(s) for s in page.get("sections", [])]
    css = (
        "*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"
        "BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;color:#0F172A;"
        "background:#FFFFFF;line-height:1.55}"
        ".section{max-width:1100px;margin:0 auto;padding:56px 24px;"
        "border-bottom:1px solid #F1F5F9}"
        ".hero{background:linear-gradient(135deg,#0284C7 0%,#16A34A 100%);"
        "color:#fff}"
        ".hero h1{font-size:44px;margin:0 0 12px}"
        ".hero .lead{font-size:18px;opacity:.9;margin:0 0 20px}"
        ".section h2{font-size:32px;margin:0 0 8px}"
        ".section p{color:#334155}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}"
        ".svc-card{padding:20px;border:1px solid #E2E8F0;border-radius:14px}"
        "blockquote{margin:16px 0;padding:12px 16px;border-left:4px solid #0284C7;background:#F0F9FF}"
        ".cta{text-align:center;background:#0F172A;color:#fff}"
        ".cta h2{color:#fff}"
        ".cta p{color:#CBD5E1}"
        ".cta-btn{display:inline-block;background:#0284C7;color:#fff;"
        "padding:14px 28px;border-radius:9999px;text-decoration:none;font-weight:700}"
        "details{padding:10px 0;border-bottom:1px dashed #E2E8F0}"
        "details summary{font-weight:600;cursor:pointer}"
        "ul li{margin:8px 0}"
    )
    return (
        f'<!doctype html><html lang="en"><head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        f'<meta name="description" content="{meta}">'
        f'<meta name="keywords" content="{kw}">'
        f'<style>{css}</style>'
        f'</head><body>{"".join(body_parts)}</body></html>'
    )


def _render_markdown(page: Dict[str, Any]) -> str:
    out = [f"# {page.get('title', '')}",
           f"_{page.get('meta_description', '')}_",
           ""]
    for s in page.get("sections", []):
        t = s.get("type")
        if s.get("heading"): out.append(f"## {s['heading']}")
        if s.get("subheading"): out.append(f"_{s['subheading']}_")
        if s.get("body"): out.append(s["body"])
        for i in (s.get("items") or []):
            if t == "faq":
                out.append(f"- **{i.get('question','')}** — {i.get('answer','')}")
            elif t == "testimonials":
                out.append(f"> {i.get('quote','')} — *{i.get('author','')}*")
            else:
                out.append(f"- **{i.get('title','')}** — {i.get('description','')}")
        out.append("")
    return "\n".join(out)


@router.get("/seo/studio/pages/{pid}/export")
async def studio_export_page(pid: str,
                                format: str = Query("html"),
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    p = await db.seo_studio_pages.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not p:
        raise HTTPException(404, "Page not found")
    fmt = (format or "html").lower()
    if fmt not in {"html", "markdown", "json"}:
        raise HTTPException(400, "format must be html|markdown|json")
    if fmt == "html":
        content = _render_full_html(p).encode("utf-8")
        ct = "text/html; charset=utf-8"
        ext = "html"
    elif fmt == "markdown":
        content = _render_markdown(p).encode("utf-8")
        ct = "text/markdown; charset=utf-8"
        ext = "md"
    else:
        content = json.dumps(p, indent=2).encode("utf-8")
        ct = "application/json"
        ext = "json"
    fname = f"studio-{p.get('slug', pid[:8])}.{ext}"
    return StreamingResponse(
        io.BytesIO(content), media_type=ct,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/preview/studio/{slug}")
async def studio_public_preview(slug: str):
    """Public no-auth preview of a *published* Studio page.
    Returns 404 if the slug doesn't exist, or 403 if it exists but is a draft.
    """
    p = await db.seo_studio_pages.find_one(
        {"slug": slug}, {"_id": 0}
    )
    if not p:
        raise HTTPException(404, "Page not found")
    if p.get("status") != "published":
        raise HTTPException(403, "Page is not yet published")
    return HTMLResponse(_render_full_html(p))


# ═══════════════════════════════════════════════════════════════════════
# 17C.3 · White-Label Reports
# ═══════════════════════════════════════════════════════════════════════

class ReportIn(BaseModel):
    title: str
    brand_name: Optional[str] = ""
    brand_color: Optional[str] = "#0284C7"
    logo_url: Optional[str] = ""
    audit_id: Optional[str] = None
    heatmap_id: Optional[str] = None
    topical_map_id: Optional[str] = None
    include_llm_visibility: bool = True
    range_days: int = Field(30, ge=1, le=365)
    notes: Optional[str] = ""


class ReportSendIn(BaseModel):
    to: str
    subject: Optional[str] = ""
    message: Optional[str] = ""


async def _collect_report_data(tenant_id: str,
                                 body: ReportIn) -> Dict[str, Any]:
    data: Dict[str, Any] = {"audit": None, "heatmap": None,
                             "topical_map": None, "llm_visibility": None}
    if body.audit_id:
        data["audit"] = await db.seo_audits.find_one(
            {"id": body.audit_id, "tenant_id": tenant_id}, {"_id": 0}
        )
    if body.heatmap_id:
        data["heatmap"] = await db.seo_rank_heatmaps.find_one(
            {"id": body.heatmap_id, "tenant_id": tenant_id}, {"_id": 0}
        )
    if body.topical_map_id:
        data["topical_map"] = await db.seo_topical_maps.find_one(
            {"id": body.topical_map_id, "tenant_id": tenant_id}, {"_id": 0}
        )
    if body.include_llm_visibility:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc)
                    - timedelta(days=body.range_days)).isoformat()
        scans = await db.seo_llm_scans.find(
            {"tenant_id": tenant_id, "scanned_at": {"$gte": cutoff}},
            {"_id": 0}
        ).to_list(2000)
        total = len(scans)
        mentioned = sum(1 for s in scans if s.get("brand_mentioned"))
        data["llm_visibility"] = {
            "total_scans": total,
            "mention_rate_pct": round(100 * mentioned / max(1, total), 1),
            "scans_preview": scans[:5],
        }
    return data


async def _claude_exec_summary(brand: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not EMERGENT_LLM_KEY:
        return {"summary": "", "mocked": True}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        summary_bits = []
        a = data.get("audit") or {}
        if a:
            s = a.get("summary") or {}
            summary_bits.append(
                f"Site audit for {a.get('url','')}: overall score "
                f"{(s.get('scores') or {}).get('overall','?')}/100, "
                f"{s.get('pages_crawled','?')} pages, "
                f"{s.get('issues_total','?')} issues.")
        h = data.get("heatmap") or {}
        if h:
            summary_bits.append(
                f"Rank heatmap for '{h.get('keyword','')}': avg rank "
                f"{h.get('avg_rank','?')}.")
        tm = data.get("topical_map") or {}
        if tm:
            nodes = (tm.get("tree") or {}).get("nodes") or []
            summary_bits.append(
                f"Topical map seed '{tm.get('seed_keyword','')}': "
                f"{len(nodes)} nodes.")
        lv = data.get("llm_visibility") or {}
        if lv:
            summary_bits.append(
                f"LLM Visibility: mention rate "
                f"{lv.get('mention_rate_pct',0)}% over {lv.get('total_scans',0)} scans.")
        system = (
            "You are a senior SEO strategist writing a client-ready executive "
            "summary. Return STRICT JSON: {\"summary\":str,\"key_wins\":[str],"
            "\"top_opportunities\":[str]}. Summary is 3-5 sentences, "
            "professional tone."
        )
        prompt = (f"Brand: {brand}\n"
                    f"Data points:\n- " + "\n- ".join(summary_bits))
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                        system_message=system)
                .with_model("anthropic", "claude-sonnet-4-6"))
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            parsed = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            parsed = json.loads(m.group(1)) if m else {"summary": text[:600]}
        return {
            "summary": parsed.get("summary") or "",
            "key_wins": parsed.get("key_wins") or [],
            "top_opportunities": parsed.get("top_opportunities") or [],
            "mocked": False,
        }
    except Exception as e:
        logger.warning(f"Report exec summary failed: {e}")
        return {"summary": "", "mocked": False, "error": str(e)}


def _report_html(report: Dict[str, Any]) -> str:
    brand = report.get("brand_name") or "Your Brand"
    color = report.get("brand_color") or "#0284C7"
    logo = report.get("logo_url") or ""
    title = report.get("title") or "SEO Report"
    exec_ = report.get("exec_summary") or {}
    data = report.get("data") or {}
    audit = data.get("audit") or {}
    heatmap = data.get("heatmap") or {}
    tmap = data.get("topical_map") or {}
    lv = data.get("llm_visibility") or {}

    audit_scores = ((audit.get("summary") or {}).get("scores") or {})
    audit_block = ""
    if audit:
        audit_block = (
            f'<h2>Site Audit — {audit.get("url","")}</h2>'
            f'<div class="scores">'
            f'<div class="score"><b>{audit_scores.get("overall","—")}</b>Overall</div>'
            f'<div class="score"><b>{audit_scores.get("technical","—")}</b>Technical</div>'
            f'<div class="score"><b>{audit_scores.get("on_page","—")}</b>On-page</div>'
            f'<div class="score"><b>{audit_scores.get("ux","—")}</b>UX</div>'
            f'</div>'
            f'<p>Pages crawled: {(audit.get("summary") or {}).get("pages_crawled","—")} · '
            f'Issues: {(audit.get("summary") or {}).get("issues_total","—")}</p>'
        )
    heatmap_block = ""
    if heatmap:
        heatmap_block = (
            f'<h2>Rank Heatmap · "{heatmap.get("keyword","")}"</h2>'
            f'<p>Average rank: <b>{heatmap.get("avg_rank","—")}</b> · '
            f'Top-3 grid cells: <b>{heatmap.get("top_position_count",0)}</b></p>'
        )
    tmap_block = ""
    if tmap:
        nodes = (tmap.get("tree") or {}).get("nodes") or []
        top_titles = [n.get("title","") for n in nodes[:8]]
        tmap_block = (
            f'<h2>Topical Opportunities · seed "{tmap.get("seed_keyword","")}"</h2>'
            f'<p>{len(nodes)} nodes generated.</p>'
            f'<ul>' + "".join(f"<li>{t}</li>" for t in top_titles) + '</ul>'
        )
    lv_block = ""
    if lv:
        lv_block = (
            f'<h2>LLM Visibility</h2>'
            f'<p>Mention rate: <b>{lv.get("mention_rate_pct",0)}%</b> '
            f'across <b>{lv.get("total_scans",0)}</b> scans.</p>'
        )
    exec_block = ""
    if exec_.get("summary"):
        wins = exec_.get("key_wins") or []
        opps = exec_.get("top_opportunities") or []
        exec_block = (
            f'<h2>Executive Summary</h2>'
            f'<p>{exec_.get("summary","")}</p>'
            + (f'<h3>Key Wins</h3><ul>' + "".join(f"<li>{w}</li>" for w in wins)
                + '</ul>' if wins else "")
            + (f'<h3>Top Opportunities</h3><ul>'
                + "".join(f"<li>{o}</li>" for o in opps) + '</ul>' if opps else "")
        )
    css = (
        "body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;"
        "color:#0F172A;margin:0;padding:32px;background:#F8FAFC}"
        f".hdr{{background:{color};color:#fff;padding:32px;border-radius:16px;"
        "margin-bottom:24px;display:flex;align-items:center;gap:16px}}"
        ".hdr img{height:48px;border-radius:8px;background:#fff;padding:6px}"
        ".hdr h1{margin:0;font-size:28px}"
        ".hdr .brand{font-size:13px;opacity:.9;margin-top:6px}"
        ".card{background:#fff;padding:24px;margin-bottom:16px;"
        "border-radius:12px;border:1px solid #E2E8F0}"
        "h2{margin-top:0;font-size:22px}"
        f"h2{{color:{color}}}"
        ".scores{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}"
        ".score{background:#F1F5F9;padding:16px;border-radius:8px;text-align:center;"
        "font-size:12px;color:#475569}"
        ".score b{display:block;font-size:26px;color:#0F172A;margin-bottom:4px}"
        "ul{padding-left:20px}li{margin:4px 0}"
        ".foot{margin-top:32px;color:#94A3B8;font-size:11px;text-align:center}"
    )
    logo_html = (f'<img src="{logo}" alt="{brand} logo">' if logo else "")
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{title}</title><style>{css}</style></head><body>'
        f'<div class="hdr">{logo_html}<div>'
        f'<h1>{title}</h1><div class="brand">{brand}</div></div></div>'
        + (f'<div class="card">{exec_block}</div>' if exec_block else "")
        + (f'<div class="card">{audit_block}</div>' if audit_block else "")
        + (f'<div class="card">{heatmap_block}</div>' if heatmap_block else "")
        + (f'<div class="card">{tmap_block}</div>' if tmap_block else "")
        + (f'<div class="card">{lv_block}</div>' if lv_block else "")
        + f'<div class="foot">Report generated {report.get("created_at","")}'
        f' · Powered by {brand}</div>'
        f'</body></html>'
    )


def _report_pdf_bytes(report: Dict[str, Any]) -> Optional[bytes]:
    """Return PDF bytes via reportlab, or None if generation fails."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors as rlc
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                          Table, TableStyle)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter,
                                  leftMargin=0.6*inch, rightMargin=0.6*inch,
                                  topMargin=0.6*inch, bottomMargin=0.6*inch)
        styles = getSampleStyleSheet()
        brand = report.get("brand_name") or "Your Brand"
        color_hex = (report.get("brand_color") or "#0284C7").lstrip("#")
        try:
            brand_color = rlc.HexColor("#" + color_hex)
        except Exception:
            brand_color = rlc.HexColor("#0284C7")
        title_style = ParagraphStyle("t", parent=styles["Title"],
                                      fontSize=22, textColor=brand_color)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"],
                             textColor=brand_color, spaceAfter=6)
        body_style = styles["BodyText"]

        flow = []
        flow.append(Paragraph(report.get("title") or "SEO Report", title_style))
        flow.append(Paragraph(brand, styles["Italic"]))
        flow.append(Spacer(1, 12))

        exec_ = report.get("exec_summary") or {}
        if exec_.get("summary"):
            flow.append(Paragraph("Executive Summary", h2))
            flow.append(Paragraph(exec_["summary"], body_style))
            if exec_.get("key_wins"):
                flow.append(Paragraph("Key Wins:", body_style))
                for w in exec_["key_wins"]:
                    flow.append(Paragraph(f"• {w}", body_style))
            if exec_.get("top_opportunities"):
                flow.append(Paragraph("Top Opportunities:", body_style))
                for o in exec_["top_opportunities"]:
                    flow.append(Paragraph(f"• {o}", body_style))
            flow.append(Spacer(1, 12))

        data = report.get("data") or {}
        audit = data.get("audit") or {}
        if audit:
            sc = (audit.get("summary") or {}).get("scores") or {}
            flow.append(Paragraph(
                f"Site Audit — {audit.get('url','')}", h2))
            tbl = Table([
                ["Overall", "Technical", "On-Page", "UX"],
                [str(sc.get("overall","—")), str(sc.get("technical","—")),
                    str(sc.get("on_page","—")), str(sc.get("ux","—"))],
            ], hAlign="LEFT", colWidths=[1.4*inch]*4)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), brand_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), rlc.white),
                ("BOX", (0, 0), (-1, -1), 0.5, rlc.grey),
                ("GRID", (0, 0), (-1, -1), 0.25, rlc.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            flow.append(tbl)
            flow.append(Spacer(1, 8))
            sm = audit.get("summary") or {}
            flow.append(Paragraph(
                f"Pages crawled: {sm.get('pages_crawled','—')}    "
                f"Issues: {sm.get('issues_total','—')}", body_style))
            flow.append(Spacer(1, 12))

        heatmap = data.get("heatmap") or {}
        if heatmap:
            flow.append(Paragraph(
                f"Rank Heatmap — \"{heatmap.get('keyword','')}\"", h2))
            flow.append(Paragraph(
                f"Average rank: <b>{heatmap.get('avg_rank','—')}</b> · "
                f"Top-3 cells: <b>{heatmap.get('top_position_count',0)}</b>",
                body_style))
            flow.append(Spacer(1, 12))

        tmap = data.get("topical_map") or {}
        if tmap:
            nodes = (tmap.get("tree") or {}).get("nodes") or []
            flow.append(Paragraph(
                f"Topical Opportunities — seed \"{tmap.get('seed_keyword','')}\"",
                h2))
            flow.append(Paragraph(
                f"{len(nodes)} content nodes suggested.", body_style))
            for n in nodes[:8]:
                flow.append(Paragraph(f"• {n.get('title','')}", body_style))
            flow.append(Spacer(1, 12))

        lv = data.get("llm_visibility") or {}
        if lv:
            flow.append(Paragraph("LLM Visibility", h2))
            flow.append(Paragraph(
                f"Mention rate: <b>{lv.get('mention_rate_pct',0)}%</b> across "
                f"<b>{lv.get('total_scans',0)}</b> scans.", body_style))

        doc.build(flow)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"Report PDF generation failed: {e}")
        return None


@router.post("/seo/reports")
async def create_report(body: ReportIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    if not any([body.audit_id, body.heatmap_id, body.topical_map_id,
                  body.include_llm_visibility]):
        raise HTTPException(400,
            "At least one data source must be included in the report.")
    data = await _collect_report_data(tenant["id"], body)
    # Sanity: any referenced id that didn't resolve → 404 with detail.
    if body.audit_id and not data["audit"]:
        raise HTTPException(404, "audit_id not found for tenant")
    if body.heatmap_id and not data["heatmap"]:
        raise HTTPException(404, "heatmap_id not found for tenant")
    if body.topical_map_id and not data["topical_map"]:
        raise HTTPException(404, "topical_map_id not found for tenant")

    exec_summary = await _claude_exec_summary(
        body.brand_name or (tenant.get("name") or "Your Brand"), data)

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "title": body.title,
        "brand_name": body.brand_name or (tenant.get("name") or "Your Brand"),
        "brand_color": body.brand_color or "#0284C7",
        "logo_url": body.logo_url or "",
        "audit_id": body.audit_id,
        "heatmap_id": body.heatmap_id,
        "topical_map_id": body.topical_map_id,
        "include_llm_visibility": body.include_llm_visibility,
        "range_days": body.range_days,
        "notes": body.notes or "",
        "data": data,
        "exec_summary": exec_summary,
        "mocked": bool(exec_summary.get("mocked")),
        "status": "ready",
        "created_at": now_iso(),
    }
    await db.seo_reports.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/seo/reports")
async def list_reports(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    rows = await db.seo_reports.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "data": 0},   # heavy blob stripped from list view
    ).sort("created_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.get("/seo/reports/{rid}")
async def get_report(rid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    r = await db.seo_reports.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not r:
        raise HTTPException(404, "Report not found")
    return r


@router.get("/seo/reports/{rid}/download")
async def download_report(rid: str,
                            format: str = Query("pdf"),
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    r = await db.seo_reports.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not r:
        raise HTTPException(404, "Report not found")
    fmt = (format or "pdf").lower()
    if fmt not in {"pdf", "html"}:
        raise HTTPException(400, "format must be pdf|html")
    if fmt == "pdf":
        pdf = _report_pdf_bytes(r)
        if pdf:
            return StreamingResponse(
                io.BytesIO(pdf), media_type="application/pdf",
                headers={"Content-Disposition":
                          f'attachment; filename="report-{rid[:8]}.pdf"'},
            )
        # graceful fallback
        content = _report_html(r).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(content), media_type="text/html; charset=utf-8",
            headers={"Content-Disposition":
                      f'attachment; filename="report-{rid[:8]}.html"',
                      "X-Pdf-Fallback": "true"},
        )
    content = _report_html(r).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content), media_type="text/html; charset=utf-8",
        headers={"Content-Disposition":
                  f'attachment; filename="report-{rid[:8]}.html"'},
    )


@router.post("/seo/reports/{rid}/send")
async def send_report(rid: str, body: ReportSendIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.seo_reports.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not r:
        raise HTTPException(404, "Report not found")
    to = (body.to or "").strip().lower()
    if not to or "@" not in to:
        raise HTTPException(400, "Valid recipient email required")
    from config import RESEND_API_KEY, EMAIL_FROM
    if not RESEND_API_KEY:
        return {"sent": False, "reason": "resend-not-configured", "to": to}
    pdf = _report_pdf_bytes(r)
    attachment_type = "pdf" if pdf else "html"
    attachment_bytes = pdf if pdf else _report_html(r).encode("utf-8")
    fname = (f"report-{rid[:8]}.pdf" if pdf else f"report-{rid[:8]}.html")
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [to],
            "subject": (body.subject
                          or f"{r.get('brand_name','Your')} SEO Report · {r.get('title','')}"),
            "html": (body.message
                       or f"<p>Please find the attached SEO report — "
                       f"<b>{r.get('title','')}</b>.</p>"),
            "attachments": [{
                "filename": fname,
                "content": base64.b64encode(attachment_bytes).decode("ascii"),
            }],
        })
        await db.seo_reports.update_one(
            {"id": rid, "tenant_id": tenant["id"]},
            {"$set": {"last_sent_to": to, "last_sent_at": now_iso()}},
        )
        return {"sent": True, "to": to, "attachment_type": attachment_type}
    except Exception as e:
        logger.warning(f"Report send failed: {e}")
        return {"sent": False, "reason": str(e), "to": to,
                 "attachment_type": attachment_type}
