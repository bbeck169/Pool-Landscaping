# Phase K47 · Invoice View Tracking (Feb 2026)

## Executive summary

Every customer-facing view of an invoice — email magic link, SMS
magic link, or authenticated portal open — is now recorded into
the ``invoice_views`` collection with source, timestamp, and
user-agent / IP metadata. Three aggregate fields are denormalised
onto the invoice document (``first_viewed_at``,
``last_viewed_at``, ``view_count``) so the invoices list can show
a "Viewed Nd ago" pill without an extra roundtrip per row. The
admin invoice detail page (web + mobile) surfaces a new
"View History" card with the full expandable event log.

**Locked answers (from user)**
* **1b** — Both invoice list AND detail get surfaced.
* **2d** — All views counted: email, SMS, portal-authenticated. Store first + last + count.
* **3c** — Full history with source + timestamp; not just a boolean.
* **4b** — Mobile parity for admin invoice screens.

## Backend

### New — ``services/invoice_view_tracker.py``

Public API:
* ``ensure_invoice_view_indexes()`` — creates two compound indexes
  (``invoice_id + viewed_at``, ``tenant_id + viewed_at``). Called
  from server startup; idempotent.
* ``record_invoice_view(*, invoice_id, tenant_id, source, user_agent, ip)``
  — inserts one ``invoice_views`` row, dedupes within 30 s per
  (invoice_id, source), atomically updates the denorm fields on
  the invoice using ``$min`` / ``$max`` / ``$inc``. Never raises.
* ``fetch_invoice_views_summary(*, invoice_id, tenant_id, limit=100)``
  — returns ``{invoice_id, first_viewed_at, last_viewed_at,
  view_count, events: [...]}`` sorted desc by ``viewed_at``.

Design guarantees:
* **Source whitelist**: ``("email", "sms", "portal", "link")`` —
  anything else collapses to ``"link"`` before storage.
* **Dedupe scoped to (invoice_id, source)** so an email open
  followed instantly by a portal login still records two events.
* **Best-effort**: Mongo failures inside the tracker are logged
  and swallowed — the read path (customer viewing an invoice) is
  never blocked on the write.
* **Field caps**: ``user_agent`` truncated at 512 chars, ``ip`` at
  64 chars.

### New — ``routers/invoice_views.py``

* ``GET /api/invoices/{iid}/views`` — admin/office/dispatcher only
  (technician + customer → 403). Returns the summary above.

### Wired into existing read paths

| Route | Source stamp |
|-------|--------------|
| ``GET /api/invoices/{iid}/full-magic?token=...&src=...`` | ``?src=email`` / ``sms`` / ``link`` — collapses to ``"link"`` on unknown values. |
| ``GET /api/invoices/{iid}/full`` (portal, ``role=customer``) | ``"portal"`` |
| ``GET /api/invoices/{iid}/full`` (admin/office/dispatcher) | **Not tracked** — internal viewers aren't a customer-engagement signal. |

### Magic-link URL builder

* ``services/pay_link_builder.build_pay_now_url`` gains an optional
  ``src`` kwarg. When present, the URL is minted as
  ``...?token=<jwt>&src=<value>``.
* ``emailer.py`` sends ``src="email"``.
* ``routers/dunning.py`` mints separate contexts per channel — the
  email template body embeds ``&src=email``, the SMS template body
  embeds ``&src=sms``.

### Invoices overview endpoint

``GET /api/invoices/overview`` now includes the three denorm
fields on every row so the mobile + web list renders the "Viewed
Nd ago" pill inline with no additional round trips.

## Web

* **``InvoicesList.jsx``** — new **Viewed** column (hidden on
  small screens, ``hidden lg:table-cell``) with a testID
  ``invoice-viewed-{id}``. Shows the eye glyph + relative
  ``Nd ago`` + optional ``(N×)`` counter for multi-view invoices.
* **``QuoteInvoiceDetail.jsx``** — mounts the new
  ``<InvoiceViewHistory invoiceId={doc.id} />`` card when
  ``isInvoice && isStaff``.
* **``components/invoices/InvoiceViewHistory.jsx``** — new
  presentational component. Fetches once on mount, shows summary
  line + collapsible event log with source badges
  (email / SMS / portal / link).
* **``pages/public/PublicInvoicePay.jsx``** — reads the ``?src=``
  query param and forwards it (whitelisted) to ``InvoiceView``.
* **``components/InvoiceView.jsx``** — accepts a new ``magicSrc``
  prop and includes it in the ``/full-magic`` request when set.

## Mobile

* **``mobile/src/components/invoices/InvoiceViewHistory.tsx``** —
  parity with the web card. Self-hides on 403 so it can be
  dropped into any invoice screen without RBAC gating at the
  callsite.
* **``mobile/app/invoice/[id].tsx``** — mounts the history card
  under the attachments section.
* **``mobile/app/invoices.tsx``** — renders a compact
  "Viewed Nd ago" pill inside each row with a testID
  ``invoice-viewed-{id}``. Only shows when
  ``item.first_viewed_at`` is populated.

## Tests

* **Backend pytest** — ``backend/tests/test_k47_invoice_view_tracking.py``
  · 9 tests, all passing:
  - insert + denorm aggregates
  - 30 s same-source dedupe
  - distinct-source dedupe scope
  - unknown/None source → "link"
  - empty invoice_id/tenant_id no-op
  - user_agent truncation
  - summary shape + ``_id`` sanitisation
  - ``build_pay_now_url`` ``src`` forwarding
* **Vitest** — ``frontend/src/test/k47-invoice-view-tracking.test.jsx``
  · 17 source-inspection guards covering the full landing state:
  backend routes/services registered, web components mounted,
  mobile parity present.

## Verification

* Backend live-fired ``GET /api/invoices/{iid}/views`` returned the
  expected empty shape ``{invoice_id, first_viewed_at: null,
  last_viewed_at: null, view_count: 0, events: []}`` on a real
  invoice.
* K46 test suites re-run and still pass (46 Jest + 62 vitest).

## Deferred / follow-ups

* **Customer-facing "your read receipt" surface** — explicitly out
  of scope per the K47 non-goals. This tracker is an internal
  collections signal, not a customer feature.
* **Email open pixel** — separate feature; K47 is link/click-based.
* **Cross-module pytest DB mutation** (K43 fallout) — still P2,
  untouched.
* **Portal invoice list "Viewed"** — the ``/portal/invoices/{id}``
  detail already stamps a ``"portal"`` view when the customer
  opens it, but no portal-side list column was added (out of the
  locked scope — 1b covers the ADMIN list + detail).
