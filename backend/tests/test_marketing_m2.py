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



# ═════════════════════════════════════════════════════════════════════
# A/B variants + /timeline endpoint (Feb-2026 M2 delta)
# ═════════════════════════════════════════════════════════════════════

class TestAbVariants:
    def test_variant_selection_deterministic(self):
        """Same (campaign_id, subscriber_id) must always resolve to the
        same variant — regardless of how many times we call the selector.
        Guarantees dry-runs, resumes, and stats recompute all agree."""
        from services.marketing_campaigns import _select_variant
        camp = {
            "id": "camp-abc-123",
            "ab_test": {"enabled": True, "variants": [
                {"id": "A", "subject": "Take A", "weight": 1},
                {"id": "B", "subject": "Take B", "weight": 1},
            ]},
        }
        picks = [_select_variant(camp, "sub-1") for _ in range(20)]
        assert len(set(v["id"] for v in picks)) == 1, (
            f"variant selection drifted for the same subscriber: {picks}"
        )

    def test_variant_selection_splits_across_subscribers(self):
        """Across a modest cohort, both A and B must get hit at least
        once — otherwise the selector is stuck on a single bucket."""
        from services.marketing_campaigns import _select_variant
        camp = {
            "id": "camp-split-xyz",
            "ab_test": {"enabled": True, "variants": [
                {"id": "A", "weight": 1},
                {"id": "B", "weight": 1},
            ]},
        }
        picks = {_select_variant(camp, f"sub-{i}")["id"] for i in range(50)}
        assert picks == {"A", "B"}, (
            f"expected both variants to appear in a 50-subscriber cohort; got {picks}"
        )

    def test_variant_selection_respects_weights(self):
        """A weight of 10:1 should hand ≥5× more traffic to A than B."""
        from services.marketing_campaigns import _select_variant
        camp = {
            "id": "camp-weight-test",
            "ab_test": {"enabled": True, "variants": [
                {"id": "A", "weight": 10},
                {"id": "B", "weight": 1},
            ]},
        }
        picks = [_select_variant(camp, f"sub-{i}")["id"] for i in range(200)]
        a_count = picks.count("A")
        b_count = picks.count("B")
        assert a_count > 5 * b_count, (
            f"weighted split A:B should be ≥5:1; got {a_count}:{b_count}"
        )

    def test_variant_disabled_returns_none(self):
        from services.marketing_campaigns import _select_variant
        # ab_test missing → no variant.
        assert _select_variant({"id": "x"}, "sub-1") is None
        # enabled=False → no variant.
        assert _select_variant({"id": "x", "ab_test": {"enabled": False,
            "variants": [{"id": "A"}]}}, "sub-1") is None
        # enabled=True but no variants → no variant.
        assert _select_variant({"id": "x", "ab_test": {"enabled": True,
            "variants": []}}, "sub-1") is None

    def test_ab_send_stamps_variant_id_on_sends(self, admin_tok, tenant_id):
        """End-to-end: A/B campaign sent to a small cohort → every
        marketing_campaign_sends row must carry a variant_id ∈ {A, B}."""
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        db_ = client[env["DB_NAME"]]
        try:
            sub_ids = _seed_subs(admin_tok, 4, prefix="m2ab")
            list_id = _seed_list(admin_tok, sub_ids, name=f"TEST_ab_list_{uuid.uuid4().hex[:6]}")
            camp = _mkcamp(admin_tok,
                            name=f"TEST_ab_send_{uuid.uuid4().hex[:6]}",
                            audience={"list_ids": [list_id]})
            # Enable A/B on the draft.
            r = requests.patch(f"{API}/marketing/campaigns/{camp['id']}",
                                 json={"ab_test": {"enabled": True, "variants": [
                                     {"id": "A", "subject": "Subject A", "weight": 1},
                                     {"id": "B", "subject": "Subject B", "weight": 1},
                                 ]}},
                                 headers=_h(admin_tok), timeout=T)
            assert r.status_code == 200, r.text
            # Send.
            requests.post(f"{API}/marketing/campaigns/{camp['id']}/send-now",
                            headers=_h(admin_tok), timeout=T)
            # Every send row must carry a variant_id.
            rows = list(db_.marketing_campaign_sends.find(
                {"tenant_id": tenant_id, "campaign_id": camp["id"]},
                {"_id": 0, "variant_id": 1},
            ))
            assert rows, "no send rows produced for A/B campaign"
            variant_ids = {r.get("variant_id") for r in rows}
            assert None not in variant_ids, (
                f"at least one send row missing variant_id: {rows}"
            )
            assert variant_ids <= {"A", "B"}, (
                f"unexpected variant ids: {variant_ids}"
            )
        finally:
            client.close()

    def test_ab_stats_include_per_variant_counters(self, admin_tok, tenant_id):
        """GET /stats on an A/B campaign must surface a ``variants``
        block with per-variant sent/opened/clicked counters."""
        sub_ids = _seed_subs(admin_tok, 2, prefix="m2abstats")
        list_id = _seed_list(admin_tok, sub_ids, name=f"TEST_ab_stats_{uuid.uuid4().hex[:6]}")
        camp = _mkcamp(admin_tok,
                        name=f"TEST_ab_stats_{uuid.uuid4().hex[:6]}",
                        audience={"list_ids": [list_id]})
        requests.patch(f"{API}/marketing/campaigns/{camp['id']}",
                         json={"ab_test": {"enabled": True, "variants": [
                             {"id": "A", "subject": "A", "weight": 1},
                             {"id": "B", "subject": "B", "weight": 1},
                         ]}},
                         headers=_h(admin_tok), timeout=T)
        requests.post(f"{API}/marketing/campaigns/{camp['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        r = requests.get(f"{API}/marketing/campaigns/{camp['id']}/stats",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        data = r.json()
        assert "variants" in data, (
            f"expected 'variants' block on A/B stats; got keys={list(data.keys())}"
        )
        # Each variant entry must carry the canonical counter shape.
        for vid, entry in (data["variants"] or {}).items():
            assert vid in ("A", "B"), vid
            for k in ("sent", "opened", "clicked", "failed",
                       "open_rate_pct", "click_rate_pct"):
                assert k in entry, (
                    f"variant {vid!r} missing '{k}' in stats: {entry}"
                )


# ═════════════════════════════════════════════════════════════════════
class TestTimeline:
    def test_timeline_404_for_unknown_campaign(self, admin_tok):
        r = requests.get(f"{API}/marketing/campaigns/does-not-exist/timeline",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 404

    def test_timeline_returns_send_events_sorted_desc(self, admin_tok):
        sub_ids = _seed_subs(admin_tok, 2, prefix="m2tl")
        list_id = _seed_list(admin_tok, sub_ids, name=f"TEST_tl_{uuid.uuid4().hex[:6]}")
        camp = _mkcamp(admin_tok,
                        name=f"TEST_tl_{uuid.uuid4().hex[:6]}",
                        audience={"list_ids": [list_id]})
        requests.post(f"{API}/marketing/campaigns/{camp['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        r = requests.get(f"{API}/marketing/campaigns/{camp['id']}/timeline",
                          headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 2, (
            f"expected ≥2 send events for a 2-subscriber campaign; got {data}"
        )
        # Every event has the canonical shape and a plausible type.
        allowed = {"send", "bounce", "open", "click", "click_event",
                    "unsubscribe"}
        for e in data["events"]:
            assert "at" in e and "type" in e
            assert e["type"] in allowed, e["type"]
        # Sorted DESC by ``at``.
        ats = [e["at"] for e in data["events"] if e.get("at")]
        assert ats == sorted(ats, reverse=True), "timeline not sorted DESC"

    def test_timeline_respects_limit_query_param(self, admin_tok):
        sub_ids = _seed_subs(admin_tok, 2, prefix="m2tllim")
        list_id = _seed_list(admin_tok, sub_ids, name=f"TEST_tl_lim_{uuid.uuid4().hex[:6]}")
        camp = _mkcamp(admin_tok,
                        name=f"TEST_tl_lim_{uuid.uuid4().hex[:6]}",
                        audience={"list_ids": [list_id]})
        requests.post(f"{API}/marketing/campaigns/{camp['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        r = requests.get(
            f"{API}/marketing/campaigns/{camp['id']}/timeline?limit=1",
            headers=_h(admin_tok), timeout=T,
        )
        assert r.status_code == 200
        assert r.json()["count"] <= 1


# ═════════════════════════════════════════════════════════════════════
# Tester feedback — M2 backend fixes (Feb-2026 round 2)
# ═════════════════════════════════════════════════════════════════════

class TestRenderBraceCompat:
    """Preview must resolve BOTH single- and double-brace tokens so seed
    data written with ``{first_name}`` no longer silently leaks through
    into the sent email. Missing tokens in either shape must surface as
    warnings — the tester found the empty-warnings array was the real
    UX bug."""

    def test_single_and_double_brace_both_resolve(self):
        from services.marketing_campaigns import render_body
        ctx = {"first_name": "Sara", "last_name": "Garcia"}
        out_dbl, missing_dbl = render_body("Hello {{first_name}} {{last_name}}!", ctx)
        out_sgl, missing_sgl = render_body("Hello {first_name} {last_name}!", ctx)
        assert out_dbl == "Hello Sara Garcia!", out_dbl
        assert out_sgl == "Hello Sara Garcia!", out_sgl
        assert missing_dbl == []
        assert missing_sgl == []

    def test_unknown_token_warns_double_brace(self):
        from services.marketing_campaigns import render_body
        _, missing = render_body("Hi {{first_name}}, {{bogus_field}} here", {"first_name": "S"})
        assert "bogus_field" in missing, missing

    def test_unknown_token_warns_single_brace(self):
        from services.marketing_campaigns import render_body
        _, missing = render_body("Hi {first_name}, {mystery} here", {"first_name": "S"})
        assert "mystery" in missing, missing

    def test_preview_endpoint_surfaces_single_brace_warnings(self, admin_tok):
        """End-to-end: a campaign whose stored subject uses ``{name_typo}``
        must render a warning in the /preview response instead of
        returning warnings=[] as before."""
        c = _mkcamp(admin_tok,
                     name=f"TEST_brace_{uuid.uuid4().hex[:6]}",
                     subject="Hi {first_name}, greetings {name_typo}",
                     content={"email_html": "<p>Hi {first_name}!</p>",
                                "sms_body": "Hi {first_name}"})
        r = requests.post(f"{API}/marketing/campaigns/{c['id']}/preview",
                            json={}, headers=_h(admin_tok), timeout=T)
        assert r.status_code == 200, r.text
        data = r.json()
        # {first_name} must resolve to the preview subscriber's name (Sam).
        assert "Sam" in data["subject"], data["subject"]
        # {name_typo} must NOT be silently dropped — expect a warning.
        joined = " | ".join(data["warnings"] or [])
        assert "name_typo" in joined, (
            f"expected 'name_typo' warning; got warnings={data['warnings']!r}"
        )


class TestStatsMonotonicity:
    """The tester saw ``sent`` drop from 4 → 3 after an open event
    because the aggregator counted ``status='sent'`` literally. Fix:
    ``sent`` counts every send row past dispatch (sent, delivered,
    opened, clicked, bounced, complained, unsubscribed, failed) so the
    number never decrements after send-now completes."""

    def _open_pixel(self, campaign_id, subscriber_id, send_id):
        from services.marketing_campaigns import mint_token
        tok = mint_token(campaign_id, subscriber_id, send_id)
        r = requests.get(f"{API}/public/mkt/o/{tok}", timeout=T)
        return r.status_code

    def test_sent_does_not_decrease_after_open(self, admin_tok, tenant_id):
        sub_ids = _seed_subs(admin_tok, 2, prefix="m2mono")
        list_id = _seed_list(admin_tok, sub_ids,
                              name=f"TEST_mono_{uuid.uuid4().hex[:6]}")
        camp = _mkcamp(admin_tok,
                        name=f"TEST_mono_{uuid.uuid4().hex[:6]}",
                        audience={"list_ids": [list_id]})
        requests.post(f"{API}/marketing/campaigns/{camp['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        stats_before = requests.get(
            f"{API}/marketing/campaigns/{camp['id']}/stats",
            headers=_h(admin_tok), timeout=T,
        ).json()
        sent_before = stats_before["sent"]
        assert sent_before >= 2, (
            f"expected ≥2 sends for a 2-subscriber campaign; got {sent_before}"
        )
        # Pull the first send row and fire the open pixel for it.
        recips = requests.get(
            f"{API}/marketing/campaigns/{camp['id']}/recipients",
            headers=_h(admin_tok), timeout=T,
        ).json()["recipients"]
        assert recips, "no recipients rows produced"
        first = recips[0]
        code = self._open_pixel(camp["id"], first["subscriber_id"], first["id"])
        assert code == 200, code
        stats_after = requests.get(
            f"{API}/marketing/campaigns/{camp['id']}/stats",
            headers=_h(admin_tok), timeout=T,
        ).json()
        assert stats_after["sent"] >= sent_before, (
            f"'sent' regressed: before={sent_before} after={stats_after['sent']}"
        )
        assert stats_after["opened"] >= 1, stats_after
        # ``delivered`` must be monotonic too (dispatched, still counts).
        assert stats_after["delivered"] >= stats_before["delivered"], (
            f"'delivered' regressed: {stats_before['delivered']} → {stats_after['delivered']}"
        )

    def test_stats_shape_includes_not_yet_engaged(self, admin_tok):
        sub_ids = _seed_subs(admin_tok, 1, prefix="m2nye")
        list_id = _seed_list(admin_tok, sub_ids,
                              name=f"TEST_nye_{uuid.uuid4().hex[:6]}")
        camp = _mkcamp(admin_tok,
                        name=f"TEST_nye_{uuid.uuid4().hex[:6]}",
                        audience={"list_ids": [list_id]})
        requests.post(f"{API}/marketing/campaigns/{camp['id']}/send-now",
                        headers=_h(admin_tok), timeout=T)
        stats = requests.get(
            f"{API}/marketing/campaigns/{camp['id']}/stats",
            headers=_h(admin_tok), timeout=T,
        ).json()
        assert "not_yet_engaged" in stats, list(stats.keys())
        assert "failed" in stats, list(stats.keys())


class TestAbDeterminismLock:
    """Explicit lock per tester's HUMAN_REQUIRED note — same subscriber
    → same variant across repeat calls; 500-cohort 60/40 split stays
    within ±5%."""

    def test_repeat_call_returns_same_variant_for_10_subscribers(self):
        from services.marketing_campaigns import _select_variant
        camp = {
            "id": "camp-lock",
            "ab_test": {"enabled": True, "variants": [
                {"id": "A", "weight": 1}, {"id": "B", "weight": 1},
            ]},
        }
        for i in range(10):
            sid = f"sub-lock-{i}"
            first = _select_variant(camp, sid)
            second = _select_variant(camp, sid)
            assert first["id"] == second["id"], (
                f"drift for {sid}: {first['id']} != {second['id']}"
            )

    def test_500_cohort_60_40_split_within_5_percent(self):
        from services.marketing_campaigns import _select_variant
        camp = {
            "id": "camp-6040",
            "ab_test": {"enabled": True, "variants": [
                {"id": "A", "weight": 60},
                {"id": "B", "weight": 40},
            ]},
        }
        picks = [_select_variant(camp, f"sub-{i}")["id"] for i in range(500)]
        pct_a = picks.count("A") / len(picks) * 100
        pct_b = picks.count("B") / len(picks) * 100
        assert 55 <= pct_a <= 65, (
            f"A share {pct_a:.1f}% outside 60±5 (A={picks.count('A')}, B={picks.count('B')})"
        )
        assert 35 <= pct_b <= 45, (
            f"B share {pct_b:.1f}% outside 40±5"
        )


class TestBraceMigration:
    """Startup migration rewrites stored single-brace tokens to
    double-brace shape. Idempotent — running it twice on already-
    migrated data must be a no-op."""

    def test_migration_rewrites_single_brace_tokens_in_place(self, admin_tok, tenant_id):
        import asyncio
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        db_ = client[env["DB_NAME"]]
        try:
            # Write a campaign with SINGLE-brace tokens directly (simulating
            # legacy seed data that lands in DB without going through the
            # canonicalisation path).
            cid = f"TEST_brace_mig_{uuid.uuid4().hex[:8]}"
            db_.marketing_campaigns.insert_one({
                "id": cid, "tenant_id": tenant_id,
                "name": "TEST_brace_mig",
                "subject": "Hi {first_name}, {tenant_name} here",
                "content": {
                    "email_html": "<p>Hi {first_name}!</p>",
                    "sms_body": "Save 10% {first_name}",
                },
                "status": "draft",
                "created_at": "2026-02-01T00:00:00Z",
                "updated_at": "2026-02-01T00:00:00Z",
            })
            from services.marketing_campaigns import migrate_campaign_templates_to_double_brace
            asyncio.get_event_loop().run_until_complete(
                migrate_campaign_templates_to_double_brace()
            )
            doc = db_.marketing_campaigns.find_one({"id": cid})
            assert "{{first_name}}" in doc["subject"], doc["subject"]
            assert "{{tenant_name}}" in doc["subject"], doc["subject"]
            assert "{{first_name}}" in doc["content"]["email_html"]
            assert "{{first_name}}" in doc["content"]["sms_body"]
            # Idempotence — second run must not double-brace to ``{{{first_name}}}``.
            asyncio.get_event_loop().run_until_complete(
                migrate_campaign_templates_to_double_brace()
            )
            doc2 = db_.marketing_campaigns.find_one({"id": cid})
            assert "{{{" not in doc2["subject"], (
                f"double-migration doubled the braces: {doc2['subject']!r}"
            )
        finally:
            db_.marketing_campaigns.delete_one({"id": cid})
            client.close()


class TestTemplateLinter:
    """Feb-2026 M2 UI — linter endpoint surfaces unresolved tokens +
    deprecated single-brace usage BEFORE send, so the wizard can gate
    scheduling until the admin fixes them (with an explicit override
    checkbox to allow a send-anyway)."""

    def test_linter_clean_when_all_tokens_resolve(self, admin_tok):
        r = requests.post(f"{API}/marketing/templates/lint", headers=_h(admin_tok), json={
            "subject": "Hi {{first_name}} from {{tenant_name}}",
            "email_html": "<p>Hi {{first_name}}!</p>",
            "sms_body": "Hi {{first_name}}",
        }, timeout=T)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["clean"] is True
        assert data["unresolved_tokens"] == []
        assert data["deprecated_single_brace"] == []

    def test_linter_flags_unresolved_tokens_by_field(self, admin_tok):
        r = requests.post(f"{API}/marketing/templates/lint", headers=_h(admin_tok), json={
            "subject": "Hi {{first_name}}, {{bogus}}",
            "email_html": "<p>{{another_bogus}}</p>",
            "sms_body": "",
        }, timeout=T)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["clean"] is False
        tokens = {u["token"] for u in data["unresolved_tokens"]}
        assert "bogus" in tokens
        assert "another_bogus" in tokens
        fields = {u["field"] for u in data["unresolved_tokens"]}
        assert "subject" in fields
        assert "email_html" in fields

    def test_linter_flags_deprecated_single_brace(self, admin_tok):
        r = requests.post(f"{API}/marketing/templates/lint", headers=_h(admin_tok), json={
            "subject": "Hi {first_name}",
            "email_html": "<p>From {tenant_name}</p>",
            "sms_body": "",
        }, timeout=T)
        assert r.status_code == 200, r.text
        data = r.json()
        # Deprecated shape is advisory only — the parser resolves them
        # cleanly via the dual-brace regex, so ``clean`` must stay True.
        # ``unresolved_tokens`` is the only blocker.
        assert data["clean"] is True, (
            f"clean should be True when only deprecated shape present; got {data}"
        )
        deprecated = {(d["field"], d["token"]) for d in data["deprecated_single_brace"]}
        assert ("subject", "first_name") in deprecated
        assert ("email_html", "tenant_name") in deprecated
        unresolved_tokens = {u["token"] for u in data["unresolved_tokens"]}
        assert "first_name" not in unresolved_tokens
        assert "tenant_name" not in unresolved_tokens

    def test_linter_clean_true_with_deprecated_only_but_false_with_unresolved(self, admin_tok):
        """Explicit lock per tester feedback — deprecated warnings are
        advisory. Only unresolved tokens gate the send."""
        # Deprecated only → clean=True.
        r1 = requests.post(f"{API}/marketing/templates/lint", headers=_h(admin_tok), json={
            "subject": "Hi {first_name}",
        }, timeout=T)
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["clean"] is True
        assert d1["deprecated_single_brace"], "expected deprecated flag"
        # Deprecated + unresolved → clean=False.
        r2 = requests.post(f"{API}/marketing/templates/lint", headers=_h(admin_tok), json={
            "subject": "Hi {first_name}, {{no_such_token}}",
        }, timeout=T)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["clean"] is False
        assert any(u["token"] == "no_such_token" for u in d2["unresolved_tokens"])


class TestVipDigestSeed:
    """Every tenant hitting a Marketing M1 admin endpoint must
    lazy-seed the "VIP Monthly Digest" campaign template alongside the
    "VIP Customers" segment."""

    def test_vip_digest_template_present_after_first_admin_hit(self, admin_tok, tenant_id):
        requests.get(f"{API}/marketing/segments", headers=_h(admin_tok), timeout=T)
        from pymongo import MongoClient
        from dotenv import dotenv_values
        env = dotenv_values("/app/backend/.env")
        client = MongoClient(env["MONGO_URL"])
        db_ = client[env["DB_NAME"]]
        try:
            digest = db_.marketing_campaigns.find_one({
                "tenant_id": tenant_id,
                "template_slug": "vip-monthly-digest",
            })
            assert digest is not None, "VIP Monthly Digest not seeded on M1 hit"
            assert digest["status"] == "draft"
            assert digest["ab_test"]["enabled"] is True
            assert len(digest["ab_test"]["variants"]) == 2
            assert digest["is_system_template"] is True
        finally:
            client.close()

