"""Phase D6.2 · Feb-2026 — dynamic email body i18n migration sweep.

Extends the D6 (P1.3) migration to cover the remaining transactional
email composers flagged in the D6 finish summary:

    * routers/admin_users.py                 · password-reset composer
    * services/tenant_billing_reminders.py   · trial-ending fallback strings
    * services/lead_notifications.py         · lead alert (email + SMS)
    * services/monthly_pricing_digest.py     · pricing insights digest
    * services/weekly_digest.py              · weekly tenant digest
    * services/aeo_digest.py                 · AEO PDF-attachment email

Acceptance coverage:
  1. Each composer renders in en/es/fr — subject + body contain
     the expected phrase.
  2. Placeholder-parity is enforced by the existing D6 drift-guard
     tests (this file adds a hardcoded-English grep guard for the
     6 files touched).
  3. Password-reset composer specifically: token URL still present
     in the body, temporary password preserved, security note
     translated in all 3 locales.
  4. Digest composers: row-data (customer/tech name, dollar
     amount, keyword) survives untranslated through the loop.
  5. AEO PDF body stays English (font-encoding limitation) — the
     email that carries it localises.

Note: `resolve_email_locale` priority + fallback semantics are
already covered by ``tests/test_email_bodies_i18n_migration.py`` —
we don't duplicate those here.
"""
from __future__ import annotations

import inspect
import re

import pytest


# ═════════════════════════════════════════════════════════════════════
# 1 · Placeholder-parity drift-guard extended to the new D6.2 keys
# ═════════════════════════════════════════════════════════════════════
_D62_KEY_PREFIXES = (
    "email.password_reset.",
    "email.trial_reminder.fallback.",
    "email.lead_alert.",
    "sms.lead_alert.",
    "email.monthly_pricing_digest.",
    "email.weekly_digest.",
    "email.aeo_digest.",
)


def test_d62_keys_present_across_all_three_locales():
    from services.email_body_i18n import LABELS
    en_d62 = {
        k for k in LABELS["en"]
        if any(k.startswith(p) for p in _D62_KEY_PREFIXES)
    }
    assert en_d62, "D6.2 sweep did not add any new keys to 'en'"
    for loc in ("es", "fr"):
        missing = en_d62 - set(LABELS[loc])
        assert not missing, (
            f"Locale {loc!r} missing D6.2 keys present under 'en': "
            f"{sorted(missing)}"
        )


def test_d62_placeholder_parity():
    from services.email_body_i18n import LABELS
    tag_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
    for key, en_tmpl in LABELS["en"].items():
        if not any(key.startswith(p) for p in _D62_KEY_PREFIXES):
            continue
        en_placeholders = set(tag_re.findall(en_tmpl))
        for loc in ("es", "fr"):
            loc_placeholders = set(tag_re.findall(LABELS[loc][key]))
            assert loc_placeholders == en_placeholders, (
                f"D6.2 placeholder drift on {key!r} in {loc!r}: "
                f"en={en_placeholders}, {loc}={loc_placeholders}"
            )


# ═════════════════════════════════════════════════════════════════════
# 2 · Password reset composer (routers/admin_users.py)
# ═════════════════════════════════════════════════════════════════════
def test_password_reset_html_english_body_contains_expected_phrases():
    from routers.admin_users import _password_reset_html
    html = _password_reset_html(
        target_name="Alice", actor_name="Bob",
        company_name="AquaTerra", temp_password="p@ssTemp!42",
        login_url="https://app.example.com/login",
        locale="en",
    )
    assert "Password reset by admin" in html
    assert "Hi Alice, Bob reset your AquaTerra password" in html
    assert "Temporary password" in html
    assert "p@ssTemp!42" in html                    # user data untouched
    assert 'href="https://app.example.com/login"' in html  # URL intact
    assert "Sign in" in html
    assert "contact your administrator immediately" in html


def test_password_reset_html_spanish_body():
    from routers.admin_users import _password_reset_html
    html = _password_reset_html(
        target_name="María", actor_name="Carlos",
        company_name="AquaTerra", temp_password="p@ssTemp!42",
        login_url="https://app.example.com/login",
        locale="es",
    )
    assert "Restablecimiento de contraseña por el administrador" in html
    assert "Hola María, Carlos restableció" in html
    assert "Contraseña temporal" in html
    assert "p@ssTemp!42" in html
    assert 'href="https://app.example.com/login"' in html
    assert "Iniciar sesión" in html
    assert "Si no fue usted" in html
    # No English leak.
    assert "Password reset by admin" not in html


def test_password_reset_html_french_body():
    from routers.admin_users import _password_reset_html
    html = _password_reset_html(
        target_name="Jean", actor_name="Claude",
        company_name="AquaTerra", temp_password="p@ssTemp!42",
        login_url="https://app.example.com/login",
        locale="fr",
    )
    assert "Mot de passe réinitialisé par un administrateur" in html
    assert "Bonjour Jean, Claude a réinitialisé" in html
    assert "Mot de passe temporaire" in html
    assert "p@ssTemp!42" in html
    assert 'href="https://app.example.com/login"' in html
    assert "Se connecter" in html
    assert "contactez immédiatement votre" in html
    assert "Password reset by admin" not in html


def test_password_reset_ttl_helper_unchanged():
    """Guardrail — the D6.2 sweep MUST NOT touch the token / TTL
    logic. This test asserts the ``_send_password_reset_email``
    function still generates a per-call idempotency key of the
    documented shape (``pwreset-{uid}-{new_id}``) and that no
    ``expires_in`` / ``ttl`` / ``expiry`` code path was modified."""
    from routers import admin_users as _mod
    src = inspect.getsource(_mod._send_password_reset_email)
    assert "pwreset-" in src, (
        "idempotency key template regressed"
    )
    # Nothing about the reset TTL should reference a hard-coded
    # duration in this composer — TTL lives on the ``users`` row
    # (``password_reset_expires_at``) and is set by the caller.
    assert "expires_in" not in src
    assert "ttl_seconds" not in src


# ═════════════════════════════════════════════════════════════════════
# 3 · Lead-alert composers (services/lead_notifications.py)
# ═════════════════════════════════════════════════════════════════════
def _lead():
    return {
        "id": "lead-abc",
        "name": "Jane Doe",
        "phone": "555-0100",
        "email": "jane@example.com",
        "service_address": "123 Main St",
        "service_interest": "pool cleaning",
        "message": "Weekly service needed for a 20k gallon pool.",
    }


def test_build_email_html_english():
    from services.lead_notifications import build_email_html
    html = build_email_html(
        lead=_lead(), app_url="https://admin.example.com", locale="en",
    )
    # Row labels are the ones translated (skipping ``Address`` since
    # the fixture only supplies ``service_address``).
    for label in ("Name", "Phone", "Email",
                   "Service address", "Service interest"):
        assert label in html, f"missing en label: {label!r}"
    # User data flows through unchanged.
    assert "Jane Doe" in html
    assert "555-0100" in html
    assert "pool cleaning" in html
    assert "New lead — Jane Doe" in html
    assert "View lead in admin" in html


def test_build_email_html_spanish():
    from services.lead_notifications import build_email_html
    html = build_email_html(
        lead=_lead(), app_url="https://admin.example.com", locale="es",
    )
    for label in ("Nombre", "Teléfono", "Correo electrónico",
                   "Dirección de servicio", "Servicio de interés"):
        assert label in html, f"missing es label: {label!r}"
    assert "Jane Doe" in html
    assert "pool cleaning" in html  # user data still English
    assert "Nuevo cliente potencial — Jane Doe" in html
    assert "Ver cliente potencial en admin" in html
    # No English label leakage.
    assert ">Name<" not in html
    assert "View lead in admin" not in html


def test_build_email_html_french():
    from services.lead_notifications import build_email_html
    html = build_email_html(
        lead=_lead(), app_url="https://admin.example.com", locale="fr",
    )
    for label in ("Nom", "Téléphone", "Courriel",
                   "Adresse du service", "Service demandé"):
        assert label in html, f"missing fr label: {label!r}"
    assert "Jane Doe" in html
    assert "Nouveau prospect — Jane Doe" in html
    assert "Voir le prospect dans l'admin" in html
    assert "View lead in admin" not in html


def test_build_sms_body_localises_header_and_view_link():
    from services.lead_notifications import build_sms_body
    en = build_sms_body(
        lead=_lead(), app_url="https://admin.example.com", locale="en",
    )
    assert en.startswith("New lead — Jane Doe")
    assert "View: https://admin.example.com/leads/lead-abc" in en
    es = build_sms_body(
        lead=_lead(), app_url="https://admin.example.com", locale="es",
    )
    assert es.startswith("Nuevo cliente potencial — Jane Doe")
    assert "Ver: https://admin.example.com/leads/lead-abc" in es
    fr = build_sms_body(
        lead=_lead(), app_url="https://admin.example.com", locale="fr",
    )
    assert fr.startswith("Nouveau prospect — Jane Doe")
    assert "Voir : https://admin.example.com/leads/lead-abc" in fr


def test_lead_email_website_visitor_fallback_localises():
    """When ``lead.name`` is empty the composer substitutes the
    "Website Visitor" fallback — it must translate."""
    from services.lead_notifications import build_email_html
    stub = dict(_lead()); stub["name"] = ""
    html_en = build_email_html(
        lead=stub, app_url="https://ex", locale="en",
    )
    assert "New lead — Website Visitor" in html_en
    html_es = build_email_html(
        lead=stub, app_url="https://ex", locale="es",
    )
    assert "Nuevo cliente potencial — Visitante del sitio web" in html_es
    html_fr = build_email_html(
        lead=stub, app_url="https://ex", locale="fr",
    )
    assert "Nouveau prospect — Visiteur du site web" in html_fr


# ═════════════════════════════════════════════════════════════════════
# 4 · Monthly pricing digest (services/monthly_pricing_digest.py)
# ═════════════════════════════════════════════════════════════════════
def _svc(service_type="chemical treatment", jobs=8, margin=12.5):
    return {"service_type": service_type,
            "job_count": jobs, "margin_pct": margin}


def _sug(service_type="chemical treatment"):
    return {"service_type": service_type,
            "current_avg_price_cents": 8500,
            "recommended_price_cents": 9500,
            "expected_margin_lift_pct": 6,
            "rationale": "Costs up 8% YoY per supplier invoices.",
            "customer_talking_points": ["Same tech, same schedule."]}


def test_monthly_pricing_digest_english_labels_and_data():
    from services.monthly_pricing_digest import _compose_html
    html = _compose_html(
        "AquaTerra", "2026-01", [_svc()], [_sug()], locale="en",
    )
    # Labels translated.
    assert "Monthly Pricing Insights" in html
    assert "Service" in html and "Pricing" in html
    assert "Rationale · Talking Points" in html
    assert "Current avg:" in html and "Recommend:" in html
    assert "+6% margin lift" in html
    assert "8 jobs · margin 12.5%" in html
    assert "Open in the app →" in html
    # User + LLM data untouched.
    assert "chemical treatment" in html
    assert "$85.00" in html and "$95.00" in html
    assert "Costs up 8% YoY" in html
    assert "Same tech, same schedule." in html


def test_monthly_pricing_digest_spanish_labels():
    from services.monthly_pricing_digest import _compose_html
    html = _compose_html(
        "AquaTerra", "2026-01", [_svc()], [_sug()], locale="es",
    )
    assert "Informe mensual de precios" in html
    assert ">Servicio<" in html and ">Precios<" in html
    assert "Justificación · Puntos de conversación" in html
    assert "Promedio actual:" in html
    assert "Recomendado:" in html
    assert "+6% de aumento de margen" in html
    assert "8 trabajos · margen 12.5%" in html
    assert "Abrir en la aplicación" in html
    assert "chemical treatment" in html  # user data intact
    assert "$85.00" in html
    assert "Monthly Pricing Insights" not in html


def test_monthly_pricing_digest_french_labels():
    from services.monthly_pricing_digest import _compose_html
    html = _compose_html(
        "AquaTerra", "2026-01", [_svc()], [_sug()], locale="fr",
    )
    assert "Analyse mensuelle des prix" in html
    assert ">Service<" in html and ">Tarification<" in html
    assert "Justification · Points de discussion" in html
    assert "Moyenne actuelle" in html
    assert "Recommandé" in html
    assert "+6% d'augmentation de marge" in html
    assert "8 interventions · marge 12.5%" in html
    assert "Ouvrir dans l'application" in html
    assert "Monthly Pricing Insights" not in html


def test_monthly_pricing_digest_empty_state_localises():
    from services.monthly_pricing_digest import _compose_html
    html_en = _compose_html("AT", "2026-01", [], [], locale="en")
    assert "No completed jobs with cost data in this month" in html_en
    html_es = _compose_html("AT", "2026-01", [], [], locale="es")
    assert "No hay trabajos completados con datos de costos" in html_es
    html_fr = _compose_html("AT", "2026-01", [], [], locale="fr")
    assert "Aucune intervention terminée avec des données" in html_fr


# ═════════════════════════════════════════════════════════════════════
# 5 · Weekly digest (services/weekly_digest.py)
# ═════════════════════════════════════════════════════════════════════
def _weekly_payload():
    return {
        "tenant_id": "t-1",
        "tenant_name": "AquaTerra",
        "week_of": "Feb 10, 2026",
        "iso_week": "2026-W07",
        "revenue": {"invoices_new": 12, "invoiced_total": 3450.00,
                     "payments_total": 2900.00, "overdue": 3},
        "operations": {"jobs_completed": 21, "jobs_pending": 5,
                        "job_requests_new": 4},
        "customers": {"new": 6, "portal_downloads": 18},
        "team": {"new_employees": 1,
                  "top_techs": [{"_id": "Sam Rivera", "jobs": 9}],
                  "onboarding_behind": ["late@example.com"]},
        "training": {"completions": 3},
        "templates_finalized_top": [{"_id": "SR-STD", "n": 5}],
        "cfo_highlights": ["Chem cost up 8% MoM"],
        "growth_summary": "Referral share climbed to 22%.",
    }


def test_weekly_digest_english_sections_and_data():
    from services.weekly_digest import render_html
    html = render_html(_weekly_payload(), locale="en")
    # Section headings translated.
    for h in ("Revenue &amp; Billing", "Field Operations",
               "Customer Activity", "Team", "Training",
               "Templates Library", "AI CFO Highlights",
               "Growth Playbook"):
        assert h in html, f"missing en section: {h!r}"
    assert "Weekly Digest · Week of Feb 10, 2026" in html
    assert "View Full Dashboard" in html
    assert "Sent automatically each Monday morning." in html
    # User data flows through untranslated.
    assert "AquaTerra" in html
    assert "Sam Rivera" in html
    assert "$3,450.00" in html
    assert "SR-STD" in html
    assert "Chem cost up 8% MoM" in html
    assert "Referral share climbed" in html


def test_weekly_digest_spanish_sections():
    from services.weekly_digest import render_html
    html = render_html(_weekly_payload(), locale="es")
    for h in ("Ingresos y facturación", "Operaciones de campo",
               "Actividad del cliente", "Equipo", "Capacitación",
               "Biblioteca de plantillas",
               "Puntos destacados del CFO IA",
               "Manual de crecimiento"):
        assert h in html, f"missing es section: {h!r}"
    assert "Resumen semanal · Semana del Feb 10, 2026" in html
    assert "Ver panel completo" in html
    assert "Enviado automáticamente cada lunes por la mañana." in html
    # Data untranslated.
    assert "Sam Rivera" in html
    assert "$3,450.00" in html
    # No English section headings.
    assert "Revenue &amp; Billing" not in html


def test_weekly_digest_french_sections():
    from services.weekly_digest import render_html
    html = render_html(_weekly_payload(), locale="fr")
    for h in ("Revenus et facturation", "Opérations sur le terrain",
               "Activité des clients", "Équipe", "Formation",
               "Bibliothèque de modèles",
               "Faits saillants du CFO IA",
               "Plan de croissance"):
        assert h in html, f"missing fr section: {h!r}"
    assert "Résumé hebdomadaire" in html
    assert "Voir le tableau de bord complet" in html
    assert "Envoyé automatiquement chaque lundi matin." in html
    # No English section headings.
    assert "Revenue &amp; Billing" not in html


def test_weekly_digest_empty_states_localise():
    from services.weekly_digest import render_html
    empty = _weekly_payload()
    empty["team"]["top_techs"] = []
    empty["templates_finalized_top"] = []
    empty["cfo_highlights"] = []
    empty["growth_summary"] = ""
    empty["team"]["onboarding_behind"] = []
    # EN
    html_en = render_html(empty, locale="en")
    assert "No completions this week" in html_en
    assert "No finalizations this week" in html_en
    assert "No highlights this week" in html_en
    assert "No growth playbook snapshot this week." in html_en
    # ES
    html_es = render_html(empty, locale="es")
    assert "Sin trabajos completados esta semana" in html_es
    assert "Sin plantillas finalizadas esta semana" in html_es
    # FR
    html_fr = render_html(empty, locale="fr")
    assert "Aucune intervention terminée cette semaine" in html_fr
    assert "Aucune finalisation de modèle cette semaine" in html_fr


def test_weekly_digest_unassigned_tech_row_localises():
    from services.weekly_digest import render_html
    payload = _weekly_payload()
    # Missing `_id` triggers the "Unassigned" fallback.
    payload["team"]["top_techs"] = [{"_id": None, "jobs": 4}]
    html_en = render_html(payload, locale="en")
    assert "Unassigned — 4 jobs" in html_en
    html_es = render_html(payload, locale="es")
    assert "Sin asignar — 4 jobs" in html_es
    html_fr = render_html(payload, locale="fr")
    assert "Non attribué — 4 jobs" in html_fr


# ═════════════════════════════════════════════════════════════════════
# 6 · AEO digest email (services/aeo_digest.py) — email localised,
#     PDF stays English (font-encoding limitation, documented)
# ═════════════════════════════════════════════════════════════════════
def _aeo_snapshot():
    return {
        "tenant_name": "AquaTerra",
        "period_start": "2026-02-08",
        "period_end":   "2026-02-14",
        "aeo_score":       {"current": 78, "prior": 72, "delta_pct": 8,
                             "sub_signals": {}},
        "ai_visibility":   {"total_probes": 50, "avg_score": 63,
                             "brand_mention_rate": 42.0,
                             "winning_query": None, "losing_query": None,
                             "providers": []},
        "brand_mentions":  {"total_new": 5, "sentiment": {},
                             "top_domains": [], "negative_samples": []},
        "action_items":    {"pending_fixes": 3, "pending_drafts": 2},
        "generated_at":    "2026-02-15T09:00:00Z",
    }


def test_aeo_digest_email_english():
    import asyncio
    from services.aeo_digest import deliver_email
    captured = {}
    async def fake_send(*, recipients, subject, html, text, attachment):
        captured.update({"subject": subject, "html": html,
                          "text": text, "attachment": attachment})
        return {"ok": True}
    asyncio.run(deliver_email(
        tenant_name="AquaTerra", snapshot=_aeo_snapshot(),
        pdf_bytes=b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n",
        recipients=["admin@example.com"],
        resend_send=fake_send, locale="en",
    ))
    assert "Weekly AEO Digest · AquaTerra" in captured["subject"]
    assert "Weekly AEO Digest · AquaTerra" in captured["html"]
    assert "AEO score: 78 / 100" in captured["html"]
    assert "PDF attached." in captured["html"]


def test_aeo_digest_email_spanish():
    import asyncio
    from services.aeo_digest import deliver_email
    captured = {}
    async def fake_send(*, recipients, subject, html, text, attachment):
        captured.update({"subject": subject, "html": html})
        return {"ok": True}
    asyncio.run(deliver_email(
        tenant_name="AquaTerra", snapshot=_aeo_snapshot(),
        pdf_bytes=b"%PDF-1.4\n",
        recipients=["admin@example.com"],
        resend_send=fake_send, locale="es",
    ))
    assert "Resumen semanal de AEO · AquaTerra" in captured["subject"]
    assert "Puntaje de AEO: 78 / 100" in captured["html"]
    assert "PDF adjunto." in captured["html"]
    assert "Weekly AEO Digest" not in captured["html"]


def test_aeo_digest_email_french():
    import asyncio
    from services.aeo_digest import deliver_email
    captured = {}
    async def fake_send(*, recipients, subject, html, text, attachment):
        captured.update({"subject": subject, "html": html})
        return {"ok": True}
    asyncio.run(deliver_email(
        tenant_name="AquaTerra", snapshot=_aeo_snapshot(),
        pdf_bytes=b"%PDF-1.4\n",
        recipients=["admin@example.com"],
        resend_send=fake_send, locale="fr",
    ))
    assert "Résumé AEO hebdomadaire" in captured["subject"]
    assert "Score AEO : 78 / 100" in captured["html"]
    assert "PDF joint." in captured["html"]


# ═════════════════════════════════════════════════════════════════════
# 7 · Grep-based guard — no hardcoded English body in the 6 files
# ═════════════════════════════════════════════════════════════════════
def _read_src(module_path: str) -> str:
    import importlib
    return inspect.getsource(importlib.import_module(module_path))


def test_no_hardcoded_english_body_in_password_reset():
    src = _read_src("routers.admin_users")
    forbidden = [
        "<h1 style=\"margin:0 0 12px 0;font-size:20px\">Password reset by admin</h1>",
        "Sign in with the temporary password below",
        ">Temporary password</div>",
        "If this wasn't you, contact your administrator immediately.",
    ]
    hits = [p for p in forbidden if p in src]
    assert not hits, (
        f"admin_users.py still ships hardcoded English body copy: {hits}"
    )


def test_no_hardcoded_english_body_in_lead_notifications():
    src = _read_src("services.lead_notifications")
    forbidden = [
        # Row labels used to be plain strings in the tuple below;
        # after migration they're catalog keys.
        '("Name",             "name"),',
        '("Phone",            "phone"),',
        # The heading used to be an f-string with "New lead —".
        '<h2 style=\'margin:0 0 12px;font-size:18px\'>New lead — ',
        # SMS header used to be an f-string.
        'lines: List[str] = [f"New lead — ',
        # "Website Visitor" fallback used to be inline.
        "or 'Website Visitor'}\\n\"]",
        # "View lead in admin" CTA used to be inline.
        "border-radius:8px;font-weight:600'>View lead in admin</a>",
    ]
    hits = [p for p in forbidden if p in src]
    assert not hits, (
        f"lead_notifications.py still ships hardcoded English: {hits}"
    )


def test_no_hardcoded_english_body_in_monthly_pricing_digest():
    src = _read_src("services.monthly_pricing_digest")
    forbidden = [
        ">Service<",  # column header used to be literal
        # These would only match if the raw HTML was inline.
        "Monthly Pricing Insights</h1>",
        "least-profitable service types + AI-drafted price increases",
        "No completed jobs with cost data in this month.",
        "Open in the app →\n",
        "f\"{tenant_name} · Monthly Pricing Insights · {month_key}\"",
    ]
    hits = [p for p in forbidden if p in src]
    assert not hits, (
        f"monthly_pricing_digest.py still ships hardcoded English: {hits}"
    )


def test_no_hardcoded_english_body_in_weekly_digest():
    src = _read_src("services.weekly_digest")
    forbidden = [
        ">Revenue &amp; Billing</h2>",
        ">Field Operations</h2>",
        ">Customer Activity</h2>",
        # Row labels
        "<li>New invoices:",
        "<li>Invoiced total:",
        "<li>Jobs completed:",
        "<li>New customers:",
        # Empty-state
        "No completions this week",
        "No finalizations this week",
        # CTA
        ">View Full Dashboard</a>",
        # Footer
        "Sent automatically each Monday morning.",
        # Subject
        "Weekly Digest · Week of {payload",
    ]
    hits = [p for p in forbidden if p in src]
    assert not hits, (
        f"weekly_digest.py still ships hardcoded English: {hits}"
    )


def test_no_hardcoded_english_body_in_aeo_digest():
    src = _read_src("services.aeo_digest")
    # The email portion is the only thing D6.2 migrated; the PDF
    # body (``render_pdf``) intentionally stays English because
    # ReportLab's default Helvetica can't render every UTF-8
    # character our es/fr copy needs — that's documented in the
    # ``deliver_email`` docstring.
    forbidden = [
        # The email HTML/text/subject sentences.
        "\"<h2>Weekly AEO Digest",
        "f\"AEO score: {snapshot",
        "f\"AI visibility avg: {snapshot",
        "f\"New mentions: {snapshot",
        "</ul><p>PDF attached.</p>",
    ]
    hits = [p for p in forbidden if p in src]
    assert not hits, (
        f"aeo_digest.py email path still ships hardcoded English: {hits}"
    )
    # Sanity check: the PDF path DOES still ship English (documented
    # limitation). This test asserts the marker string is still
    # present so future PRs don't accidentally regress the guard.
    assert '"Weekly AEO Digest"' in src, (
        "PDF-side English header removed — if you localised the "
        "PDF too, delete this sanity check and add a locale-scoped "
        "font swap for ReportLab."
    )


def test_no_hardcoded_english_body_in_tenant_billing_reminders():
    src = _read_src("services.tenant_billing_reminders")
    forbidden = [
        # Fallback strings used to be inline.
        'return "your plan pricing"',
        '"admin_name":      admin.get("name") or "there"',
        '"business_name":   tenant.get("name") or "your business"',
    ]
    hits = [p for p in forbidden if p in src]
    assert not hits, (
        f"tenant_billing_reminders.py still ships hardcoded fallbacks: {hits}"
    )
