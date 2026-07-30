"""Phase 5a · pytest — AEO auditor signals + generators.

Covers:
  1. Full JSON-LD + FAQ HTML → overall_aeo_score >= 75.
  2. No schema / no FAQ / long passages → overall_aeo_score <= 30.
  3. llms.txt fetch: 200 text/plain body with "# " → score == 100.
  4. Generator: LocalBusiness + FAQPage w/ 3 FAQs → valid JSON-LD.
  5. LLMs.txt concise + full → tenant name in first line, correct filename.
  6. Role guard: tech + customer → 403 on both endpoints.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict

import pytest
import requests
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


# ── Fixtures ──────────────────────────────────────────────────────
_HTML_RICH = b"""
<html lang="en">
<head>
  <title>Blue Water Pools</title>
  <meta name="description"
        content="Blue Water Pools serves Phoenix with weekly pool service, tile cleaning, and equipment repair. Ten-year local family owned company.">
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"LocalBusiness",
   "name":"Blue Water Pools","url":"https://bluewaterpools.example",
   "sameAs":["https://facebook.com/bluewaterpools","https://linkedin.com/company/bluewaterpools"]}
  </script>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"FAQPage",
   "mainEntity":[
     {"@type":"Question","name":"How often should I clean my pool?",
      "acceptedAnswer":{"@type":"Answer","text":"Weekly is best."}},
     {"@type":"Question","name":"What is included in service?",
      "acceptedAnswer":{"@type":"Answer","text":"Chemistry, brushing, skimming, equipment check."}}
   ]}
  </script>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"Service","name":"Weekly pool cleaning"}
  </script>
</head>
<body>
  <h1>Blue Water Pools</h1>
  <p>Weekly pool cleaning in Phoenix.</p>
  <p>Certified technicians.</p>
  <h2>How often should I service my pool?</h2>
  <p>Weekly service is ideal in Phoenix heat.</p>
  <h3>What chemicals do you use?</h3>
  <p>EPA-approved chlorine and pH balancers.</p>
  <details><summary>Do you handle equipment repair?</summary>
    <p>Yes, pumps and filters.</p>
  </details>
</body>
</html>
""".strip()

_HTML_POOR = (b"""
<html>
<head><title>x</title></head>
<body>
<p>""" + (b"lorem ipsum " * 200) + b"""</p>
<p>""" + (b"lorem ipsum " * 200) + b"""</p>
</body></html>
""").strip()


# ── 1. Rich HTML → high AEO score ────────────────────────────────
def test_aeo_signals_high_score_on_rich_html():
    from services.aeo_auditor import aeo_signals_from_html
    sigs = aeo_signals_from_html(_HTML_RICH,
                                    base_url="https://bluewaterpools.example",
                                    business_name="Blue Water Pools",
                                    llms_txt={"present": True,
                                                "url_checked": "x",
                                                "size_bytes": 200,
                                                "score": 100})
    assert sigs["overall_aeo_score"] >= 75, sigs
    assert sigs["schema"]["score"] >= 60
    assert sigs["faq"]["schema_faq"] is True
    assert sigs["faq"]["count"] >= 2


# ── 2. Poor HTML → low score ─────────────────────────────────────
def test_aeo_signals_low_score_on_poor_html():
    from services.aeo_auditor import aeo_signals_from_html
    sigs = aeo_signals_from_html(_HTML_POOR,
                                    base_url="https://x.example",
                                    business_name="",
                                    llms_txt={"present": False,
                                                "url_checked": "x",
                                                "size_bytes": 0,
                                                "score": 0})
    assert sigs["overall_aeo_score"] <= 30, sigs
    assert sigs["schema"]["score"] == 0
    assert sigs["faq"]["count"] == 0
    assert sigs["passages"]["over_90_words"] >= 1


# ── 3. llms.txt fetch presence ───────────────────────────────────
def test_llms_txt_presence_positive_and_negative():
    import httpx
    from services.aeo_auditor import fetch_llms_txt_presence

    def _handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/llms.txt" and "good.example" in req.url.host:
            return httpx.Response(200, content=b"# Blue Water Pools\n> Test",
                                    headers={"content-type": "text/plain"})
        return httpx.Response(404)

    async def _run(host):
        transport = httpx.MockTransport(_handler)
        async with httpx.AsyncClient(transport=transport) as c:
            return await fetch_llms_txt_presence(c, f"https://{host}/")

    good = asyncio.run(_run("good.example"))
    assert good["present"] is True and good["score"] == 100
    assert good["size_bytes"] > 0
    bad = asyncio.run(_run("nope.example"))
    assert bad["present"] is False and bad["score"] == 0


# ── 4. JSON-LD generator ─────────────────────────────────────────
def test_generate_jsonld_localbusiness_and_faqpage():
    from services.aeo_generators import generate_jsonld
    out = generate_jsonld(
        types=["LocalBusiness", "FAQPage"],
        business_profile={
            "name": "Blue Water Pools",
            "url": "https://bluewaterpools.example",
            "phone": "+1-602-555-0100",
            "address": {"streetAddress": "123 Main St", "city": "Phoenix",
                          "state": "AZ", "postalCode": "85001"},
        },
        faqs=[
            {"question": "How often?", "answer": "Weekly."},
            {"question": "What chemicals?", "answer": "EPA-approved."},
            {"question": "Do you repair?", "answer": "Yes."},
        ],
    )
    assert out["count"] == 2
    types = [b["type"] for b in out["blocks"]]
    assert "LocalBusiness" in types and "FAQPage" in types
    # Each block must be valid JSON.
    for b in out["blocks"]:
        parsed = json.loads(b["jsonld_string"])
        assert parsed["@context"] == "https://schema.org"
    # combined_script must be a valid <script> wrapper containing a JSON list.
    assert out["combined_script"].startswith("<script")
    assert "</script>" in out["combined_script"]
    inner = out["combined_script"].split(">", 1)[1].rsplit("<", 1)[0]
    arr = json.loads(inner)
    assert isinstance(arr, list) and len(arr) == 2
    faq = [x for x in arr if x["@type"] == "FAQPage"][0]
    assert len(faq["mainEntity"]) == 3
    assert faq["mainEntity"][0]["name"] == "How often?"


# ── 5. LLMs.txt concise + full ───────────────────────────────────
def test_llms_txt_concise_and_full():
    from services.aeo_generators import generate_llms_txt
    tenant = {"name": "Blue Water Pools",
              "url": "https://bluewaterpools.example",
              "phone": "+1-602-555-0100",
              "tagline": "Weekly pool care in the Valley.",
              "service_areas": ["Phoenix", "Scottsdale"],
              "services": ["Weekly cleaning", "Equipment repair"],
              "faqs": [{"question": "Q1", "answer": "A1"}]}
    concise = generate_llms_txt(tenant, style="concise", include_faqs=False)
    assert concise["filename"] == "llms.txt"
    assert concise["content"].splitlines()[0] == "# Blue Water Pools"
    assert concise["byte_size"] > 0
    assert "install" in concise["install_instructions"].lower() or "copy" in concise["install_instructions"].lower()

    full = generate_llms_txt(tenant, style="full", include_faqs=True,
                                recent_checkins=[{"title": "Weekly clean at 42 Palm",
                                                    "summary": "Balanced pH and skim."}])
    assert full["filename"] == "llms-full.txt"
    lines = full["content"].splitlines()
    assert lines[0] == "# Blue Water Pools"
    assert any(l == "## Services" for l in lines)
    assert any(l == "## FAQ" for l in lines)
    assert any(l == "## Recent work" for l in lines)
    assert "Q1" in full["content"]


# ── 6. Role guard — tech + customer forbidden ────────────────────
@pytest.mark.parametrize("email", ["landscaper@aquaterra.com",
                                    "customer@aquaterra.com"])
def test_role_guard_forbids_tech_and_customer(email):
    tok = _login(email)
    r = requests.post(f"{API}/aeo/jsonld/generate",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"types": ["LocalBusiness"], "business_profile": {}},
                       timeout=10)
    assert r.status_code == 403, f"{email} jsonld → {r.status_code}"
    r = requests.post(f"{API}/aeo/llms-txt/generate",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"style": "concise"}, timeout=10)
    assert r.status_code == 403, f"{email} llms-txt → {r.status_code}"


# ── 7. Live endpoints — manager 200 with valid JSON-LD out ───────
def test_live_jsonld_endpoint_returns_valid_script():
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/aeo/jsonld/generate",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"types": ["LocalBusiness", "FAQPage"],
                              "business_profile": {"name": "Test Pool Co",
                                                    "url": "https://test.example"},
                              "faqs": [{"question": "Q?", "answer": "A."}]},
                       timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["count"] == 2
    assert "<script" in d["combined_script"]


def test_live_llms_txt_endpoint_returns_content():
    tok = _login("manager@aquaterra.com")
    r = requests.post(f"{API}/aeo/llms-txt/generate",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"style": "concise", "include_faqs": False},
                       timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["filename"] == "llms.txt"
    assert d["byte_size"] > 0
    assert d["content"].startswith("# ")
