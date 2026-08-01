"""Phase 18 hotfix · Feb-2026 — Webform lead intake regression.

Reproduces the reported bug: browser-style ``https://…`` Origin headers
were being rejected against a bare-hostname allowlist, so every website
form submission failed with 403 and zero leads landed. This suite locks
in the scheme-normalization fix and asserts every payload field survives
end-to-end to ``db.leads``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _tenant_id() -> str:
    return _sync.tenants.find_one({"slug": "aquaterra"})["id"]


def _ensure_allowlist(host: str) -> None:
    """Ensure the tenant allowlist has our bare-host entry — the whole
    point of the fix is that a bare-host entry matches a schemed browser
    Origin."""
    _sync.tenants.update_one(
        {"slug": "aquaterra"},
        {"$addToSet": {"widget_allowed_domains": host}},
    )


def _cleanup(name: str) -> None:
    _sync.leads.delete_many({"name": name})


def test_webform_full_payload_lands_all_fields():
    host = "poolscape-audit.preview.emergentagent.com"
    _ensure_allowlist(host)
    name = "TEST_p18hf full-payload"
    _cleanup(name)
    r = requests.post(
        f"{API}/public/leads",
        headers={"Origin": f"https://{host}", "Content-Type": "application/json"},
        json={
            "name": name,
            "email": "jane@example.com",
            "phone": "+15551230000",
            "service_address": "123 Test Ln",
            "service_interest": "Pool",
            "notes": "Test description of services — pool cleanup + algae",
        },
        timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    row = _sync.leads.find_one({"id": body["lead_id"]}, {"_id": 0})
    try:
        assert row is not None, "lead not inserted"
        assert row["name"] == name
        assert row["email"] == "jane@example.com"
        assert row["phone"] == "+15551230000"
        assert row["service_address"] == "123 Test Ln"
        assert row["service_interest"] == "Pool"
        assert "algae" in (row["notes"] or "")
        assert row["source"] == "website_form"
    finally:
        _cleanup(name)


def test_webform_schemed_origin_matches_bare_host_allowlist():
    """The exact bug: bare-host allowlist entry must match schemed Origin."""
    host = f"host-{__import__('uuid').uuid4().hex[:8]}.example.test"
    _ensure_allowlist(host)
    name = f"TEST_p18hf schemed {host}"
    _cleanup(name)
    r = requests.post(
        f"{API}/public/leads",
        headers={"Origin": f"https://{host}", "Content-Type": "application/json"},
        json={"name": name, "email": "x@example.com",
              "notes": "svc description"},
        timeout=10,
    )
    try:
        assert r.status_code == 200, r.text
    finally:
        _cleanup(name)
        _sync.tenants.update_one(
            {"slug": "aquaterra"},
            {"$pull": {"widget_allowed_domains": host}},
        )


def test_webform_referer_with_path_still_matches():
    """Referer headers carry a path suffix — the matcher must still succeed."""
    host = "poolscape-audit.preview.emergentagent.com"
    _ensure_allowlist(host)
    name = "TEST_p18hf referer-with-path"
    _cleanup(name)
    r = requests.post(
        f"{API}/public/leads",
        headers={"Referer": f"https://{host}/public/leads?utm=x",
                 "Content-Type": "application/json"},
        json={"name": name, "email": "x@example.com",
              "notes": "svc description"},
        timeout=10,
    )
    try:
        assert r.status_code == 200, r.text
    finally:
        _cleanup(name)


def test_webform_unknown_origin_still_rejected():
    """The fix must NOT open the endpoint to every origin — hosts NOT on
    the allowlist must still be rejected with 403."""
    r = requests.post(
        f"{API}/public/leads",
        headers={"Origin": "https://evil-domain-not-in-allowlist.example",
                 "Content-Type": "application/json"},
        json={"name": "TEST_p18hf reject", "email": "x@example.com"},
        timeout=10,
    )
    assert r.status_code == 403, r.text
    assert "Origin not allowed" in r.json().get("detail", "")
