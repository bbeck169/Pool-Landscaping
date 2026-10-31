"""Feb 2026 · Task B — Seed 3 canonical system-template sequences per tenant.

What this seeds
---------------
Three inactive, distinct-badge sequences every tenant gets pre-installed
so admins can one-click-activate proven revenue plays rather than
building from scratch:

  1. ``invoice_past_due_7d``       — 7-day dunning nudge (Email + SMS)
  2. ``job_completed_review_48h``  — 48h post-service review request
                                     (Email primary; SMS optional)
  3. ``customer_birthday_10pct_off`` — birthday greeting w/ 10% code
                                     (Email + SMS)

All three are stamped with:

* ``active: false``                — admin flips on when they're ready
* ``system_template: true``        — renders the "System Template"
                                     badge on the UI + protects the
                                     DELETE endpoint (409 → hint
                                     "deactivate instead")
* ``system_template_id: <slug>``   — canonical identifier used for
                                     per-tenant idempotency
* ``schema_version: 2``            — v2 trigger AST (matches the
                                     ``services/marketing/trigger_evaluator``
                                     shipped in Phase 1)

Idempotency
-----------
* **Boot migration**: sentinel doc in ``db.migrations`` with
  ``id = feb2026_seed_system_templates_v1``. First run scans every
  active tenant, seeds any missing template, stamps the sentinel with
  a summary. Second boot returns ``skipped=True`` immediately.
* **Per-tenant idempotency (secondary guard)**: even when the sentinel
  hasn't fired for a tenant (e.g. a brand-new tenant created AFTER the
  boot sentinel stamped), we check
  ``marketing_sequences.find_one({tenant_id, system_template_id})``
  before inserting. Naturally re-runnable; never double-inserts.
* **Tenant provisioning hook**: ``seed_system_templates_for_tenant``
  is called from ``routers/tenants.py::create_tenant`` after every new
  tenant lands. Reuses the same helper so behavior stays consistent.

Merge tags
----------
The user brief used friendly names (``PAY_INVOICE_LINK``,
``LEAVE_REVIEW_LINK``, ``AMOUNT_DUE``). We map them to the canonical
tokens already registered in ``services/marketing/merge_tags.py``:

  * ``AMOUNT_DUE``          →  ``INVOICE_BALANCE`` (outstanding
                                 balance = ``total − amount_paid``;
                                 preferred over ``INVOICE_TOTAL`` for
                                 past-due reminders so partial-payment
                                 invoices render the amount still owed —
                                 TD-sms-reminder-use-balance-not-total)
  * ``PAY_INVOICE_LINK``    →  ``INVOICE_PAY_MAGIC_URL``
  * ``LEAVE_REVIEW_LINK``   →  ``REVIEW_PAGE``

For the birthday promo code we ship a static ``BDAY10`` string in the
template body — per-customer rotating codes are a separate merge-tag
piece of work explicitly scoped out.

Localisation
------------
Feb 2026 · Invoice Email CTA Label ticket — the CTA button label on
the ``invoice_past_due_7d`` email template is threaded through the
:func:`services.email_cta_i18n.t_email_cta` helper at seed time,
keyed on the tenant's ``default_locale``. This produces
"View Invoice" for ``en`` tenants, "Ver factura" for ``es``, and
"Voir la facture" for ``fr`` without a runtime merge-tag hop.

Rejecting deletion
------------------
``routers/marketing_sequences.py::delete_sequence`` reads the
``system_template`` flag and returns HTTP 409 with a friendly hint
when it's ``true``. Admin can still ``PATCH`` (toggle active, edit
body/subject).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from config import db
from utils import new_id, now_iso
from services.email_cta_i18n import t_email_cta


logger = logging.getLogger("seed_system_templates")

_SENTINEL_ID = "feb2026_seed_system_templates_v1"


# ────────────────────────────────────────────────────────────────────
# Template definitions
# ────────────────────────────────────────────────────────────────────
# Each entry describes ONE sequence + the marketing_templates docs
# its steps reference. ``system_template_id`` is the stable identifier
# used for idempotency; ``system_key`` on the templates is used to
# reuse existing tenant-scoped templates when they exist (avoid
# duplicate ``marketing_templates`` rows on re-seed).


def _build_templates(locale: str) -> List[Dict[str, Any]]:
    """Return the seed template list with the CTA label resolved for
    ``locale`` (Feb 2026 · Invoice Email CTA Label). Sequences that
    don't include an invoice CTA are locale-invariant.
    """
    view_invoice_label = t_email_cta(locale, "view_invoice")
    return [
    # 1. Invoice past due — 7d win-back
    {
        "system_template_id": "invoice_past_due_7d",
        "name": "Invoice past due · 7-day win-back",
        "description": "Friendly reminder + pay-link 7 days after an "
                        "invoice becomes overdue. Dual-channel by default.",
        "trigger_type": "invoice_past_due_N_days",
        "trigger_config": {"days_past_due": 7},
        "trigger_v2": {
            "logic": "AND",
            "conditions": [{
                "event": "invoice_overdue",
                "delay": {"mode": "after", "value": 7, "unit": "day"},
                "filters": {},
            }],
        },
        "email_template": {
            "system_key": "system_tpl_invoice_past_due_7d_email",
            "name": "System Template · Invoice past due 7d · Email",
            "category": "billing",
            "subject": ("Quick reminder — invoice {{INVOICE_NUMBER}} "
                        "is 7 days past due"),
            "body": (
                "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
                "<p>Just a friendly note that invoice "
                "<strong>{{INVOICE_NUMBER}}</strong> for "
                "<strong>{{INVOICE_BALANCE}}</strong> is now 7 days past "
                "due. If you've already sent payment, thank you — please "
                "ignore this message.</p>"
                "<p>Otherwise, you can review your invoice here:</p>"
                "<p><a href=\"{{INVOICE_PAY_MAGIC_URL}}\" "
                "style=\"background:#DC2626;color:#fff;padding:12px 20px;"
                "border-radius:8px;text-decoration:none;display:inline-block;"
                "font-size:22px;font-weight:700;\">"
                f"{view_invoice_label}</a></p>"
                "<p>If you have questions or need to set up a payment "
                "plan, just reply to this email — we're happy to help.</p>"
                "<p>Thanks,<br/>{{COMPANY_NAME}}</p>"
            ),
        },
        "sms_template": {
            "system_key": "system_tpl_invoice_past_due_7d_sms",
            "name": "System Template · Invoice past due 7d · SMS",
            "category": "billing",
            "subject": "",
            "body": (
                "Hi {{CUSTOMER_FIRST_NAME}} — friendly reminder that "
                "invoice {{INVOICE_NUMBER}} ({{INVOICE_BALANCE}}) is 7 "
                "days past due. Pay in one tap: {{INVOICE_PAY_MAGIC_URL}} "
                "— {{COMPANY_NAME}}"
            ),
        },
        "steps": [
            # Email first (immediate on trigger); SMS 4h later so the
            # customer sees the email first and doesn't feel spammed.
            {"channel": "email", "delay_from": "trigger",
              "delay_hours": 0},
            {"channel": "sms",   "delay_from": "previous_step",
              "delay_hours": 4},
        ],
    },
    # 2. Job completed — 48h review request
    {
        "system_template_id": "job_completed_review_48h",
        "name": "Job completed · 48h review request",
        "description": "Thank-you + review link 48 hours after a job "
                        "is completed. Email primary; SMS optional.",
        "trigger_type": "service_completed",
        "trigger_config": {},
        "trigger_v2": {
            "logic": "AND",
            "conditions": [{
                "event": "job_completed",
                "delay": {"mode": "after", "value": 48, "unit": "hour"},
                "filters": {},
            }],
        },
        "email_template": {
            "system_key": "system_tpl_job_completed_review_48h_email",
            "name": "System Template · Review request 48h · Email",
            "category": "review",
            "subject": "How was your service, {{CUSTOMER_FIRST_NAME}}?",
            "body": (
                "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
                "<p>Thanks for choosing {{COMPANY_NAME}} — we hope "
                "everything went great! If you have a moment, we'd "
                "love to hear about your experience.</p>"
                "<p><a href=\"{{REVIEW_PAGE}}\" "
                "style=\"background:#0369A1;color:#fff;padding:10px 18px;"
                "border-radius:6px;text-decoration:none;display:inline-block\">"
                "Leave a review</a></p>"
                "<p>Reviews help us grow and let other neighbors know "
                "we're the real deal. Thanks so much!</p>"
                "<p>— The {{COMPANY_NAME}} team</p>"
            ),
        },
        "sms_template": {
            "system_key": "system_tpl_job_completed_review_48h_sms",
            "name": "System Template · Review request 48h · SMS",
            "category": "review",
            "subject": "",
            "body": (
                "Hi {{CUSTOMER_FIRST_NAME}}, thanks for choosing "
                "{{COMPANY_NAME}}! If you have a moment, we'd love a "
                "quick review: {{REVIEW_PAGE}}"
            ),
        },
        "steps": [
            # Email is the primary channel; SMS is opt-in via admin
            # patch. Ship both as steps so activating the sequence
            # sends both by default; admin can drop the SMS step
            # after activation if they prefer email-only.
            {"channel": "email", "delay_from": "trigger",
              "delay_hours": 0},
            {"channel": "sms",   "delay_from": "previous_step",
              "delay_hours": 24},
        ],
    },
    # 3. Customer birthday — 10% off promo
    {
        "system_template_id": "customer_birthday_10pct_off",
        "name": "Customer birthday · 10% off promo",
        "description": "Birthday greeting + one-time 10% discount code "
                        "sent on the customer's birthday.",
        "trigger_type": "birthday",
        "trigger_config": {},
        "trigger_v2": {
            "logic": "AND",
            "conditions": [{
                "event": "customer_birthday",
                "delay": {"mode": "immediate"},
                "filters": {},
            }],
        },
        "email_template": {
            "system_key": "system_tpl_customer_birthday_10pct_off_email",
            "name": "System Template · Birthday 10% off · Email",
            "category": "promotion",
            "subject": ("Happy birthday, {{CUSTOMER_FIRST_NAME}}! "
                        "Here's 10% off your next service"),
            "body": (
                "<p>Happy birthday, {{CUSTOMER_FIRST_NAME}}!</p>"
                "<p>To celebrate, here's a little something from "
                "{{COMPANY_NAME}} — <strong>10% off your next service</strong>. "
                "Use code <strong>BDAY10</strong> at checkout or mention "
                "it when you book.</p>"
                "<p>Wishing you a wonderful year ahead.</p>"
                "<p>— The {{COMPANY_NAME}} team</p>"
            ),
        },
        "sms_template": {
            "system_key": "system_tpl_customer_birthday_10pct_off_sms",
            "name": "System Template · Birthday 10% off · SMS",
            "category": "promotion",
            "subject": "",
            "body": (
                "Happy birthday, {{CUSTOMER_FIRST_NAME}}! Enjoy 10% off "
                "your next {{COMPANY_NAME}} service with code BDAY10."
            ),
        },
        "steps": [
            # Same-day burst — email + SMS both immediate. Birthday
            # should feel warm on the day, not trickled.
            {"channel": "email", "delay_from": "trigger",
              "delay_hours": 0},
            {"channel": "sms",   "delay_from": "trigger",
              "delay_hours": 0},
        ],
    },
]


# Back-compat alias — legacy tests + imports use ``_TEMPLATES`` as a
# module-level constant. Resolves to the English-baked variant so
# behaviour is unchanged for those callers.
_TEMPLATES: List[Dict[str, Any]] = _build_templates("en")


async def _ensure_template(tenant_id: str, tpl_def: Dict[str, Any],
                            channel: str) -> str:
    """Insert a ``marketing_templates`` doc if the tenant doesn't
    already have one with the same ``system_key``. Returns the
    template id."""
    existing = await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "system_key": tpl_def["system_key"]},
        {"_id": 0, "id": 1},
    )
    if existing:
        return existing["id"]
    tid = new_id()
    now = now_iso()
    await db.marketing_templates.insert_one({
        "id": tid,
        "tenant_id": tenant_id,
        "system_key": tpl_def["system_key"],
        "name": tpl_def["name"],
        "channel": channel,
        "category": tpl_def["category"],
        "subject": tpl_def["subject"],
        "body": tpl_def["body"],
        "active": True,
        "system": True,
        "created_at": now,
        "updated_at": now,
    })
    return tid


async def seed_system_templates_for_tenant(tenant_id: str
                                             ) -> Dict[str, Any]:
    """Seed the 3 canonical sequences for ONE tenant. Idempotent —
    an existing ``system_template_id`` short-circuits.

    Feb 2026 · Invoice Email CTA Label — the ``invoice_past_due_7d``
    email body's CTA label is resolved against the tenant's
    ``default_locale`` at seed time (en/es/fr → "View Invoice" /
    "Ver factura" / "Voir la facture"). Falls back to ``en`` when
    the tenant record is missing or the locale is unsupported.

    Returns::
        {
            "tenant_id": str,
            "seeded":    ["invoice_past_due_7d", ...],  # newly inserted
            "existing":  ["job_completed_review_48h", ...],  # skipped
            "template_ids": {"invoice_past_due_7d": "<seq_id>", ...},
        }
    """
    seeded: List[str] = []
    existing: List[str] = []
    ids: Dict[str, str] = {}

    # Resolve locale ONCE per tenant so the CTA label stays consistent
    # across email + sms + steps within this seed pass.
    _tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "default_locale": 1},
    ) or {}
    _tenant_locale = _tenant.get("default_locale") or "en"
    templates_for_tenant = _build_templates(_tenant_locale)

    for tpl_def in templates_for_tenant:
        stid = tpl_def["system_template_id"]
        existing_seq = await db.marketing_sequences.find_one(
            {"tenant_id": tenant_id, "system_template_id": stid},
            {"_id": 0, "id": 1},
        )
        if existing_seq:
            existing.append(stid)
            ids[stid] = existing_seq["id"]
            continue

        # Insert per-channel marketing_templates first (each returns
        # an id we point the sequence's steps at). The helper is
        # idempotent — pre-existing templates with the same system_key
        # are reused.
        email_id = await _ensure_template(
            tenant_id, tpl_def["email_template"], "email",
        )
        sms_id = await _ensure_template(
            tenant_id, tpl_def["sms_template"], "sms",
        )
        step_tpl = {"email": email_id, "sms": sms_id}
        steps = [
            {
                "order": i,
                "channel": s["channel"],
                "template_id": step_tpl[s["channel"]],
                "delay_from": s["delay_from"],
                "delay_hours": int(s["delay_hours"]),
                "condition": None,
            }
            for i, s in enumerate(tpl_def["steps"])
        ]

        seq_id = new_id()
        now = now_iso()
        await db.marketing_sequences.insert_one({
            "id": seq_id,
            "tenant_id": tenant_id,
            "name": tpl_def["name"],
            "description": tpl_def["description"],
            "trigger_type": tpl_def["trigger_type"],
            "trigger_config": tpl_def["trigger_config"] or {},
            # Schema v2 trigger AST — matches trigger_evaluator.
            "trigger": tpl_def["trigger_v2"],
            "schema_version": 2,
            "steps": steps,
            "active": False,             # opt-in — admin activates
            "stop_on_reply": True,
            "stop_on_unsubscribe": True,
            # Task B markers
            "system_template": True,
            "system_template_id": stid,
            # Pre-existing ``system`` flag stays False so the SEED
            # badge is reserved for the older seed-set; TEMPLATE
            # badge (frontend) keys off ``system_template``.
            "system": False,
            "created_at": now,
            "updated_at": now,
        })
        seeded.append(stid)
        ids[stid] = seq_id

    return {
        "tenant_id": tenant_id,
        "seeded": seeded,
        "existing": existing,
        "template_ids": ids,
    }


async def seed_system_templates_all_tenants() -> Dict[str, Any]:
    """Idempotent boot migration. Runs once per environment. Second-
    and-later boots skip immediately via the ``db.migrations`` sentinel.

    Per-tenant idempotency (via ``system_template_id``) means even
    tenants created BETWEEN boot runs land with the templates on their
    next provisioning call (see ``routers/tenants.py``) — the sentinel
    is only a fast-path for boot-time bulk seed."""
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel:
        return {
            "skipped": True,
            "reason": "already_ran",
            "ran_at": sentinel.get("ran_at"),
            "summary": sentinel.get("summary") or {},
        }

    tenants_scanned = 0
    tenants_seeded = 0
    total_seeded = 0
    total_skipped = 0

    async for tenant in db.tenants.find(
        {"active": {"$ne": False}}, {"_id": 0, "id": 1, "slug": 1},
    ):
        tenants_scanned += 1
        tid = tenant.get("id")
        if not tid:
            continue
        try:
            report = await seed_system_templates_for_tenant(tid)
            if report["seeded"]:
                tenants_seeded += 1
            total_seeded += len(report["seeded"])
            total_skipped += len(report["existing"])
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[seed_system_templates] tenant=%s failed: %s", tid, e,
            )

    summary = {
        "tenants_scanned": tenants_scanned,
        "tenants_seeded":  tenants_seeded,
        "templates_seeded": total_seeded,
        "templates_skipped_idempotent": total_skipped,
    }
    await db.migrations.insert_one({
        "id": _SENTINEL_ID,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    })
    logger.info(
        "[seed_system_templates] boot migration complete: %s", summary,
    )
    return {"skipped": False, "summary": summary}
