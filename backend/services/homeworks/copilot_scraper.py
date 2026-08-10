"""Phase 55-b · Aug-2026 — Copilot CRM Playwright scraper.

⚠ EXPERIMENTAL ⚠

This module is NOT verified against a live Copilot CRM account. All
selectors below are educated guesses based on the Phase 55 recon doc
(§1.4 — the marketing site is Duda-hosted, the app fingerprint is
unknown until we log in). The user will smoke-test this against
their live account and file selector drift as follow-ups.

Design constraints:
  * Reuses ``services.suppliers.challenge.detect_challenge_on_page``
    for Cloudflare Turnstile detection. Slug: ``"homeworks"``.
  * Reuses ``services.suppliers.sessions.get_active_session`` for
    cookie rehydration — same infra as the Phase 54h wholesale
    scrapers, no new table.
  * Yields ``(raw, mapped)`` tuples per row so the orchestrator can
    persist them into ``homeworks_staging`` with an audit-quality
    ``raw_payload``.

Contract:
  * ``iter_customers(page)`` → async iterator yielding
    ``(raw_dict, mapped_dict)``.
  * ``iter_properties(page)`` → same shape, plus
    ``customer_homeworks_id`` inside raw for FK resolution.
  * ``authenticate(page)`` — login flow with challenge detection.

Everything is written mock-friendly: no top-level Playwright imports,
so tests can monkey-patch the class in without pulling in the runtime.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from config import logger
from services.homeworks.mapping import (
    map_customer, map_property, map_job, map_recurring_schedule,
    map_invoice, map_payment, map_quote,
)


LOGIN_URL = "https://secure.copilotcrm.com/login"
CUSTOMERS_URL = "https://secure.copilotcrm.com/customers"
PROPERTIES_URL = "https://secure.copilotcrm.com/properties"
JOBS_URL = "https://secure.copilotcrm.com/jobs"
RECURRING_URL = "https://secure.copilotcrm.com/recurring"
QUOTES_URL = "https://secure.copilotcrm.com/quotes"
INVOICES_URL = "https://secure.copilotcrm.com/invoices"
PAYMENTS_URL = "https://secure.copilotcrm.com/payments"
USER_AGENT = "AquaTerra-HomeworksImport/1.0"

# PLACEHOLDER selectors — MUST be verified against the live UI once
# the user runs the smoke. Overriding on a subclass or updating the
# module constant is cheap. Bug filed at PHASE_55_HOMEWORKS_IMPORT_DESIGN
# doc §9 as the highest-risk unknown.
SELECTORS: Dict[str, str] = {
    "input_email":               'input[name="email"], input[type="email"]',
    "input_password":            'input[name="password"], input[type="password"]',
    "btn_submit":                'button[type="submit"]',
    "logged_in_marker":          '[data-testid="dashboard-root"], .app-shell',
    # Customers list.
    "customer_row":              '[data-testid="customer-row"], tr.customer',
    "customer_id_attr":          "data-homeworks-id",
    "customer_first_name":       '[data-field="first_name"]',
    "customer_last_name":        '[data-field="last_name"]',
    "customer_email":            '[data-field="email"]',
    "customer_phone":            '[data-field="phone"]',
    "customer_address":          '[data-field="billing_address"]',
    "customer_tags":             '[data-field="tags"]',
    "customer_notes":            '[data-field="notes"]',
    # Properties list.
    "property_row":              '[data-testid="property-row"], tr.property',
    "property_id_attr":          "data-homeworks-id",
    "property_customer_ref":     "data-customer-id",
    "property_label":            '[data-field="label"]',
    "property_address":          '[data-field="address"]',
    "property_city":             '[data-field="city"]',
    # Jobs list (Phase 55-c).
    "job_row":                   '[data-testid="job-row"], tr.job',
    "job_id_attr":                "data-homeworks-id",
    "job_customer_ref":           "data-customer-id",
    "job_property_ref":           "data-property-id",
    "job_title":                 '[data-field="title"]',
    "job_description":           '[data-field="description"]',
    "job_status":                '[data-field="status"]',
    "job_scheduled_at":          '[data-field="scheduled_at"]',
    "job_scheduled_end":         '[data-field="scheduled_end"]',
    "job_duration":              '[data-field="duration_minutes"]',
    "job_assigned_email":        '[data-field="assigned_to_email"]',
    "job_service_template":      '[data-field="service_template_hint"]',
    "job_notes":                 '[data-field="notes"]',
    # Recurring schedules (Phase 55-c).
    "rec_row":                   '[data-testid="recurring-row"], tr.recurring',
    "rec_id_attr":                "data-homeworks-id",
    "rec_customer_ref":           "data-customer-id",
    "rec_property_ref":           "data-property-id",
    "rec_interval_type":         '[data-field="interval_type"]',
    "rec_interval_days":         '[data-field="interval_days"]',
    "rec_next_run":              '[data-field="next_run_at"]',
    "rec_active":                '[data-field="active"]',
    "rec_service_template":      '[data-field="service_template_hint"]',
    # Quotes list (Phase 55-d).
    "quote_row":                 '[data-testid="quote-row"], tr.quote',
    "quote_id_attr":              "data-homeworks-id",
    "quote_customer_ref":         "data-customer-id",
    "quote_property_ref":         "data-property-id",
    "quote_title":               '[data-field="title"]',
    "quote_status":              '[data-field="status"]',
    "quote_total_cents":         '[data-field="total_cents"]',
    "quote_line_items":          '[data-field="line_items"]',   # JSON blob
    # Invoices list (Phase 55-d).
    "inv_row":                   '[data-testid="invoice-row"], tr.invoice',
    "inv_id_attr":                "data-homeworks-id",
    "inv_customer_ref":           "data-customer-id",
    "inv_job_ref":                "data-job-id",
    "inv_quote_ref":              "data-quote-id",
    "inv_number":                '[data-field="invoice_number"]',
    "inv_status":                '[data-field="status"]',
    "inv_total_cents":           '[data-field="total_cents"]',
    "inv_due_date":              '[data-field="due_date"]',
    "inv_line_items":            '[data-field="line_items"]',   # JSON blob
    # Payments list (Phase 55-d).
    "pay_row":                   '[data-testid="payment-row"], tr.payment',
    "pay_id_attr":                "data-homeworks-id",
    "pay_invoice_ref":            "data-invoice-id",
    "pay_customer_ref":           "data-customer-id",
    "pay_amount":                '[data-field="amount"]',
    "pay_method":                '[data-field="method"]',
    "pay_applied_at":            '[data-field="applied_at"]',
    "pay_transaction_ref":       '[data-field="transaction_ref"]',
    "pay_stripe_charge":         '[data-field="stripe_charge_id"]',
    # Pagination.
    "btn_next_page":             'button.pagination-next, [data-testid="page-next"]',
}

RATE_LIMIT_SECONDS = 0.5
PAGE_TIMEOUT_MS = 30_000


class CopilotCRMScraper:
    """EXPERIMENTAL scraper for the Copilot CRM UI.

    Instances are cheap (no browser is opened at construction time).
    Every ``iter_*`` method expects an already-authenticated Playwright
    ``page`` object.
    """

    slug: str = "homeworks"
    display_name: str = "Homeworks (Copilot CRM)"

    def __init__(
        self,
        tenant_id: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        session_cookies: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.email = email or ""
        self.password = password or ""
        self.session_cookies = session_cookies or []

    async def authenticate(self, page: Any) -> None:
        """Fill the login form + wait for the app shell. Raises
        ``SupplierChallengeRequired`` (via ``detect_challenge_on_page``)
        if Turnstile fronts the login page."""
        from services.suppliers.challenge import detect_challenge_on_page

        await page.goto(LOGIN_URL)
        await detect_challenge_on_page(
            page, self.slug,
            username_selector=SELECTORS["input_email"],
        )
        if self.email and self.password:
            await page.fill(SELECTORS["input_email"], self.email)
            await page.fill(SELECTORS["input_password"], self.password)
            await page.click(SELECTORS["btn_submit"])
        # Wait for the app shell. If cookies were rehydrated the shell
        # may already be visible before we even filled the form.
        try:
            await page.wait_for_selector(
                SELECTORS["logged_in_marker"], timeout=15_000)
        except Exception as e:                                      # noqa: BLE001
            raise RuntimeError(f"homeworks login did not reach app shell: {e}")

    async def iter_customers(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per customer row. Paginates until
        the Next button disappears."""
        await page.goto(CUSTOMERS_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["customer_row"])
            if not rows and page_num == 1:
                logger.warning(
                    f"[homeworks] no customer rows on page 1 — "
                    f"selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_customer(row)
                if not raw.get("id"):
                    continue
                mapped = map_customer(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(
                    f"[homeworks] iter_customers finished: "
                    f"{yielded} rows across {page_num - 1} page(s)")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    async def iter_properties(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per property. ``raw`` includes
        ``customer_homeworks_id`` so the orchestrator can resolve the
        parent FK via staging."""
        await page.goto(PROPERTIES_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["property_row"])
            if not rows and page_num == 1:
                logger.warning(
                    f"[homeworks] no property rows on page 1 — "
                    f"selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_property(row)
                if not raw.get("id"):
                    continue
                # Parent FK is resolved by the orchestrator once the
                # customer staging row is written; mapper stubs it null.
                mapped = map_property(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(
                    f"[homeworks] iter_properties finished: "
                    f"{yielded} rows across {page_num - 1} page(s)")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    async def iter_jobs(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per job. ``raw`` carries
        ``customer_homeworks_id`` + ``property_homeworks_id`` so the
        orchestrator can resolve both FKs against the already-staged
        customer + property rows."""
        await page.goto(JOBS_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["job_row"])
            if not rows and page_num == 1:
                logger.warning(
                    "[homeworks] no job rows on page 1 — selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_job(row)
                if not raw.get("id"):
                    continue
                mapped = map_job(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(
                    f"[homeworks] iter_jobs finished: "
                    f"{yielded} rows across {page_num - 1} page(s)")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    async def iter_recurring_schedules(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per recurring schedule. Same FK
        resolution pattern as ``iter_jobs``."""
        await page.goto(RECURRING_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["rec_row"])
            if not rows and page_num == 1:
                logger.warning(
                    "[homeworks] no recurring rows on page 1 — "
                    "selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_recurring(row)
                if not raw.get("id"):
                    continue
                mapped = map_recurring_schedule(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(
                    f"[homeworks] iter_recurring finished: "
                    f"{yielded} rows across {page_num - 1} page(s)")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    async def iter_quotes(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per quote/estimate."""
        await page.goto(QUOTES_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["quote_row"])
            if not rows and page_num == 1:
                logger.warning(
                    "[homeworks] no quote rows on page 1 — selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_quote(row)
                if not raw.get("id"):
                    continue
                mapped = map_quote(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(f"[homeworks] iter_quotes finished: {yielded} rows")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    async def iter_invoices(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per invoice. ``raw`` carries
        ``job_homeworks_id`` and ``quote_homeworks_id`` for FK
        resolution against staged jobs + quotes."""
        await page.goto(INVOICES_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["inv_row"])
            if not rows and page_num == 1:
                logger.warning(
                    "[homeworks] no invoice rows on page 1 — selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_invoice(row)
                if not raw.get("id"):
                    continue
                mapped = map_invoice(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(f"[homeworks] iter_invoices finished: {yielded} rows")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    async def iter_payments(
        self, page: Any,
    ) -> AsyncIterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Yield ``(raw, mapped)`` per payment. ``raw`` carries
        ``invoice_homeworks_id`` for FK resolution against staged
        invoices."""
        await page.goto(PAYMENTS_URL)
        page_num = 1
        yielded = 0
        while True:
            rows = await page.query_selector_all(SELECTORS["pay_row"])
            if not rows and page_num == 1:
                logger.warning(
                    "[homeworks] no payment rows on page 1 — selector drift?")
                return
            if not rows:
                return
            for row in rows:
                raw = await self._extract_payment(row)
                if not raw.get("id"):
                    continue
                mapped = map_payment(raw)
                yielded += 1
                yield raw, mapped
            page_num += 1
            if not await self._go_next_page(page):
                logger.info(f"[homeworks] iter_payments finished: {yielded} rows")
                return
            await asyncio.sleep(RATE_LIMIT_SECONDS)

    # ─── Extraction helpers ──────────────────────────────────────
    async def _extract_customer(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["customer_id_attr"]),
            "first_name": await self._text(row, SELECTORS["customer_first_name"]),
            "last_name": await self._text(row, SELECTORS["customer_last_name"]),
            "email": await self._text(row, SELECTORS["customer_email"]),
            "phone": await self._text(row, SELECTORS["customer_phone"]),
            "billing_address": await self._text(row, SELECTORS["customer_address"]),
            "tags": await self._text(row, SELECTORS["customer_tags"]),
            "notes": await self._text(row, SELECTORS["customer_notes"]),
        }

    async def _extract_property(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["property_id_attr"]),
            "customer_homeworks_id": await self._attr(
                row, SELECTORS["property_customer_ref"]),
            "label": await self._text(row, SELECTORS["property_label"]),
            "address": await self._text(row, SELECTORS["property_address"]),
            "city": await self._text(row, SELECTORS["property_city"]),
        }

    async def _extract_job(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["job_id_attr"]),
            "customer_homeworks_id": await self._attr(
                row, SELECTORS["job_customer_ref"]),
            "property_homeworks_id": await self._attr(
                row, SELECTORS["job_property_ref"]),
            "title": await self._text(row, SELECTORS["job_title"]),
            "description": await self._text(
                row, SELECTORS["job_description"]),
            "status": await self._text(row, SELECTORS["job_status"]),
            "scheduled_at": await self._text(
                row, SELECTORS["job_scheduled_at"]),
            "scheduled_end": await self._text(
                row, SELECTORS["job_scheduled_end"]),
            "duration_minutes": await self._text(
                row, SELECTORS["job_duration"]),
            "assigned_to_email": await self._text(
                row, SELECTORS["job_assigned_email"]),
            "service_template_hint": await self._text(
                row, SELECTORS["job_service_template"]),
            "notes": await self._text(row, SELECTORS["job_notes"]),
        }

    async def _extract_recurring(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["rec_id_attr"]),
            "customer_homeworks_id": await self._attr(
                row, SELECTORS["rec_customer_ref"]),
            "property_homeworks_id": await self._attr(
                row, SELECTORS["rec_property_ref"]),
            "interval_type": await self._text(
                row, SELECTORS["rec_interval_type"]),
            "interval_days": await self._text(
                row, SELECTORS["rec_interval_days"]),
            "next_run_at": await self._text(
                row, SELECTORS["rec_next_run"]),
            "active": await self._text(row, SELECTORS["rec_active"]),
            "service_template_hint": await self._text(
                row, SELECTORS["rec_service_template"]),
        }

    async def _extract_quote(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["quote_id_attr"]),
            "customer_homeworks_id": await self._attr(
                row, SELECTORS["quote_customer_ref"]),
            "property_homeworks_id": await self._attr(
                row, SELECTORS["quote_property_ref"]),
            "title": await self._text(row, SELECTORS["quote_title"]),
            "status": await self._text(row, SELECTORS["quote_status"]),
            "total_cents": await self._text(
                row, SELECTORS["quote_total_cents"]),
            # ``line_items`` may be exposed as an embedded JSON blob
            # on the row — real selector to be tuned in smoke.
            "line_items": await self._text(
                row, SELECTORS["quote_line_items"]),
        }

    async def _extract_invoice(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["inv_id_attr"]),
            "customer_homeworks_id": await self._attr(
                row, SELECTORS["inv_customer_ref"]),
            "job_homeworks_id": await self._attr(
                row, SELECTORS["inv_job_ref"]),
            "quote_id": await self._attr(row, SELECTORS["inv_quote_ref"]),
            "invoice_number": await self._text(row, SELECTORS["inv_number"]),
            "status": await self._text(row, SELECTORS["inv_status"]),
            "total_cents": await self._text(
                row, SELECTORS["inv_total_cents"]),
            "due_date": await self._text(row, SELECTORS["inv_due_date"]),
            "line_items": await self._text(
                row, SELECTORS["inv_line_items"]),
        }

    async def _extract_payment(self, row: Any) -> Dict[str, Any]:
        return {
            "id": await self._attr(row, SELECTORS["pay_id_attr"]),
            "invoice_homeworks_id": await self._attr(
                row, SELECTORS["pay_invoice_ref"]),
            "customer_homeworks_id": await self._attr(
                row, SELECTORS["pay_customer_ref"]),
            "amount": await self._text(row, SELECTORS["pay_amount"]),
            "method": await self._text(row, SELECTORS["pay_method"]),
            "applied_at": await self._text(
                row, SELECTORS["pay_applied_at"]),
            "transaction_ref": await self._text(
                row, SELECTORS["pay_transaction_ref"]),
            "stripe_charge_id": await self._text(
                row, SELECTORS["pay_stripe_charge"]),
        }

    async def _go_next_page(self, page: Any) -> bool:
        """Click Next if available. Returns True when a click landed,
        False when there's no next page → stop iteration."""
        try:
            btn = await page.query_selector(SELECTORS["btn_next_page"])
        except Exception:                                           # noqa: BLE001
            btn = None
        if not btn:
            return False
        try:
            await btn.click()
            await page.wait_for_load_state(
                "networkidle", timeout=PAGE_TIMEOUT_MS)
        except Exception:                                           # noqa: BLE001
            return False
        return True

    async def _text(self, node: Any, sel: str) -> Optional[str]:
        try:
            el = await node.query_selector(sel)
        except Exception:                                           # noqa: BLE001
            el = None
        if not el:
            return None
        try:
            return (await el.text_content()) or None
        except Exception:                                           # noqa: BLE001
            return None

    async def _attr(self, node: Any, attr: str) -> Optional[str]:
        try:
            v = await node.get_attribute(attr)
        except Exception:                                           # noqa: BLE001
            v = None
        return v or None
