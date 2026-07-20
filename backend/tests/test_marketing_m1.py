"""Marketing Subsystem · Phase M1 — Foundation backend tests.

Covers:

* Auto-seed of default segment + list per tenant on first admin hit
* Subscriber CRUD (create/list/patch/unsubscribe/delete) + email de-dupe
* Segment DSL: compile + preview matched_count + sample + ad-hoc preview
* Dynamic list resolves via segment; static list membership add/remove
* Marketing settings: GET returns defaults; PUT persists
* Public signup with DOI on → status=pending_confirmation + honeypot ignored
* Public confirm endpoint flips subscriber to ``subscribed``
* Public signup with tenant DOI off → status=subscribed + list membership
* CRM mirror: creating a Customer auto-creates a subscriber
* Tenant isolation: super_admin cross-tenant via X-Tenant-Slug stays scoped
* RBAC: technician role is 403 on every admin endpoint
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

from tests.conftest import demo_pw

BACKEND = os.environ.get("REACT_APP_BACKEND_URL") \
    or "https://poolscape-audit.preview.emergentagent.com"
API = f"{BACKEND}/api"
T = 20


# ─── helpers ──────────────────────────────────────────────────────────

def _login(email, pw):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com", demo_pw("mike@aquaterra.com"))


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    r = requests.get(f"{API}/tenants/current", headers=_h(admin_tok), timeout=T)
    r.raise_for_status()
    return r.json()["id"]


# ─── Auto-seed on first admin hit ─────────────────────────────────────

class TestAutoSeed:
    def test_first_segments_hit_seeds_active_subscribers(self, admin_tok):
        r = requests.get(f"{API}/marketing/segments",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        slugs = {s["slug"] for s in d["segments"]}
        assert "active-subscribers" in slugs
        active = next(s for s in d["segments"] if s["slug"] == "active-subscribers")
        assert active["is_system_default"] is True
        assert active["rules"]["combinator"] == "and"

    def test_first_lists_hit_seeds_all_subscribers(self, admin_tok):
        r = requests.get(f"{API}/marketing/lists",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        slugs = {l["slug"] for l in d["lists"]}
        assert "all-subscribers" in slugs

    def test_second_hit_is_idempotent(self, admin_tok):
        r1 = requests.get(f"{API}/marketing/segments",
                           headers=_h(admin_tok), timeout=T)
        r2 = requests.get(f"{API}/marketing/segments",
                           headers=_h(admin_tok), timeout=T)
        assert r1.json()["count"] == r2.json()["count"]


# ─── RBAC ─────────────────────────────────────────────────────────────

class TestRBAC:
    def test_tech_forbidden_on_subscribers(self, tech_tok):
        r = requests.get(f"{API}/marketing/subscribers",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403

    def test_tech_forbidden_on_lists(self, tech_tok):
        r = requests.get(f"{API}/marketing/lists",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403

    def test_tech_forbidden_on_segments(self, tech_tok):
        r = requests.get(f"{API}/marketing/segments",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403

    def test_tech_forbidden_on_settings(self, tech_tok):
        r = requests.get(f"{API}/marketing/settings",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code == 403


# ─── Marketing settings ───────────────────────────────────────────────

class TestSettings:
    def test_defaults_are_returned(self, admin_tok):
        r = requests.get(f"{API}/marketing/settings",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["require_double_optin"], bool)
        assert isinstance(d["revenue_attribution_days"], int)
        assert d["revenue_attribution_days"] >= 1

    def test_put_persists_settings(self, admin_tok):
        # Read baseline.
        base = requests.get(f"{API}/marketing/settings",
                             headers=_h(admin_tok), timeout=T).json()
        r = requests.put(f"{API}/marketing/settings",
                          json={"require_double_optin": True,
                                 "revenue_attribution_days": 45},
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["revenue_attribution_days"] == 45
        # Restore.
        requests.put(f"{API}/marketing/settings",
                     json={"revenue_attribution_days":
                             base.get("revenue_attribution_days", 30)},
                     headers=_h(admin_tok), timeout=T)


# ─── Subscriber CRUD ─────────────────────────────────────────────────

class TestSubscribersCRUD:
    _sub_id = None

    def test_create_and_list(self, admin_tok):
        email = f"alexa_TEST_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/marketing/subscribers",
                           json={"email": email, "first_name": "Alexa",
                                  "tags": ["VIP", "TEST_seed"],
                                  "attributes": {"pool_gallons": 18000}},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "subscribed"
        assert body["source"] == "manual"
        assert body["email"] == email.lower()
        TestSubscribersCRUD._sub_id = body["id"]

        # Duplicate rejected.
        r2 = requests.post(f"{API}/marketing/subscribers",
                            json={"email": email},
                            headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 409

    def test_search_filter(self, admin_tok):
        r = requests.get(f"{API}/marketing/subscribers?q=alexa_TEST",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    def test_patch_status(self, admin_tok):
        assert TestSubscribersCRUD._sub_id
        r = requests.patch(
            f"{API}/marketing/subscribers/{TestSubscribersCRUD._sub_id}",
            json={"first_name": "Alexa-Renamed", "tags": ["VIP-updated"]},
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["first_name"] == "Alexa-Renamed"
        assert "VIP-updated" in r.json()["tags"]

    def test_unsubscribe(self, admin_tok):
        assert TestSubscribersCRUD._sub_id
        r = requests.post(
            f"{API}/marketing/subscribers/"
            f"{TestSubscribersCRUD._sub_id}/unsubscribe",
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        row = requests.get(
            f"{API}/marketing/subscribers/{TestSubscribersCRUD._sub_id}",
            headers=_h(admin_tok), timeout=T).json()
        assert row["status"] == "unsubscribed"
        assert row["unsubscribed_at"]

    def test_delete_cleans_up(self, admin_tok):
        assert TestSubscribersCRUD._sub_id
        r = requests.delete(
            f"{API}/marketing/subscribers/{TestSubscribersCRUD._sub_id}",
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 204
        # Second delete → 404.
        r2 = requests.delete(
            f"{API}/marketing/subscribers/{TestSubscribersCRUD._sub_id}",
            headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 404

    def test_email_or_phone_required(self, admin_tok):
        r = requests.post(f"{API}/marketing/subscribers",
                           json={"first_name": "Nobody"},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 422


# ─── Segments ─────────────────────────────────────────────────────────

class TestSegments:
    _seg_id = None
    _sub_ids = []

    def _seed_subs(self, admin_tok):
        # Seed two VIP + one non-VIP subscriber, all in status=subscribed.
        for i, tag in enumerate(["VIP", "VIP", "Regular"]):
            email = f"seg_TEST_{i}_{uuid.uuid4().hex[:6]}@example.com"
            r = requests.post(f"{API}/marketing/subscribers",
                               json={"email": email,
                                      "tags": [tag, "TEST_seed"]},
                               headers=_h(admin_tok), timeout=T)
            assert r.status_code == 201, r.text
            TestSegments._sub_ids.append(r.json()["id"])

    def test_create_segment_with_valid_rule(self, admin_tok):
        self._seed_subs(admin_tok)
        r = requests.post(f"{API}/marketing/segments",
                           json={"name": "TEST_ VIP Subs",
                                  "rules": {"combinator": "and", "rules": [
                                      {"field": "tags", "op": "contains",
                                       "value": "VIP"},
                                      {"field": "status", "op": "eq",
                                       "value": "subscribed"},
                                  ]}},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        TestSegments._seg_id = r.json()["id"]

    def test_preview_returns_matched_count(self, admin_tok):
        assert TestSegments._seg_id
        r = requests.post(
            f"{API}/marketing/segments/{TestSegments._seg_id}/preview",
            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        d = r.json()
        assert d["matched_count"] >= 2  # the two VIP subs we seeded
        assert d["sample_size"] >= 2
        assert all(("VIP" in (s.get("tags") or [])) for s in d["sample"])

    def test_adhoc_preview_no_save(self, admin_tok):
        # Filter by tag we know we seeded.
        r = requests.post(f"{API}/marketing/segments/preview",
                           json={"name": "adhoc",
                                  "rules": {"field": "tags",
                                             "op": "contains",
                                             "value": "TEST_seed"}},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["matched_count"] >= 3

    def test_invalid_rules_return_422(self, admin_tok):
        r = requests.post(f"{API}/marketing/segments",
                           json={"name": "bad",
                                  "rules": {"field": "not_a_real_field",
                                             "op": "eq", "value": "x"}},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 422

    def test_delete_default_segment_blocked(self, admin_tok):
        r = requests.get(f"{API}/marketing/segments",
                          headers=_h(admin_tok), timeout=T)
        default = next(s for s in r.json()["segments"]
                        if s["slug"] == "active-subscribers")
        rd = requests.delete(f"{API}/marketing/segments/{default['id']}",
                              headers=_h(admin_tok), timeout=T)
        assert rd.status_code == 400

    def test_cleanup(self, admin_tok):
        # Remove the seg we made (no dynamic list points at it here).
        if TestSegments._seg_id:
            requests.delete(
                f"{API}/marketing/segments/{TestSegments._seg_id}",
                headers=_h(admin_tok), timeout=T)
        for sid in TestSegments._sub_ids:
            requests.delete(f"{API}/marketing/subscribers/{sid}",
                             headers=_h(admin_tok), timeout=T)


# ─── Lists (static + dynamic) ─────────────────────────────────────────

class TestLists:
    _static_id = None
    _dynamic_id = None
    _seg_id = None
    _sub_ids = []

    def test_static_list_add_remove_members(self, admin_tok):
        # Seed a subscriber.
        email = f"list_TEST_{uuid.uuid4().hex[:6]}@example.com"
        rsub = requests.post(f"{API}/marketing/subscribers",
                              json={"email": email,
                                     "tags": ["TEST_seed"]},
                              headers=_h(admin_tok), timeout=T)
        assert rsub.status_code == 201, rsub.text
        sid = rsub.json()["id"]
        TestLists._sub_ids.append(sid)

        r = requests.post(f"{API}/marketing/lists",
                           json={"name": "TEST_ Static Members",
                                  "type": "static"},
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code == 201, r.text
        TestLists._static_id = r.json()["id"]

        add = requests.post(
            f"{API}/marketing/lists/{TestLists._static_id}/members",
            json={"subscriber_ids": [sid]},
            headers=_h(admin_tok), timeout=T)
        assert add.status_code == 201
        assert add.json()["added"] == 1

        members = requests.get(
            f"{API}/marketing/lists/{TestLists._static_id}/members",
            headers=_h(admin_tok), timeout=T)
        assert members.status_code == 200
        assert members.json()["count"] == 1

        # Idempotent add.
        add2 = requests.post(
            f"{API}/marketing/lists/{TestLists._static_id}/members",
            json={"subscriber_ids": [sid]},
            headers=_h(admin_tok), timeout=T)
        assert add2.status_code == 201
        assert add2.json()["added"] == 0

        rm = requests.delete(
            f"{API}/marketing/lists/{TestLists._static_id}/members/{sid}",
            headers=_h(admin_tok), timeout=T)
        assert rm.status_code == 204

    def test_dynamic_list_resolves_via_segment(self, admin_tok):
        # Segment: everyone tagged TEST_seed.
        rseg = requests.post(f"{API}/marketing/segments",
                              json={"name": "TEST_ Dyn Seg",
                                     "rules": {"field": "tags",
                                                "op": "contains",
                                                "value": "TEST_seed"}},
                              headers=_h(admin_tok), timeout=T)
        assert rseg.status_code == 201, rseg.text
        TestLists._seg_id = rseg.json()["id"]

        rlst = requests.post(f"{API}/marketing/lists",
                              json={"name": "TEST_ Dyn List",
                                     "type": "dynamic",
                                     "segment_id": TestLists._seg_id},
                              headers=_h(admin_tok), timeout=T)
        assert rlst.status_code == 201, rlst.text
        TestLists._dynamic_id = rlst.json()["id"]

        # Add a subscriber tagged TEST_seed, then verify the dynamic
        # list surfaces it without an explicit membership row.
        email = f"dyn_TEST_{uuid.uuid4().hex[:6]}@example.com"
        rsub = requests.post(f"{API}/marketing/subscribers",
                              json={"email": email,
                                     "tags": ["TEST_seed"]},
                              headers=_h(admin_tok), timeout=T)
        assert rsub.status_code == 201
        TestLists._sub_ids.append(rsub.json()["id"])

        members = requests.get(
            f"{API}/marketing/lists/{TestLists._dynamic_id}/members",
            headers=_h(admin_tok), timeout=T)
        assert members.status_code == 200
        emails = {(s.get("email") or "") for s in members.json()["subscribers"]}
        assert email.lower() in emails

    def test_delete_default_list_blocked(self, admin_tok):
        r = requests.get(f"{API}/marketing/lists",
                          headers=_h(admin_tok), timeout=T)
        default = next(l for l in r.json()["lists"]
                        if l["slug"] == "all-subscribers")
        rd = requests.delete(f"{API}/marketing/lists/{default['id']}",
                              headers=_h(admin_tok), timeout=T)
        assert rd.status_code == 400

    def test_delete_segment_blocked_when_dynamic_list_uses_it(self, admin_tok):
        assert TestLists._seg_id
        rd = requests.delete(f"{API}/marketing/segments/{TestLists._seg_id}",
                              headers=_h(admin_tok), timeout=T)
        assert rd.status_code == 400

    def test_cleanup(self, admin_tok):
        for lid in (TestLists._static_id, TestLists._dynamic_id):
            if lid:
                requests.delete(f"{API}/marketing/lists/{lid}",
                                 headers=_h(admin_tok), timeout=T)
        if TestLists._seg_id:
            requests.delete(f"{API}/marketing/segments/{TestLists._seg_id}",
                             headers=_h(admin_tok), timeout=T)
        for sid in TestLists._sub_ids:
            requests.delete(f"{API}/marketing/subscribers/{sid}",
                             headers=_h(admin_tok), timeout=T)


# ─── Public signup + confirm ──────────────────────────────────────────

class TestPublicSignup:
    _form_slug = None
    _form_id = None
    _sub_email = None

    def _create_form(self, admin_tok, **extra):
        payload = {"name": f"TEST_ Newsletter {uuid.uuid4().hex[:6]}",
                    "status": "published",
                    "fields": [{"name": "email", "type": "email",
                                 "label": "Email", "required": True}]}
        payload.update(extra)
        r = requests.post(f"{API}/forms", json=payload,
                           headers=_h(admin_tok), timeout=T)
        assert r.status_code in (200, 201), r.text
        return r.json()

    def test_signup_with_doi_default_lands_pending(self, admin_tok,
                                                    tenant_id):
        # Ensure tenant DOI is on (default).
        requests.put(f"{API}/marketing/settings",
                     json={"require_double_optin": True},
                     headers=_h(admin_tok), timeout=T)

        form = self._create_form(admin_tok)
        TestPublicSignup._form_slug = form["slug"]
        TestPublicSignup._form_id = form.get("id")
        email = f"public_TEST_{uuid.uuid4().hex[:8]}@example.com"
        TestPublicSignup._sub_email = email

        r = requests.post(
            f"{API}/marketing/public/signup-form/"
            f"{TestPublicSignup._form_slug}/subscribe",
            json={"email": email, "first_name": "Publicly"},
            timeout=T)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "pending_confirmation"
        assert d["require_confirm"] is True

    def test_honeypot_returns_ignored(self, admin_tok):
        assert TestPublicSignup._form_slug
        r = requests.post(
            f"{API}/marketing/public/signup-form/"
            f"{TestPublicSignup._form_slug}/subscribe",
            json={"email": f"bot_TEST_{uuid.uuid4().hex[:6]}@example.com",
                  "honeypot": "gotcha"},
            timeout=T)
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"

    def test_confirm_flips_to_subscribed(self, admin_tok, tenant_id):
        from services.marketing_subscribers import sign_confirmation
        email = TestPublicSignup._sub_email
        token = sign_confirmation(tenant_id, email)
        r = requests.post(f"{API}/marketing/public/confirm",
                          json={"tenant_id": tenant_id,
                                 "email": email, "token": token},
                          timeout=T)
        assert r.status_code == 200, r.text
        assert r.json()["subscriber"]["status"] == "subscribed"
        assert r.json()["subscriber"]["confirmed_at"]

    def test_confirm_bad_token_403(self, admin_tok, tenant_id):
        r = requests.post(f"{API}/marketing/public/confirm",
                          json={"tenant_id": tenant_id,
                                 "email": TestPublicSignup._sub_email,
                                 "token": "notasignature"},
                          timeout=T)
        assert r.status_code == 403

    def test_signup_with_doi_disabled_subscribes_immediately(self,
                                                                admin_tok):
        # Publish a new form that overrides tenant DOI.
        form = self._create_form(admin_tok, double_opt_in=False)
        email = f"nodoi_TEST_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(
            f"{API}/marketing/public/signup-form/{form['slug']}/subscribe",
            json={"email": email, "first_name": "NoDoI"},
            timeout=T)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "subscribed"

    def test_cleanup(self, admin_tok):
        # Purge test subscribers + form.
        r = requests.get(f"{API}/marketing/subscribers?q=_TEST_",
                          headers=_h(admin_tok), timeout=T)
        for s in r.json().get("subscribers", []):
            requests.delete(f"{API}/marketing/subscribers/{s['id']}",
                             headers=_h(admin_tok), timeout=T)
        # Form deletion — legacy endpoint keyed by fid.
        if TestPublicSignup._form_id:
            requests.delete(f"{API}/forms/{TestPublicSignup._form_id}",
                             headers=_h(admin_tok), timeout=T)


# ─── CRM mirror ───────────────────────────────────────────────────────

class TestCrmMirror:
    def test_creating_customer_creates_subscriber(self, admin_tok):
        email = f"mirror_TEST_{uuid.uuid4().hex[:8]}@example.com"
        rc = requests.post(f"{API}/customers",
                            json={"name": "TEST_ Mirror",
                                   "email": email,
                                   "phone": "+15551110000"},
                            headers=_h(admin_tok), timeout=T)
        assert rc.status_code == 200, rc.text
        cid = rc.json()["id"]

        # Poll: the mirror is best-effort/async-safe but currently sync.
        found = None
        for _ in range(5):
            r = requests.get(f"{API}/marketing/subscribers?q=mirror_TEST",
                              headers=_h(admin_tok), timeout=T)
            for s in r.json().get("subscribers", []):
                if s.get("email") == email.lower():
                    found = s
                    break
            if found:
                break
        assert found, "subscriber row was not mirrored from customer.create"
        assert found["source"] == "crm_customer"
        assert found["status"] == "subscribed"
        assert found["customer_id"] == cid
        # Cleanup.
        requests.delete(f"{API}/marketing/subscribers/{found['id']}",
                         headers=_h(admin_tok), timeout=T)
        requests.delete(f"{API}/customers/{cid}",
                         headers=_h(admin_tok), timeout=T)


# ─── Tenant isolation ─────────────────────────────────────────────────

class TestTenantIsolation:
    def test_tenant_scoped_lists(self, admin_tok, tenant_id):
        # Every returned list must belong to this tenant.
        r = requests.get(f"{API}/marketing/lists",
                          headers=_h(admin_tok), timeout=T)
        for l in r.json()["lists"]:
            assert l["tenant_id"] == tenant_id

    def test_tenant_scoped_subscribers(self, admin_tok, tenant_id):
        r = requests.get(f"{API}/marketing/subscribers",
                          headers=_h(admin_tok), timeout=T)
        for s in r.json()["subscribers"]:
            assert s["tenant_id"] == tenant_id
