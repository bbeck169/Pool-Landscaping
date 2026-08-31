"""Phase F4 · E2E API tests — Widget-Embed Check-ins Map + moderation source.

Covers:
* GET /api/public/checkins/{slug}/pins  — schema + PII whitelist
* GET /api/public/checkins/{slug}/map.html — Leaflet + JSON-LD + no PII
* 404 on unknown tenant slug (no enumeration)
* 60/min per-IP rate limit -> 429
* Auto-enqueue on job completion (source='auto', obfuscated coords)
* Idempotency (no duplicate row for the same source_job_id)
* Tenant setting auto_enqueue_public_checkins=false gate
* Moderation list returns `source` field (demo seed rows)
* Regression: /api/widget.js and /api/widget/preview/{slug}
"""
import json
import os
import re
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or _fe.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

_be = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or _be.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _be.get("DB_NAME")

SLUG = "aquaterra"
ADMIN_EMAIL = "admin@aquaterra.com"
ADMIN_PW = "password123"

PIN_KEYS = {"lat", "lng", "service_type", "completed_at_month_year",
            "area_label"}
FORBIDDEN_SUBSTRINGS = ["customer_name", "customer_id", "job_id",
                        "lat_raw", "lng_raw", "raw_address",
                        "source_job_id", "submitted_by_user_id"]


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_headers(client):
    r = client.post(f"{BASE_URL}/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    if r.status_code != 200:
        pytest.fail(f"admin login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("access_token")
    assert tok, f"no access_token in login response: {r.text[:200]}"
    return {"Authorization": f"Bearer {tok}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tenant_id(client, admin_headers):
    r = client.get(f"{BASE_URL}/api/auth/me", headers=admin_headers)
    assert r.status_code == 200, r.text[:300]
    tid = r.json().get("tenant_id")
    assert tid
    return tid


def _fresh_ip():
    return f"198.51.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"


# ── 1) /pins contract ──────────────────────────────────────────────
class TestPinsEndpoint:
    def test_pins_200_and_schema(self, client):
        r = client.get(f"{BASE_URL}/api/public/checkins/{SLUG}/pins",
                       headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        for key in ("tenant", "pins", "count", "as_of", "window_days"):
            assert key in body, f"missing key {key} in {list(body)}"
        assert isinstance(body["pins"], list)
        assert body["count"] == len(body["pins"])
        assert body["window_days"] == 365
        assert body["tenant"].get("slug") == SLUG

    def test_pins_whitelist_only(self, client):
        r = client.get(f"{BASE_URL}/api/public/checkins/{SLUG}/pins",
                       headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 200
        body = r.json()
        for pin in body["pins"]:
            assert set(pin.keys()) == PIN_KEYS, f"unexpected keys: {pin}"
        raw = r.text
        for bad in FORBIDDEN_SUBSTRINGS:
            assert bad not in raw, f"PII/internal field leaked: {bad}"

    def test_pins_unknown_slug_404(self, client):
        r = client.get(
            f"{BASE_URL}/api/public/checkins/nonexistent-slug-f4/pins",
            headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 404, f"{r.status_code}: {r.text[:300]}"

    def test_pins_cors_open(self, client):
        r = client.get(f"{BASE_URL}/api/public/checkins/{SLUG}/pins",
                       headers={"X-Forwarded-For": _fresh_ip(),
                                "Origin": "https://example.com"})
        assert r.status_code == 200
        acao = r.headers.get("access-control-allow-origin")
        assert acao in ("*", "https://example.com"), r.headers

    def test_pins_rate_limit_429_on_61st(self, client):
        ip = _fresh_ip()
        codes = []
        for _ in range(61):
            resp = client.get(
                f"{BASE_URL}/api/public/checkins/{SLUG}/pins",
                headers={"X-Forwarded-For": ip})
            codes.append(resp.status_code)
            if resp.status_code == 429:
                break
        assert 429 in codes, f"no 429 within 61 requests: {codes[-5:]}"
        first_429 = codes.index(429)
        assert first_429 >= 55, (
            f"429 came too early (request #{first_429 + 1}); "
            "budget may be shared/pre-consumed")


# ── 2) map.html contract ───────────────────────────────────────────
class TestMapHtmlEndpoint:
    @pytest.fixture(scope="class")
    def map_resp(self, client):
        return client.get(
            f"{BASE_URL}/api/public/checkins/{SLUG}/map.html",
            headers={"X-Forwarded-For": _fresh_ip()})

    def test_map_html_200_content_type(self, map_resp):
        assert map_resp.status_code == 200, map_resp.text[:400]
        assert "text/html" in map_resp.headers.get("content-type", "")

    def test_map_html_has_leaflet_and_container(self, map_resp):
        body = map_resp.text
        assert "leaflet" in body.lower()
        assert "unpkg.com/leaflet" in body
        assert 'data-testid="widget-map-container"' in body
        assert "tile.openstreetmap.org" in body

    def test_map_html_jsonld_localbusiness(self, map_resp):
        body = map_resp.text
        m = re.search(
            r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
            body, re.S)
        assert m, "no ld+json script block"
        ld = json.loads(m.group(1))
        assert ld.get("@type") == "LocalBusiness", ld
        assert isinstance(ld.get("areaServed"), list)
        assert isinstance(ld.get("makesOffer"), list)

    def test_map_html_no_pii(self, map_resp, mongo, tenant_id):
        body = map_resp.text
        for bad in FORBIDDEN_SUBSTRINGS:
            assert bad not in body, f"leaked {bad}"
        # No exact timestamps (ISO date w/ day precision) in the payload.
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", body), \
            "exact timestamp present in map.html"
        # No approved-row customer names present in the HTML.
        names = set()
        for row in mongo.public_checkins.find(
                {"tenant_id": tenant_id, "state": "approved"},
                {"_id": 0, "customer_name": 1, "raw_address": 1}):
            if row.get("customer_name"):
                names.add(str(row["customer_name"]))
            addr = row.get("raw_address") or {}
            if isinstance(addr, dict) and addr.get("line1"):
                names.add(str(addr["line1"]))
        for n in names:
            assert n not in body, f"customer PII '{n}' leaked in map.html"

    def test_map_html_unknown_slug_404(self, client):
        r = client.get(
            f"{BASE_URL}/api/public/checkins/nope-f4-slug/map.html",
            headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 404, r.status_code


# ── 3) Auto-enqueue on job completion ──────────────────────────────
class TestAutoEnqueueOnCompletion:
    created_job_ids = []

    @pytest.fixture(scope="class", autouse=True)
    def cleanup(self, mongo, tenant_id):
        yield
        for jid in list(self.created_job_ids):
            mongo.jobs.delete_many({"id": jid})
            mongo.public_checkins.delete_many({"source_job_id": jid})
        mongo.tenants.update_one(
            {"id": tenant_id},
            {"$unset": {"settings.auto_enqueue_public_checkins": ""}})

    @pytest.fixture(scope="class")
    def geocoded_customer(self, mongo, tenant_id):
        cust = mongo.customers.find_one(
            {"tenant_id": tenant_id,
             "latitude": {"$ne": None},
             "longitude": {"$ne": None}},
            {"_id": 0, "id": 1, "name": 1, "latitude": 1, "longitude": 1})
        if not cust:
            pytest.fail("no geocoded customer in aquaterra tenant")
        # Avoid the multi-property 400 by preferring a single-property cust
        return cust

    def _create_and_complete(self, client, admin_headers, cust, title):
        payload = {"title": title, "customer_id": cust["id"],
                   "service_type": "TEST_F4 Service",
                   "status": "scheduled", "price": 10.0}
        r = client.post(f"{BASE_URL}/api/jobs", json=payload,
                        headers=admin_headers)
        assert r.status_code in (200, 201), f"create job: {r.status_code} {r.text[:400]}"
        jid = r.json().get("id")
        assert jid
        self.created_job_ids.append(jid)
        r2 = client.put(f"{BASE_URL}/api/jobs/{jid}",
                        json={"status": "completed"},
                        headers=admin_headers)
        assert r2.status_code == 200, f"complete job: {r2.status_code} {r2.text[:400]}"
        return jid

    def test_auto_enqueue_row_created(self, client, admin_headers,
                                      geocoded_customer, mongo, tenant_id):
        jid = self._create_and_complete(
            client, admin_headers, geocoded_customer,
            "TEST_F4 auto enqueue job")
        r = client.get(
            f"{BASE_URL}/api/admin/moderation/public-checkins"
            f"?state=pending_review&limit=200",
            headers=admin_headers)
        assert r.status_code == 200, r.text[:300]
        items = r.json()["items"]
        row = next((i for i in items if i.get("source_job_id") == jid), None)
        assert row, ("no pending_review row for completed job "
                     f"{jid}; queue size={len(items)}")
        assert row.get("source") == "auto", row.get("source")
        assert row.get("state") == "pending_review"
        lat_raw = float(geocoded_customer["latitude"])
        lng_raw = float(geocoded_customer["longitude"])
        assert row.get("lat_public") is not None
        assert row.get("lng_public") is not None
        assert abs(float(row["lat_public"]) - lat_raw) <= 0.0010001, row
        assert abs(float(row["lng_public"]) - lng_raw) <= 0.0010001, row
        assert float(row["lat_public"]) != lat_raw, "coords not jittered"
        assert row.get("completed_at_month_year"), row
        assert "_id" not in row

    def test_idempotent_no_duplicate(self, client, admin_headers, mongo,
                                     tenant_id):
        jid = self.created_job_ids[0]
        # re-complete the same job
        r = client.put(f"{BASE_URL}/api/jobs/{jid}",
                       json={"status": "completed"}, headers=admin_headers)
        assert r.status_code == 200, r.text[:300]
        cnt = mongo.public_checkins.count_documents(
            {"tenant_id": tenant_id, "source_job_id": jid})
        assert cnt == 1, f"expected 1 row for job {jid}, got {cnt}"

    def test_tenant_setting_off_blocks_enqueue(
            self, client, admin_headers, geocoded_customer, mongo, tenant_id):
        mongo.tenants.update_one(
            {"id": tenant_id},
            {"$set": {"settings.auto_enqueue_public_checkins": False}})
        try:
            jid = self._create_and_complete(
                client, admin_headers, geocoded_customer,
                "TEST_F4 setting off job")
            cnt = mongo.public_checkins.count_documents(
                {"tenant_id": tenant_id, "source_job_id": jid})
            assert cnt == 0, (
                "row enqueued despite auto_enqueue_public_checkins=false")
        finally:
            mongo.tenants.update_one(
                {"id": tenant_id},
                {"$unset": {"settings.auto_enqueue_public_checkins": ""}})


# ── 4) Moderation list source discriminator ────────────────────────
class TestModerationSourceField:
    def test_demo_rows_have_source(self, client, admin_headers):
        r = client.get(
            f"{BASE_URL}/api/admin/moderation/public-checkins"
            "?state=pending_review&limit=200",
            headers=admin_headers)
        assert r.status_code == 200, r.text[:300]
        items = r.json()["items"]
        assert items, "moderation queue empty"
        by_name = {i.get("service_name"): i for i in items}
        auto = by_name.get("Weekly Pool Cleaning (F4 demo · auto)")
        tech = by_name.get("Palm Tree Trim (F4 demo · tech)")
        assert auto, f"demo auto row missing; names={list(by_name)[:10]}"
        assert tech, f"demo tech row missing; names={list(by_name)[:10]}"
        assert auto.get("source") == "auto", auto.get("source")
        assert tech.get("source") == "tech", tech.get("source")

    def test_list_requires_auth(self, client):
        r = client.get(f"{BASE_URL}/api/admin/moderation/public-checkins")
        assert r.status_code in (401, 403), r.status_code


# ── 5) Regression: existing widget surface ─────────────────────────
class TestWidgetRegression:
    def test_widget_js_200(self, client):
        r = client.get(f"{BASE_URL}/api/widget.js",
                       headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert "javascript" in r.headers.get("content-type", "").lower()

    def test_widget_preview_200(self, client):
        r = client.get(f"{BASE_URL}/api/widget/preview/{SLUG}",
                       headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"

    def test_widget_feed_200(self, client):
        r = client.get(f"{BASE_URL}/api/public/checkins/{SLUG}/feed",
                       headers={"X-Forwarded-For": _fresh_ip()})
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
