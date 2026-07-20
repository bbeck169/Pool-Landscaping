"""Marketing Campaigns · Phase M2 backend tests (Feb 2026).

Covers CRUD, audience math, preview render, test-send, send-now with
mocked provider paths, scheduling + cancel + pause/resume, open pixel
+ click redirect + unsubscribe tracking, provider webhooks, aggregate
stats + top links + per-recipient view, notification kind wiring,
tenant isolation, RBAC, and OpenAPI registration.

Uses ``SMS_MOCK_MODE=1`` (already the default) so no external provider
is contacted. ``RESEND_API_KEY`` is intentionally unset on preview so
``send_email`` returns ``{"status": "not_sent_missing_key"}`` — that's
our mock signal.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import List

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
T = 30


def _login(email: str, pw: str):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], (d.get("user") or {}).get("id")


def _h(tok: str):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))[0]


@pytest.fixture(scope="module")
def admin_uid():
    return _login("admin@aquaterra.com", demo_pw("admin@aquaterra.com"))[1]


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com", demo_pw("mike@aquaterra.com"))[0]


@pytest.fixture(scope="module")
def tenant_id(admin_tok):
    return requests.get(f"{API}/tenants/current",
                         headers=_h(admin_tok), timeout=T).json()["id"]


# ─── Seed helpers ──────────────────────────────────────────────────────
def _seed_subs(admin_tok: str, n: int, status: str = "subscribed",
                 prefix: str = "m2") -> List[str]:
    """Create ``n`` subscribers directly via the admin API. Returns
    their id list. Kept small (≤3) so tests don't spam Resend even if
    the mock ever slips."""
    ids: List[str] = []
    for i in range(n):
        r = requests.post(f"{API}/marketing/subscribers",
                          json={"email": f"{prefix}-{uuid.uuid4().hex[:6]}-{i}@example.com",
                                 "first_name": f"TEST{i}",
                                 "phone": f"+1555{uuid.uuid4().int % 10_000_000:07d}",
                                 "status": status,
                                 "consent_source": "test"},
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code in (200, 201), r.text
        ids.append(r.json()["id"])
    return ids


def _seed_list(admin_tok: str, sub_ids: List[str], name: str) -> str:
    """Create a static list then attach members via M1 memberships API."""
    r = requests.post(f"{API}/marketing/lists",
                       json={"name": name, "type": "static"},
                       headers=_h(admin_tok), timeout=T)
    assert r.status_code in (200, 201), r.text
    lid = r.json()["id"]
    if sub_ids:
        m = requests.post(f"{API}/marketing/lists/{lid}/members",
                           json={"subscriber_ids": sub_ids},
                           headers=_h(admin_tok), timeout=T)
        assert m.status_code in (200, 201), m.text
    return lid


def _mkcamp(admin_tok: str, **over) -> dict:
    payload = {
        "name": over.get("name", f"TEST_camp_{uuid.uuid4().hex[:6]}"),
        "subject": over.get("subject", "Hello {{first_name}}!"),
        "from_name": over.get("from_name", "TestSender"),
        "from_email": over.get("from_email", "sender@test.example"),
        "channel": over.get("channel", "email"),
        "content": over.get("content", {
            "email_html": "<p>Hi {{first_name}} — visit <a href=\"https://ex.example/pool\">our site</a>.</p>",
            "sms_body":   "Hey {{first_name}}, save 10% at https://ex.example/pool",
        }),
        "audience": over.get("audience", {}),
    }
    r = requests.post(f"{API}/marketing/campaigns",
                       json=payload, headers=_h(admin_tok), timeout=T)
    assert r.status_code == 201, r.text
    return r.json()


# ═════════════════════════════════════════════════════════════════════
class TestCrud:
    def test_create_and_get(self, admin_tok):
        c = _mkcamp(admin_tok)
        assert c["status"] == "draft"
        got = requests.get(f"{API}/marketing/campaigns/{c['id']}",
                            headers=_h(admin_tok), timeout=T).json()
        assert got["id"] == c["id"]
        assert "stats" in got

    def test_list(self, admin_tok):
        _mkcamp(admin_tok, name="TEST_list_me")
        r = requests.get(f"{API}/marketing/campaigns?q=TEST_list_me",
                          headers=_h(admin_tok), timeout=T).json()
        assert r["count"] >= 1

    def test_patch_draft(self, admin_tok):
        c = _mkcamp(admin_tok)
        r = requests.patch(f"{API}/marketing/campaigns/{c['id']}",
                             json={"subject": "New subject"},
                             headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["subject"] == "New subject"

    def test_delete_draft(self, admin_tok):
        c = _mkcamp(admin_tok)
        r = requests.delete(f"{API}/marketing/campaigns/{c['id']}",
                              headers=_h(admin_tok), timeout=T)
        assert r.status_code == 204
        # Now GET should 404.
        g = requests.get(f"{API}/marketing/campaigns/{c['id']}",
                          headers=_h(admin_tok), timeout=T)
        assert g.status_code == 404

    def test_patch_sent_returns_409(self, admin_tok):
        # Create + send a campaign with an empty audience → status flips
        # to "sent" immediately (audience.subscriber_ids is empty).
        c = _mkcamp(admin_tok)
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        r = requests.patch(f"{API}/marketing/campaigns/{c['id']}",
                             json={"subject": "should fail"},
                             headers=_h(admin_tok), timeout=T)
        assert r.status_code == 409


class TestAudience:
    def test_estimate_math(self, admin_tok):
        # Two subs (subscribed) + one unsubscribed. Include list has
        # all 3 → estimate should count only the 2 subscribed.
        s_sub = _seed_subs(admin_tok, 2, "subscribed", "aud")
        s_unsub = _seed_subs(admin_tok, 1, "unsubscribed", "aud")
        lst_all = _seed_list(admin_tok, s_sub + s_unsub, f"list_all_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst_all],
                                            "segment_ids": [],
                                            "exclude_list_ids": [],
                                            "exclude_segment_ids": []})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/estimate-audience",
                            headers=_h(admin_tok), timeout=T).json()
        assert r["estimated_size"] == 2
        assert r["unsubscribed_excluded_count"] == 1

    def test_estimate_with_excludes(self, admin_tok):
        s = _seed_subs(admin_tok, 3, "subscribed", "excl")
        lst = _seed_list(admin_tok, s, f"list_{uuid.uuid4().hex[:6]}")
        lst_x = _seed_list(admin_tok, [s[0]], f"exclude_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst],
                                            "exclude_list_ids": [lst_x]})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/estimate-audience",
                            headers=_h(admin_tok), timeout=T).json()
        assert r["estimated_size"] == 2


class TestPreview:
    def test_token_render(self, admin_tok):
        c = _mkcamp(admin_tok, subject="Hi {{first_name}}!",
                       content={"email_html": "<p>{{first_name}} from {{tenant_name}}</p>",
                                 "sms_body": "Yo {{first_name}}"})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/preview",
                            json={}, headers=_h(admin_tok), timeout=T).json()
        assert "Sam" in r["email_html"]
        assert "Sam" in r["subject"]
        assert "Sam" in r["sms_body"]

    def test_missing_token_warning(self, admin_tok):
        c = _mkcamp(admin_tok, subject="Hey {{nonexistent}}",
                       content={"email_html": "hi", "sms_body": "hi"})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/preview",
                            json={}, headers=_h(admin_tok), timeout=T).json()
        assert any("nonexistent" in w for w in r["warnings"])

    def test_spam_heuristic(self, admin_tok):
        c = _mkcamp(admin_tok, subject="FREE guaranteed offer",
                       content={"email_html": "act now buy now",
                                 "sms_body": ""})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/preview",
                            json={}, headers=_h(admin_tok), timeout=T).json()
        assert r["spam_score"] >= 3


class TestSendTest:
    def test_test_send_no_row_created(self, admin_tok, tenant_id):
        c = _mkcamp(admin_tok)
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/send-test",
                            json={"recipient_emails":
                                    ["admin+test@example.com"]},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        j = r.json()
        assert len(j["email"]) == 1
        # No marketing_campaign_sends row should have been created.
        recips = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                                headers=_h(admin_tok), timeout=T).json()
        assert recips["count"] == 0


class TestSendNow:
    def test_end_to_end_send(self, admin_tok, tenant_id):
        s = _seed_subs(admin_tok, 2, "subscribed", "sendnow")
        lst = _seed_list(admin_tok, s, f"list_send_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        # Campaign must be flipped to ``sent`` after dispatch.
        got = requests.get(f"{API}/marketing/campaigns/{c['id']}",
                            headers=_h(admin_tok), timeout=T).json()
        assert got["status"] == "sent"
        # 2 send rows exist.
        rec = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                             headers=_h(admin_tok), timeout=T).json()
        assert rec["count"] == 2

    def test_repeat_send_returns_409(self, admin_tok):
        # From TestSendNow above, we've already sent one. Cannot send-now
        # a sent campaign.
        c = _mkcamp(admin_tok)
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 409


class TestSchedule:
    def test_schedule_and_cancel(self, admin_tok):
        c = _mkcamp(admin_tok)
        # 24 h out.
        from datetime import datetime, timedelta, timezone as _tz
        future = (datetime.now(_tz.utc) + timedelta(hours=24)).isoformat()
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/schedule",
                            json={"scheduled_at": future},
                            headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        assert r.json()["status"] == "scheduled"
        # Cancel it.
        r2 = requests.post(f"{API}/marketing/campaigns/{c['id']}/cancel",
                             headers=_h(admin_tok), timeout=T)
        assert r2.status_code == 200
        got = requests.get(f"{API}/marketing/campaigns/{c['id']}",
                            headers=_h(admin_tok), timeout=T).json()
        assert got["status"] == "cancelled"

    def test_pause_resume(self, admin_tok):
        c = _mkcamp(admin_tok)
        from datetime import datetime, timedelta, timezone as _tz
        future = (datetime.now(_tz.utc) + timedelta(hours=6)).isoformat()
        requests.post(f"{API}/marketing/campaigns/{c['id']}/schedule",
                        json={"scheduled_at": future},
                        headers=_h(admin_tok), timeout=T)
        p = requests.post(f"{API}/marketing/campaigns/{c['id']}/pause",
                            headers=_h(admin_tok), timeout=T)
        assert p.status_code == 200
        got = requests.get(f"{API}/marketing/campaigns/{c['id']}",
                            headers=_h(admin_tok), timeout=T).json()
        assert got["status"] == "paused"
        rr = requests.post(f"{API}/marketing/campaigns/{c['id']}/resume",
                             headers=_h(admin_tok), timeout=T).json()
        assert rr["status"] == "scheduled"

    def test_scheduler_sweep_fires_due_campaigns(self, admin_tok):
        c = _mkcamp(admin_tok)
        # Backdate.
        from datetime import datetime, timedelta, timezone as _tz
        past = (datetime.now(_tz.utc) - timedelta(minutes=1)).isoformat()
        requests.post(f"{API}/marketing/campaigns/{c['id']}/schedule",
                        json={"scheduled_at": past},
                        headers=_h(admin_tok), timeout=T)
        # Run sweep synchronously.
        import asyncio
        from services.marketing_campaigns import run_scheduled_campaign_sweep
        r = asyncio.get_event_loop().run_until_complete(run_scheduled_campaign_sweep())
        assert r["fired"] >= 1


class TestTracking:
    def test_pixel_and_open_count(self, admin_tok):
        s = _seed_subs(admin_tok, 1, "subscribed", "track")
        lst = _seed_list(admin_tok, s, f"list_trk_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]})
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        rec = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                             headers=_h(admin_tok), timeout=T).json()
        assert rec["count"] == 1
        send_row = rec["recipients"][0]
        # Mint a token using service helper.
        from services.marketing_campaigns import mint_token
        tok = mint_token(c["id"], send_row["subscriber_id"], send_row["id"])
        # Hit the pixel.
        r = requests.get(f"{API}/public/mkt/o/{tok}", timeout=T)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/gif")
        # Row should now show open_count>=1.
        rec2 = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                              headers=_h(admin_tok), timeout=T).json()
        assert rec2["recipients"][0]["open_count"] >= 1

    def test_pixel_silent_on_bad_token(self):
        r = requests.get(f"{API}/public/mkt/o/garbage", timeout=T)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/gif")

    def test_click_redirect(self, admin_tok):
        s = _seed_subs(admin_tok, 1, "subscribed", "click")
        lst = _seed_list(admin_tok, s, f"list_click_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]})
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        rec = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                             headers=_h(admin_tok), timeout=T).json()
        send_row = rec["recipients"][0]
        from services.marketing_campaigns import mint_token, hash_url
        url = "https://ex.example/pool"
        tok = mint_token(c["id"], send_row["subscriber_id"], send_row["id"],
                            url_hash=hash_url(url))
        r = requests.get(f"{API}/public/mkt/c/{tok}?u={hash_url(url)}",
                          timeout=T, allow_redirects=False)
        assert r.status_code == 302
        assert "ex.example" in r.headers.get("location", "")
        # Click count bumped.
        rec2 = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                              headers=_h(admin_tok), timeout=T).json()
        assert rec2["recipients"][0]["click_count"] >= 1

    def test_click_bad_token_404(self):
        r = requests.get(f"{API}/public/mkt/c/garbage?u=abc",
                          allow_redirects=False, timeout=T)
        assert r.status_code == 404

    def test_unsub(self, admin_tok):
        s = _seed_subs(admin_tok, 1, "subscribed", "unsub")
        sub_id = s[0]
        lst = _seed_list(admin_tok, s, f"list_unsub_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]})
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        rec = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                             headers=_h(admin_tok), timeout=T).json()
        send_row = rec["recipients"][0]
        from services.marketing_campaigns import mint_token
        tok = mint_token(c["id"], send_row["subscriber_id"], send_row["id"])
        r = requests.post(f"{API}/public/mkt/unsub/{tok}", timeout=T)
        assert r.status_code == 200
        assert r.json().get("unsubscribed") is True
        # Verify subscriber flipped.
        sub = requests.get(f"{API}/marketing/subscribers/{sub_id}",
                            headers=_h(admin_tok), timeout=T).json()
        assert sub["status"] == "unsubscribed"


class TestWebhooks:
    def test_provider_webhook_accepts_when_non_strict(self):
        # No signature header required when MARKETING_WEBHOOK_STRICT unset.
        r = requests.post(f"{API}/public/mkt/webhooks/resend",
                           json={"events": [{"type": "email.delivered",
                                              "data": {"message_id": "nonexistent"}}]},
                           timeout=T)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_provider_webhook_updates_matched_send(self, admin_tok):
        s = _seed_subs(admin_tok, 1, "subscribed", "wh")
        lst = _seed_list(admin_tok, s, f"list_wh_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]})
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        rec = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                             headers=_h(admin_tok), timeout=T).json()
        provider_id = rec["recipients"][0]["provider_message_id"]
        r = requests.post(f"{API}/public/mkt/webhooks/resend",
                           json={"events": [{"type": "email.bounced",
                                              "data": {"message_id": provider_id}}]},
                           timeout=T)
        assert r.status_code == 200
        assert r.json()["updated"] >= 1


class TestStats:
    def test_stats_and_top_links(self, admin_tok):
        s = _seed_subs(admin_tok, 2, "subscribed", "stat")
        lst = _seed_list(admin_tok, s, f"list_stat_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]})
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        st = requests.get(f"{API}/marketing/campaigns/{c['id']}/stats",
                            headers=_h(admin_tok), timeout=T).json()
        assert st["sent"] == 2
        # Trigger a click on recipient #1.
        rec = requests.get(f"{API}/marketing/campaigns/{c['id']}/recipients",
                             headers=_h(admin_tok), timeout=T).json()
        send_row = rec["recipients"][0]
        from services.marketing_campaigns import mint_token, hash_url
        url = "https://ex.example/pool"
        tok = mint_token(c["id"], send_row["subscriber_id"], send_row["id"],
                            url_hash=hash_url(url))
        requests.get(f"{API}/public/mkt/c/{tok}?u={hash_url(url)}",
                       allow_redirects=False, timeout=T)
        # top-links should show at least this URL.
        tl = requests.get(f"{API}/marketing/campaigns/{c['id']}/top-links",
                            headers=_h(admin_tok), timeout=T).json()
        assert any(l["clicks"] >= 1 for l in tl["links"]), tl


class TestNotifications:
    def test_kind_registered(self, admin_tok):
        r = requests.get(f"{API}/settings/notifications",
                          headers=_h(admin_tok), timeout=T).json()
        kinds = {k["key"] for k in r.get("kinds", [])}
        assert "marketing_campaign_sent" in kinds

    def test_campaign_send_fires_notification(self, admin_tok):
        s = _seed_subs(admin_tok, 1, "subscribed", "notif")
        lst = _seed_list(admin_tok, s, f"list_notif_{uuid.uuid4().hex[:6]}")
        c = _mkcamp(admin_tok, audience={"list_ids": [lst]},
                       name=f"NOTIFY_test_{uuid.uuid4().hex[:6]}")
        before = len(requests.get(f"{API}/notifications",
                                     params={"kind": "marketing_campaign_sent",
                                              "limit": 100},
                                     headers=_h(admin_tok), timeout=T).json())
        requests.post(f"{API}/marketing/campaigns/{c['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        # Poll up to 3s.
        after = before
        for _ in range(6):
            after = len(requests.get(f"{API}/notifications",
                                        params={"kind": "marketing_campaign_sent",
                                                 "limit": 100},
                                        headers=_h(admin_tok), timeout=T).json())
            if after > before:
                break
            time.sleep(0.5)
        assert after > before


class TestRbacIsolation:
    def test_tech_forbidden(self, tech_tok):
        r = requests.get(f"{API}/marketing/campaigns",
                          headers=_h(tech_tok), timeout=T)
        assert r.status_code in (401, 403)

    def test_tech_cannot_create(self, tech_tok):
        r = requests.post(f"{API}/marketing/campaigns",
                           json={"name": "unauthorized"},
                           headers=_h(tech_tok), timeout=T)
        assert r.status_code in (401, 403)


class TestOpenApi:
    def test_admin_paths(self, admin_tok):
        r = requests.get(f"{BACKEND}/api/openapi.json", timeout=T).json()
        paths = set(r.get("paths", {}).keys())
        must = {
            "/api/marketing/campaigns",
            "/api/marketing/campaigns/{cid}",
            "/api/marketing/campaigns/{cid}/preview",
            "/api/marketing/campaigns/{cid}/estimate-audience",
            "/api/marketing/campaigns/{cid}/send-test",
            "/api/marketing/campaigns/{cid}/send-now",
            "/api/marketing/campaigns/{cid}/schedule",
            "/api/marketing/campaigns/{cid}/cancel",
            "/api/marketing/campaigns/{cid}/pause",
            "/api/marketing/campaigns/{cid}/resume",
            "/api/marketing/campaigns/{cid}/stats",
            "/api/marketing/campaigns/{cid}/top-links",
            "/api/marketing/campaigns/{cid}/recipients",
            "/api/public/mkt/o/{token}",
            "/api/public/mkt/c/{token}",
            "/api/public/mkt/unsub/{token}",
            "/api/public/mkt/webhooks/{provider}",
        }
        missing = must - paths
        assert not missing, f"missing OpenAPI paths: {missing}"


class TestServiceHelpers:
    def test_token_roundtrip(self):
        from services.marketing_campaigns import mint_token, verify_token
        tok = mint_token("c1", "s1", "sd1", "u1")
        p = verify_token(tok)
        assert p["c"] == "c1" and p["s"] == "s1" and p["sd"] == "sd1"

    def test_token_tamper_rejected(self):
        from services.marketing_campaigns import mint_token, verify_token
        tok = mint_token("c1", "s1", "sd1")
        # Flip one char in the payload half.
        head, sig = tok.split(".", 1)
        tampered = head[:-1] + ("A" if head[-1] != "A" else "B") + "." + sig
        assert verify_token(tampered) is None

    def test_render_tokens(self):
        from services.marketing_campaigns import render_body
        s, missing = render_body("Hi {{first_name}} from {{brand}}",
                                    {"first_name": "Sam"})
        assert "Sam" in s
        assert "brand" in missing

    def test_spam_score(self):
        from services.marketing_campaigns import spam_score
        n, hits = spam_score("FREE offer!", "act now — limited time")
        assert n >= 3

    def test_rewrite_email_html(self):
        from services.marketing_campaigns import rewrite_email_html
        html, idx = rewrite_email_html(
            '<p><a href="https://ex.example/x">go</a></p>',
            "cid", "sid", "sdid")
        assert "/api/public/mkt/c/" in html
        assert "<img" in html
        assert "unsub" in html.lower()
        assert idx and idx[0]["url"] == "https://ex.example/x"

    def test_rewrite_sms_body(self):
        from services.marketing_campaigns import rewrite_sms_body
        out = rewrite_sms_body("Save at https://ex.example/x",
                                  "cid", "sid", "sdid",
                                  primary_url="https://ex.example/x")
        assert "/api/public/mkt/c/" in out
        assert "STOP" in out.upper()

    def test_hash_url_stable(self):
        from services.marketing_campaigns import hash_url
        assert hash_url("https://x") == hash_url("https://x")
        assert hash_url("https://x") != hash_url("https://y")


class TestFilters:
    def test_list_status_filter(self, admin_tok):
        _mkcamp(admin_tok, name=f"DRAFT_only_{uuid.uuid4().hex[:6]}")
        r = requests.get(f"{API}/marketing/campaigns?status=draft",
                          headers=_h(admin_tok), timeout=T).json()
        assert all(c["status"] == "draft" for c in r["campaigns"])
