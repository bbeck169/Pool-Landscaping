"""Feb-2026 · Quote/Estimate email · idempotent per-tenant system template.

Seeds one row in ``marketing_templates`` per tenant with the stable
natural key ``system_key = "quote_estimate_email"``. The row is the
system default admins see on the Marketing → Templates page under the
``Quote / Estimate`` category.

Semantics (match ``services.referral_watcher.seed_referral_credit_templates``):

  * Row missing      → INSERT with the factory body + stamp
                       ``body_version`` for the future upgrade path.
  * Row present,
    ``system=False`` → tenant fully overrode; SKIP.
  * Row present,
    ``system=True``, body already carries the current
    ``body_version`` → idempotent SKIP.
  * Row present,
    ``system=True``, body diverges from factory defaults →
                       SKIP (preserve user edits).
                       A later version bump + a known-prior allow-list
                       (same pattern as the referral P53 upgrader) can
                       force-upgrade later; this first drop stays
                       conservative.

Hooks:
  * Boot-time fan-out via ``server.py`` background task → calls
    ``seed_quote_estimate_template_all_tenants()``.
  * New-tenant provisioning via
    ``routers/tenants.py::create_tenant`` → calls
    ``seed_for_tenant(tenant_id)``.

Logging:
  * Aggregated single log line at fan-out ("seeded N, skipped M,
    errors E") — no per-tenant chatter.
  * Fail-soft on individual tenant errors so one tenant's failure
    cannot block the rest of the fan-out (per Feb-2026 brief
    guardrail — matches the referral seeder's try/except shape).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from config import db
from utils import new_id, now_iso


logger = logging.getLogger("seed_quote_estimate_template")


TEMPLATE_SYSTEM_KEY = "quote_estimate_email"
_BODY_VERSION = "v1-2026-02"


_SUBJECT = "Your {{QUOTE_LABEL}} from {{COMPANY_NAME}}"


# Email-safe inline-styled HTML. The regex Mustache renderer in
# ``services/marketing/render.py`` substitutes ``{{TOKEN}}`` tags
# verbatim; every list-shaped value (line items) is pre-rendered by
# ``QUOTE_LINE_ITEMS_HTML`` (see
# ``services/marketing/merge_tags.py::_quote_line_items_html``).
_BODY = """<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:collapse;background-color:#F9FAFB;padding:24px 0;">
  <tr>
    <td align="center">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width:640px;background-color:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden;">
        <tr>
          <td style="padding:28px 32px 16px 32px;border-bottom:1px solid #E5E7EB;">
            <div style="font-size:12px;color:#6B7280;text-transform:uppercase;letter-spacing:0.08em;">{{COMPANY_NAME}}</div>
            <h1 style="margin:8px 0 0 0;font-size:22px;line-height:28px;color:#111827;font-weight:700;">Your {{QUOTE_LABEL}} is ready</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 32px 8px 32px;font-size:15px;line-height:24px;color:#111827;">
            <p style="margin:0 0 12px 0;">Hi {{CUSTOMER_FIRST_NAME}},</p>
            <p style="margin:0 0 12px 0;">Thanks for considering {{COMPANY_NAME}}. Your {{QUOTE_LABEL}} <strong>#{{QUOTE_SHORT_ID}}</strong> is below. Review the line items, and when you're ready, open the full {{QUOTE_LABEL}} in your portal to accept or ask a question.</p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px;">
            {{QUOTE_LINE_ITEMS_HTML}}
          </td>
        </tr>
        <tr>
          <td style="padding:4px 32px 24px 32px;font-size:15px;line-height:24px;color:#111827;">
            <p style="margin:0 0 4px 0;color:#4B5563;">{{QUOTE_LABEL}} total</p>
            <p style="margin:0;font-size:22px;line-height:28px;color:#111827;font-weight:700;font-variant-numeric:tabular-nums;">{{QUOTE_TOTAL}}</p>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:8px 32px 32px 32px;">
            <a href="{{ESTIMATE_LINK}}" style="display:inline-block;padding:12px 24px;background-color:#111827;color:#FFFFFF;text-decoration:none;font-weight:600;font-size:15px;border-radius:6px;" data-cta="view-quote">View your {{QUOTE_LABEL}}</a>
          </td>
        </tr>
        <tr>
          <td style="padding:0 32px 28px 32px;font-size:13px;line-height:20px;color:#6B7280;">
            <p style="margin:0 0 4px 0;">Questions? Just reply to this email and we'll help right away.</p>
            <p style="margin:12px 0 0 0;">— The {{COMPANY_NAME}} team</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""


def _factory_doc(tenant_id: str) -> Dict[str, Any]:
    """Build the full row body for insert. All fields match the
    shape produced by ``marketing_templates.seed_marketing_templates
    _for_tenant`` + the referral seeder so admin UI treats this row
    identically to the other system defaults (badge + revert path)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "system_key": TEMPLATE_SYSTEM_KEY,
        "name": "Quote / Estimate",
        "channel": "email",
        "category": "quotes",
        "subject": _SUBJECT,
        "body": _BODY,
        "body_version": _BODY_VERSION,
        "active": True,
        "system": True,
        "is_editable": True,
        "factory_defaults": {
            "name": "Quote / Estimate",
            "channel": "email",
            "category": "quotes",
            "subject": _SUBJECT,
            "body": _BODY,
            "body_version": _BODY_VERSION,
        },
        "created_at": ts,
        "updated_at": ts,
        "created_by": None,
    }


async def seed_for_tenant(tenant_id: str) -> Dict[str, int]:
    """Idempotent per-tenant upsert. Returns a counters dict with
    exactly one of ``inserted`` / ``skipped_current`` /
    ``skipped_customized`` / ``skipped_non_system`` incremented so
    the fan-out summary adds cleanly across tenants."""
    counts = {
        "inserted": 0,
        "skipped_current": 0,
        "skipped_customized": 0,
        "skipped_non_system": 0,
    }
    existing = await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "system_key": TEMPLATE_SYSTEM_KEY},
        {"_id": 0},
    )
    if not existing:
        await db.marketing_templates.insert_one(_factory_doc(tenant_id))
        counts["inserted"] = 1
        return counts

    if not existing.get("system"):
        # Tenant fully overrode — do not touch.
        counts["skipped_non_system"] = 1
        return counts

    if existing.get("body_version") == _BODY_VERSION:
        counts["skipped_current"] = 1
        return counts

    # ``system=True`` but body_version missing / outdated. First-drop
    # policy is conservative: preserve the existing body so admin
    # edits made in the gap between the first boot and the version
    # stamp aren't trampled. A future upgrade commit can allow-list
    # the known-prior bodies and promote the upgrade path (same
    # pattern as the referral P53 upsert).
    counts["skipped_customized"] = 1
    return counts


async def seed_all_tenants() -> Dict[str, int]:
    """Fan-out across every tenant. Fail-soft per tenant per the
    Feb-2026 brief guardrail — one tenant's failure must not block
    the rest. Returns an aggregated counters dict for the single
    boot-time log line."""
    agg = {
        "tenants": 0,
        "inserted": 0,
        "skipped_current": 0,
        "skipped_customized": 0,
        "skipped_non_system": 0,
        "errors": 0,
    }
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        agg["tenants"] += 1
        try:
            tc = await seed_for_tenant(t["id"])
            for k, v in tc.items():
                if k in agg:
                    agg[k] += v
        except Exception as exc:  # noqa: BLE001
            agg["errors"] += 1
            # Per-tenant warning for triage — the summary stays a
            # single aggregated INFO line below.
            logger.warning(
                "[seed_quote_estimate_template] tenant %s failed: %s",
                t.get("id"), exc,
            )
    logger.info(
        "[seed_quote_estimate_template] fan-out — tenants=%d inserted=%d "
        "skipped_current=%d skipped_customized=%d skipped_non_system=%d "
        "errors=%d",
        agg["tenants"], agg["inserted"], agg["skipped_current"],
        agg["skipped_customized"], agg["skipped_non_system"], agg["errors"],
    )
    return agg
