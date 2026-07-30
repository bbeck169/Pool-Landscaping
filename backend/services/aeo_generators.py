"""Phase 5a · Feb-2026 — JSON-LD generator + LLMs.txt generator.

Pure builders — no network. Fed by the router with tenant profile
+ user-supplied FAQs / HowTo steps.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# ── JSON-LD builders ─────────────────────────────────────────────

def _clean(x: Any) -> Any:
    """Strip None/empty values recursively so the emitted JSON-LD is
    tight (Google likes minimal, correct blocks)."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()
                if v not in (None, "", [], {})}
    if isinstance(x, list):
        return [_clean(v) for v in x if v not in (None, "", [], {})]
    return x


def build_local_business(profile: Dict[str, Any]) -> Dict[str, Any]:
    addr = profile.get("address") or {}
    if isinstance(addr, str):
        # Flatten string address into `streetAddress`.
        addr = {"streetAddress": addr}
    ld: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": profile.get("name"),
        "url": profile.get("url"),
        "telephone": profile.get("phone"),
        "email": profile.get("email"),
        "address": {
            "@type": "PostalAddress",
            "streetAddress": addr.get("streetAddress"),
            "addressLocality": addr.get("city") or addr.get("addressLocality"),
            "addressRegion": addr.get("state") or addr.get("addressRegion"),
            "postalCode": addr.get("postalCode") or addr.get("zip"),
            "addressCountry": addr.get("country") or addr.get("addressCountry") or "US",
        } if addr else None,
        "areaServed": profile.get("service_areas") or profile.get("areaServed"),
        "priceRange": profile.get("price_range"),
        "sameAs": profile.get("same_as") or profile.get("sameAs"),
    }
    if profile.get("hours"):
        # Accept both dict {mon: "09:00-17:00", ...} and pre-formatted list.
        h = profile["hours"]
        if isinstance(h, dict):
            spec: List[Dict[str, Any]] = []
            _map = {"mon":"Monday","tue":"Tuesday","wed":"Wednesday",
                    "thu":"Thursday","fri":"Friday","sat":"Saturday",
                    "sun":"Sunday"}
            for k, v in h.items():
                if not v: continue
                try:
                    opens, closes = v.split("-", 1)
                    spec.append({"@type": "OpeningHoursSpecification",
                                  "dayOfWeek": _map.get(k.lower(), k),
                                  "opens": opens.strip(),
                                  "closes": closes.strip()})
                except ValueError:
                    continue
            ld["openingHoursSpecification"] = spec
        elif isinstance(h, list):
            ld["openingHoursSpecification"] = h
    return _clean(ld)


def build_organization(profile: Dict[str, Any]) -> Dict[str, Any]:
    ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": profile.get("name"),
        "url": profile.get("url"),
        "logo": profile.get("logo"),
        "sameAs": profile.get("same_as") or profile.get("sameAs"),
        "contactPoint": {
            "@type": "ContactPoint",
            "telephone": profile.get("phone"),
            "contactType": "customer service",
            "email": profile.get("email"),
        } if profile.get("phone") or profile.get("email") else None,
    }
    return _clean(ld)


def build_service(profile: Dict[str, Any],
                    services: Optional[List[Dict[str, Any]]] = None,
                    ) -> Dict[str, Any]:
    # Emit an ItemList of Service so multiple services fit in one block.
    services = services or profile.get("services") or []
    if isinstance(services, list) and services and isinstance(services[0], str):
        services = [{"name": s} for s in services]
    items = []
    for i, s in enumerate(services or []):
        items.append({
            "@type": "Service",
            "position": i + 1,
            "name": s.get("name"),
            "description": s.get("description"),
            "areaServed": s.get("area_served") or profile.get("service_areas"),
            "provider": {"@type": "LocalBusiness",
                           "name": profile.get("name")},
        })
    ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{profile.get('name') or 'Services'} · Services",
        "itemListElement": items,
    }
    return _clean(ld)


def build_faqpage(faqs: List[Dict[str, str]]) -> Dict[str, Any]:
    ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question",
            "name": f.get("question") or f.get("q"),
            "acceptedAnswer": {
                "@type": "Answer",
                "text": f.get("answer") or f.get("a"),
            },
        } for f in (faqs or []) if (f.get("question") or f.get("q"))],
    }
    return _clean(ld)


def build_howto(howto: Dict[str, Any]) -> Dict[str, Any]:
    steps = howto.get("steps") or []
    ld = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": howto.get("name"),
        "description": howto.get("description"),
        "step": [{"@type": "HowToStep",
                    "position": i + 1,
                    "name": s.get("name"),
                    "text": s.get("text")}
                   for i, s in enumerate(steps)
                   if (s.get("name") or s.get("text"))],
    }
    return _clean(ld)


_BUILDERS = {
    "LocalBusiness": lambda p, extras: build_local_business(p),
    "Organization": lambda p, extras: build_organization(p),
    "Service":      lambda p, extras: build_service(p, extras.get("services")),
    "FAQPage":      lambda p, extras: build_faqpage(extras.get("faqs") or []),
    "HowTo":        lambda p, extras: build_howto(extras.get("howto") or {}),
}


def generate_jsonld(types: List[str],
                     business_profile: Dict[str, Any],
                     faqs: Optional[List[Dict[str, str]]] = None,
                     howto: Optional[Dict[str, Any]] = None,
                     services: Optional[List[Dict[str, Any]]] = None,
                     ) -> Dict[str, Any]:
    """Return {blocks: [{type, jsonld_string, jsonld}], combined_script}."""
    extras = {"faqs": faqs, "howto": howto, "services": services}
    blocks: List[Dict[str, Any]] = []
    ordered: List[Dict[str, Any]] = []
    for t in types or []:
        builder = _BUILDERS.get(t)
        if not builder:
            continue
        obj = builder(business_profile or {}, extras)
        if not obj:
            continue
        # Validate by round-tripping through json.
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        json.loads(text)  # will raise ValueError if malformed
        blocks.append({"type": t, "jsonld_string": text, "jsonld": obj})
        ordered.append(obj)
    combined_json = json.dumps(ordered, ensure_ascii=False,
                                separators=(",", ":"))
    combined_script = (
        f"<script type=\"application/ld+json\">{combined_json}</script>"
    )
    return {"blocks": blocks, "combined_script": combined_script,
            "count": len(blocks)}


# ── LLMs.txt builders ────────────────────────────────────────────

def _one_line(s: str) -> str:
    return " ".join((s or "").split())


def generate_llms_txt(tenant: Dict[str, Any],
                        style: str = "concise",
                        include_faqs: bool = False,
                        recent_checkins: Optional[List[Dict[str, Any]]] = None,
                        ) -> Dict[str, Any]:
    """Return {filename, content, byte_size, install_instructions}."""
    name = tenant.get("name") or tenant.get("business_name") or "Business"
    tagline = tenant.get("tagline") or tenant.get("description") or ""
    url = tenant.get("url") or tenant.get("website") or ""
    phone = tenant.get("phone") or ""
    services = tenant.get("services") or []
    if isinstance(services, list) and services and isinstance(services[0], dict):
        service_names = [s.get("name") for s in services if s.get("name")]
    else:
        service_names = list(services or [])
    areas = tenant.get("service_areas") or []
    faqs = tenant.get("faqs") or []

    lines: List[str] = []
    lines.append(f"# {name}")
    if tagline:
        lines.append(f"> {_one_line(tagline)}")
    lines.append("")
    if url:
        lines.append(f"- Website: {url}")
    if phone:
        lines.append(f"- Phone: {phone}")
    if areas:
        lines.append(f"- Service areas: {', '.join(areas)}")
    if service_names:
        lines.append("")
        lines.append("## Services")
        for s in service_names:
            lines.append(f"- {s}")

    if style == "full":
        lines.append("")
        lines.append("## About")
        about = tenant.get("about") or tagline or (
            f"{name} provides {', '.join(service_names[:3])} services "
            f"in {', '.join(areas[:2])}."
            if service_names and areas else ""
        )
        if about:
            lines.append(_one_line(about))
        if recent_checkins:
            lines.append("")
            lines.append("## Recent work")
            for c in recent_checkins[:5]:
                t = c.get("title") or "Job"
                summ = c.get("summary") or c.get("notes") or ""
                if summ:
                    lines.append(f"- **{t}** — {_one_line(summ)[:180]}")
                else:
                    lines.append(f"- **{t}**")

    if include_faqs and faqs:
        lines.append("")
        lines.append("## FAQ")
        for f in faqs[:15]:
            q = f.get("question") or f.get("q") or ""
            a = f.get("answer") or f.get("a") or ""
            if q and a:
                lines.append(f"### {q}")
                lines.append(_one_line(a))
                lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    filename = "llms-full.txt" if style == "full" else "llms.txt"
    install = (
        f"Copy the file to your web-site repo at the root URL path so it "
        f"is reachable at `{url.rstrip('/')}/{filename}` (or "
        f"`https://your-site.com/{filename}` if the URL above is empty). "
        f"For static hosts (Netlify, Vercel, Cloudflare Pages, GitHub "
        f"Pages) drop it into the public/static directory. For custom "
        f"servers add a route that serves it with `Content-Type: text/plain`."
    )
    return {"filename": filename, "content": content,
            "byte_size": len(content.encode("utf-8")),
            "install_instructions": install}
