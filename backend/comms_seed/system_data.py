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


def _invoice_created_blocks() -> list:
    return [
        _block("heading", {"text": "Invoice {{invoice.invoice_number}} is ready",
                            "level": 1, "alignment": "left", "color": "#111",
                            "padding": "24px 24px 8px"}),
        _block("text", {"html": (
            "<p>Hi {{customer.first_name}},</p>"
            "<p>Your latest invoice for {{invoice.amount_due}} is ready to view. "
            "Payment is due by <strong>{{invoice.due_date}}</strong>.</p>"
        ), "padding": "8px 24px"}),
        _block("button", {"label": "Pay online", "link_url": "{{invoice.portal_link}}",
                            "alignment": "left", "background_color": "#0f6ed1",
                            "text_color": "#ffffff", "border_radius": "6px",
                            "padding": "12px 20px"}),
        _block("text", {"html": (
            "<p>Questions about a line item? Reply and we'll walk through it with you.</p>"
        ), "padding": "16px 24px 8px", "text_color": "#333"}),
        _footer(),
    ]


def _invoice_overdue_blocks() -> list:
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
        _block("button", {"label": "Pay now", "link_url": "{{invoice.portal_link}}",
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


SYSTEM_EMAIL_TEMPLATES = [
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
        "blocks_json": _invoice_created_blocks(),
    },
    {
        "code": "system.invoice_overdue",
        "name": "Invoice overdue — polite nudge",
        "description": "Sent when an invoice becomes past due.",
        "subject": "Reminder: invoice {{invoice.invoice_number}} is past due",
        "blocks_json": _invoice_overdue_blocks(),
    },
    {
        "code": "system.satisfaction_survey_invite",
        "name": "Satisfaction survey — 3 days post-visit",
        "description": "Invites recent customers to leave feedback.",
        "subject": "How did we do, {{customer.first_name}}?",
        "blocks_json": _satisfaction_survey_blocks(),
    },
]


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
