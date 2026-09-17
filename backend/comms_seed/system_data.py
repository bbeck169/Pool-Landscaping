"""Communications Subsystem · Phase 1 — Seed data (6 email templates,
4 SMS templates, 5 automation rules). All body copy is in-house original
and blacklist-clean.

System rows are created with ``tenant_id=None`` so every tenant can see
and duplicate them. Rules are seeded with ``active=false`` so nothing
fires accidentally until an admin turns them on.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from services.comm_tokens import extract_tokens
# Feb 2026 · Invoice Email CTA Label — shared i18n helper. System
# templates are ``tenant_id=None`` and en-baked at seed time; the
# admin duplicates them per-tenant and can localise via the
# template editor. Per-tenant sequences localise via
# ``seed_system_templates.py`` which threads the tenant locale.
from services.email_cta_i18n import t_email_cta

# --- Email templates ----------------------------------------------------

def _block(t: str, props: dict, children=None, block_id: str | None = None) -> dict:
    d: dict = {"type": t, "id": block_id or str(uuid.uuid4()), "props": props}
    if children is not None:
        d["children"] = children
    return d


def _footer() -> dict:
    return _block("footer", {
        "company_name": "{{company.name}}",
        "address": "{{company.address}}",
        "unsubscribe_link_token": "{{unsubscribe_url}}",
        "padding": "24px",
        "text_color": "#8a8a8a",
    })


def _welcome_new_customer_blocks() -> list:
    return [
        _block("image", {"url": "{{company.logo_url}}", "alt": "{{company.name}}",
                          "alignment": "center", "width_pct": 40, "padding": "24px 24px 8px"}),
        _block("heading", {"text": "Welcome to {{company.name}}, {{customer.first_name}}",
                            "level": 1, "alignment": "left", "color": "#0f6ed1",
                            "padding": "8px 24px"}),
        _block("text", {"html": (
            "<p>Thanks for choosing us to look after your pool and yard. "
            "You'll hear from your assigned technician before your first visit, "
            "and every service call is followed by a photo-backed report you can review any time.</p>"
            "<p>You can review upcoming visits, billing history, and service reports in your customer portal.</p>"
        ), "padding": "8px 24px", "text_color": "#222222", "font_size": "15px",
           "font_family": "inherit", "background_color": "transparent"}),
        _block("button", {"label": "Open your portal", "link_url": "{{company.portal_link}}",
                            "alignment": "left", "background_color": "#0f6ed1",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("spacer", {"height_px": 8}),
        _block("text", {"html": (
            "<p>Have a question before your first visit? Reply to this email or call "
            "us at {{company.phone}}. We answer during business hours and return "
            "voicemail the same day.</p>"
        ), "padding": "8px 24px", "text_color": "#333333"}),
        _footer(),
    ]


def _appointment_reminder_blocks() -> list:
    return [
        _block("heading", {"text": "Your visit is tomorrow", "level": 1,
                            "alignment": "left", "color": "#111",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>Hi {{customer.first_name}},</p>"
            "<p>This is a friendly reminder that {{job.tech_name}} is scheduled to stop "
            "by <strong>{{job.next_visit_date}}</strong> for your {{job.service_type}} visit.</p>"
            "<p>No prep needed — just make sure gates are unlocked and pets are indoors "
            "when we arrive.</p>"
        ), "padding": "8px 24px"}),
        _block("divider", {"color": "#e0e0e0", "thickness_px": 1,
                            "padding": "16px 24px"}),
        _block("text", {"html": (
            "<p><strong>Need to reschedule?</strong> Reply to this email or call "
            "{{company.phone}} and we'll find a time that fits.</p>"
        ), "padding": "8px 24px", "text_color": "#333"}),
        _footer(),
    ]


def _visit_summary_blocks() -> list:
    return [
        _block("heading", {"text": "Your visit summary", "level": 1,
                            "alignment": "left", "color": "#0f6ed1",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>Hi {{customer.first_name}},</p>"
            "<p>{{job.tech_name}} wrapped up your {{job.service_type}} visit today. "
            "We've attached a full report — chemistry readings, work performed, and "
            "any recommendations — to your customer portal.</p>"
        ), "padding": "8px 24px"}),
        # Phase 22 · Feb 2026 — Service Record Images. Renders a
        # 200x200 thumbnail gallery when the visit has photos (and the
        # service report has a public_uuid). Substitutes to empty
        # string on visits without photos so the block collapses
        # cleanly — no orphan "Photos" heading in that case.
        _block("text", {"html": "{{SERVICE_RECORD_IMAGES}}",
                          "padding": "0 24px"}),
        _block("button", {"label": "View report", "link_url": "{{company.portal_link}}",
                            "alignment": "left", "background_color": "#0f6ed1",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("text", {"html": (
            "<p>Thanks for trusting {{company.name}} with your outdoor space. "
            "See you next visit.</p>"
        ), "padding": "16px 24px 8px", "text_color": "#333"}),
        _footer(),
    ]


def _invoice_created_blocks(locale: str = "en") -> list:
    """Blocks for the ``system.invoice_created`` template.

    Feb 2026 · Invoice Email CTA Label — CTA label localises against
    ``locale`` so non-English tenants get "Ver factura" / "Voir la
    facture" instead of an English CTA. Falls back to English per
    the ``t_email_cta`` contract when an unsupported locale is
    passed. Module-level ``SYSTEM_EMAIL_TEMPLATES`` bakes the
    English variant for the system-wide ``tenant_id=None`` seed
    rows; per-tenant sends resolve the recipient locale at the
    call site and rebuild the blocks via
    :func:`build_system_email_templates` (see this module).
    """
    return [
        _block("heading", {"text": "Invoice {{invoice.invoice_number}} is ready",
                            "level": 1, "alignment": "left", "color": "#111",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>Hi {{customer.first_name}},</p>"
            "<p>Your latest invoice for {{invoice.amount_due}} is ready to view. "
            "Payment is due by <strong>{{invoice.due_date}}</strong>.</p>"
        ), "padding": "8px 24px"}),
        _block("button", {"label": t_email_cta(locale, "view_invoice"), "link_url": "{{invoice.portal_link}}",
                            "alignment": "left", "background_color": "#0f6ed1",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("text", {"html": (
            "<p>Questions about a line item? Reply and we'll walk through it with you.</p>"
        ), "padding": "16px 24px 8px", "text_color": "#333"}),
        _footer(),
    ]


def _invoice_overdue_blocks(locale: str = "en") -> list:
    """Blocks for the ``system.invoice_overdue`` template.

    Feb 2026 · Invoice Email CTA Label — parallel to
    :func:`_invoice_created_blocks`; CTA label honours ``locale``.
    """
    return [
        _block("heading", {"text": "A quick note on invoice {{invoice.invoice_number}}",
                            "level": 1, "alignment": "left", "color": "#c94a3d",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>Hi {{customer.first_name}},</p>"
            "<p>Our records show invoice <strong>{{invoice.invoice_number}}</strong> "
            "for {{invoice.amount_due}} is a few days past due. If you've already "
            "sent payment, thank you and please disregard this note — it can take "
            "a couple of business days to post.</p>"
            "<p>If not, here's the quickest way to bring the account current:</p>"
        ), "padding": "8px 24px"}),
        _block("button", {"label": t_email_cta(locale, "view_invoice"), "link_url": "{{invoice.portal_link}}",
                            "alignment": "left", "background_color": "#c94a3d",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("text", {"html": (
            "<p>If cash flow is tight, reply to this email and we'll set up a short "
            "payment plan — we're a family business and we understand.</p>"
        ), "padding": "16px 24px 8px", "text_color": "#333"}),
        _footer(),
    ]


def _satisfaction_survey_blocks() -> list:
    return [
        _block("heading", {"text": "How did we do, {{customer.first_name}}?",
                            "level": 1, "alignment": "left", "color": "#0f6ed1",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>Your {{job.service_type}} visit wrapped up a few days ago and we'd love "
            "60 seconds of your time to know how we did. Your answer goes straight to "
            "the person on your account — not a review-farming inbox.</p>"
        ), "padding": "8px 24px"}),
        _block("button", {"label": "Leave feedback", "link_url": "{{company.portal_link}}",
                            "alignment": "left", "background_color": "#0f6ed1",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("text", {"html": (
            "<p>Thanks — feedback is how we get better.</p>"
        ), "padding": "16px 24px 8px", "text_color": "#333"}),
        _footer(),
    ]


# Reviews Phase 1 — Feb 2026. Original copy, catalog-token syntax.
def _review_request_blocks() -> list:
    return [
        _block("image", {"url": "{{company.logo_url}}", "alt": "{{company.name}}",
                          "alignment": "center", "width_pct": 36,
                          "padding": "24px 24px 4px"}),
        _block("heading", {"text": "Thanks for having us out, {{customer.first_name}}",
                            "level": 1, "alignment": "left", "color": "#0f6ed1",
                            "padding": "12px 24px 4px"}),
        _block("text", {"html": (
            "<p>{{tech.first_name}} just wrapped your visit and we hope your pool "
            "and yard are looking sharp. Would you tell us how we did? It takes about "
            "30 seconds, and honest feedback is the single biggest gift you can give "
            "a small business like ours.</p>"
        ), "padding": "8px 24px", "text_color": "#222222", "font_size": "15px",
           "font_family": "inherit", "background_color": "transparent"}),
        _block("button", {"label": "Share your feedback",
                            "link_url": "{{review_request.public_url}}",
                            "alignment": "left", "background_color": "#0f6ed1",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "14px 22px"}),
        _block("spacer", {"height_px": 12}),
        _block("text", {"html": (
            "<p>If anything about the visit fell short, please tell us that too — "
            "the same link goes straight to the owner's inbox, not to a public "
            "review site. We would rather hear it from you first.</p>"
        ), "padding": "8px 24px", "text_color": "#555"}),
        _footer(),
    ]


def _review_private_feedback_admin_alert_blocks() -> list:
    return [
        _block("heading", {"text": "New private feedback — {{customer.full_name}}",
                            "level": 1, "alignment": "left", "color": "#b34700",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>A recent customer used the private feedback path instead of posting "
            "publicly. Full details are on the review-request landing page linked "
            "below — the customer's rating, comments, and the job they were "
            "reviewing are all there.</p>"
        ), "padding": "8px 24px", "text_color": "#222222"}),
        _block("button", {"label": "Open review-request record",
                            "link_url": "{{review_request.public_url}}",
                            "alignment": "left", "background_color": "#b34700",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("text", {"html": (
            "<p>Reach out to the customer within one business day — following up "
            "quickly on private feedback is the single most effective way to "
            "recover the relationship (and often, the public review).</p>"
        ), "padding": "16px 24px 8px", "text_color": "#333"}),
        _footer(),
    ]


def build_system_email_templates(locale: str = "en") -> list:
    """Feb 2026 · Invoice Email CTA Label — locale-aware factory.

    Returns the SYSTEM_EMAIL_TEMPLATES list with the two invoice-CTA
    blocks rebuilt for ``locale``. All non-invoice templates are
    locale-invariant so they pass through unchanged (their CTAs
    either don't link to the invoice viewer OR aren't in-scope for
    the current ticket).

    Called at module import time with ``locale="en"`` to preserve
    the module-level ``SYSTEM_EMAIL_TEMPLATES`` constant that
    ``comms_seed/seed_comms.py`` iterates on for the shared
    ``tenant_id=None`` system-wide seed rows. Also invoked by
    per-tenant sends that resolve the recipient locale at the call
    site (see the Phase D5 i18n resolver + the send-path unit
    tests for the expected wiring).
    """
    return [
    {
        "code": "system.welcome_new_customer",
        "name": "Welcome — new customer",
        "description": "Sent when a new customer is added to the CRM.",
        "subject": "Welcome to {{company.name}}, {{customer.first_name}}",
        "blocks_json": _welcome_new_customer_blocks(),
    },
    {
        "code": "system.appointment_reminder",
        "name": "Appointment reminder — day before",
        "description": "Sent 24 hours before a scheduled service visit.",
        "subject": "Your {{company.name}} visit is tomorrow",
        "blocks_json": _appointment_reminder_blocks(),
    },
    {
        "code": "system.visit_summary",
        "name": "Visit summary — post-service",
        "description": "Sent after a service visit is finalized with report link.",
        "subject": "Your visit summary from {{job.tech_name}}",
        "blocks_json": _visit_summary_blocks(),
    },
    {
        "code": "system.invoice_created",
        "name": "Invoice created",
        "description": "Sent when a new invoice is generated.",
        "subject": "Invoice {{invoice.invoice_number}} — {{invoice.amount_due}} due {{invoice.due_date}}",
        "blocks_json": _invoice_created_blocks(locale),
    },
    {
        "code": "system.invoice_overdue",
        "name": "Invoice overdue — polite nudge",
        "description": "Sent when an invoice becomes past due.",
        "subject": "Reminder: invoice {{invoice.invoice_number}} is past due",
        "blocks_json": _invoice_overdue_blocks(locale),
    },
    {
        "code": "system.satisfaction_survey_invite",
        "name": "Satisfaction survey — 3 days post-visit",
        "description": "Invites recent customers to leave feedback.",
        "subject": "How did we do, {{customer.first_name}}?",
        "blocks_json": _satisfaction_survey_blocks(),
    },
    {
        "code": "system.review_request_email",
        "name": "Review request — post-visit ask",
        "description": ("Manual or automated ask to a happy customer to leave a "
                         "public review. Uses the star-gated landing so 1-3 star "
                         "responses divert to private feedback."),
        "subject": "How did we do, {{customer.first_name}}?",
        "blocks_json": _review_request_blocks(),
    },
    {
        "code": "system.review_private_feedback_admin_alert",
        "name": "Review — private feedback admin alert",
        "description": ("Emails the admin team the moment a customer submits a "
                         "1-3 star private feedback response so they can follow "
                         "up before the customer decides to post publicly."),
        "subject": "Private feedback from {{customer.full_name}} — please follow up",
        "blocks_json": _review_private_feedback_admin_alert_blocks(),
    },
    ]


# Module-level constant — kept for back-compat with every caller that
# imports it (``seed_comms``, ``test_visit_summary_merge_tag_seed``,
# ``test_reviews_backend`` …). English variant matches the historical
# shape byte-for-byte apart from the CTA label rename shipped by the
# Feb 2026 Invoice Email CTA Label ticket.
SYSTEM_EMAIL_TEMPLATES = build_system_email_templates("en")


# --- SMS templates ------------------------------------------------------

SYSTEM_SMS_TEMPLATES = [
    {
        "code": "system.sms.appointment_reminder",
        "name": "SMS · Appointment reminder",
        "body": ("{{company.name}}: friendly reminder — {{job.tech_name}} is "
                  "scheduled for {{job.next_visit_date}}. Reply STOP to opt out."),
    },
    {
        "code": "system.sms.tech_en_route",
        "name": "SMS · Technician en route",
        "body": ("{{company.name}}: {{job.tech_name}} is on the way to your "
                  "{{job.service_type}} visit and should arrive within 30 minutes. "
                  "Reply STOP to opt out."),
    },
    {
        "code": "system.sms.invoice_overdue_short",
        "name": "SMS · Invoice past due (short)",
        "body": ("{{company.name}}: invoice {{invoice.invoice_number}} for "
                  "{{invoice.amount_due}} is past due. Pay: {{invoice.portal_link}} "
                  "Reply STOP to opt out."),
    },
    {
        "code": "system.sms.thank_you",
        "name": "SMS · Thank-you after visit",
        "body": ("{{company.name}}: thanks for your business, {{customer.first_name}}. "
                  "Visit report: {{company.portal_link}} Reply STOP to opt out."),
    },
    {
        "code": "system.sms.review_request",
        "name": "SMS · Review request",
        "body": ("{{company.name}}: hey {{customer.first_name}}, would you share "
                  "30 seconds of feedback on your recent visit? "
                  "{{review_request.public_url}} Reply STOP to opt out."),
    },
]


# --- Automation rules ---------------------------------------------------

SYSTEM_AUTOMATION_RULES = [
    {
        "code": "welcome_new_customer_email",
        "name": "Welcome — new customer (email)",
        "description": "Send the welcome email when a new customer is created.",
        "trigger_event": "customer.created",
        "trigger_conditions": {},
        "channel": "email",
        "template_code": "system.welcome_new_customer",
        "send_delay_minutes": 0,
    },
    {
        "code": "appointment_reminder_email_dayof",
        "name": "Appointment reminder (email, day-of)",
        "description": "24-hour reminder before a scheduled service visit.",
        "trigger_event": "job.scheduled",
        "trigger_conditions": {},
        "channel": "email",
        "template_code": "system.appointment_reminder",
        "send_delay_minutes": 24 * 60,
    },
    {
        "code": "visit_summary_email",
        "name": "Visit summary (email)",
        "description": "Sent when a service report is finalized.",
        "trigger_event": "service_report.finalized",
        "trigger_conditions": {},
        "channel": "email",
        "template_code": "system.visit_summary",
        "send_delay_minutes": 0,
    },
    {
        "code": "invoice_created_notify",
        "name": "Invoice created (email)",
        "description": "Send the invoice notification when an invoice is created.",
        "trigger_event": "invoice.created",
        "trigger_conditions": {},
        "channel": "email",
        "template_code": "system.invoice_created",
        "send_delay_minutes": 0,
    },
    {
        "code": "invoice_overdue_nudge",
        "name": "Invoice overdue nudge (email)",
        "description": "Polite past-due reminder when an invoice becomes overdue.",
        "trigger_event": "invoice.overdue",
        "trigger_conditions": {},
        "channel": "email",
        "template_code": "system.invoice_overdue",
        "send_delay_minutes": 0,
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
