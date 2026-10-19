# Mobile TD-79 Audit — customer profile Overview · invoice list (last 10 + View all)

Web ship of record: `db3ef6d2f`. Audit at HEAD `9e40b2d6a`; hygiene clean (non-pyc status = 3 known untracked `.env.example`).

| # | Lookup | Result |
|---|---|---|
| 1 | Mobile customer profile Overview | `app/customer/[id].tsx` (Overview tab). Web anchor (below identity/contact, above `PaymentMethodTiles`) maps to: after the `<MultiContact>` LightPanel, before `customer-payment-method` card. Admin-gated like the adjacent payment controls |
| 2 | Mobile invoice list route | `app/invoices.tsx` (`/invoices`). Reads `GET /api/invoices/overview` (admin, AR overview, **no customer param**) and parsed **no** route params → needed `?customer_id=` wiring (client-side; BE untouched) → split commit `m-invoices-filter` |
| 3 | Mobile invoice detail route | Admin detail = `app/quote/[id].tsx` → `router.push(\`/quote/${id}\`)` (what the invoice list rows use). `app/invoice/[id].tsx` is the customer-facing pay view — not used |
| 4 | Title resolver | Already ported in TD-71 mobile cycle: `src/lib/portalInvoiceTitle.ts` (`resolvePortalInvoiceTitle`) — reused, no port commit |
| 5 | BE filter | `GET /api/quotes?doc_type=invoice&customer_id=<cid>&limit=10&offset=0` live → `{rows, total_count, has_more}` (148 / 3 / 0 verified). Mobile had no prior consumer of this filter; new component uses it exactly like web |
| 6 | No-web-parallel screens | `app/customer/[id]/payment-methods.tsx`, `app/customer/[id]/compose.tsx` — not touched |

Caveat: "View all" lands on mobile `/invoices`, which is the AR overview (`/invoices/overview`) — it omits fully-settled invoices (live: a 4-invoice customer shows 2). Web InvoicesList shows every status. Closing that gap needs either a different mobile list data source or a BE param (out of scope).

Commits: `m-invoices-filter` (751c12952) → `m-td79`.
