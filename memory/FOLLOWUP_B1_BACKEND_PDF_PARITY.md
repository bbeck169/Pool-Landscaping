# B1-follow · Backend PDF parity for Invoice/Estimate B1 sizing

**Priority**: P2
**Logged**: Feb-2026 (alongside Task B1 CSS-only commit `<TBD>`)
**Origin**: Task B1 · CSS-only Logo 3x + font +2px on Invoices/Estimates.

---

## Summary

Task B1 shipped 3x logo + +2px body-copy font on the **browser-render**
Invoice + Estimate surfaces via `.iv-*` / `.ev-*` CSS class bumps in:

- `frontend/src/components/InvoiceView.css` — 1 logo rule (72→216,
  220→min(660px, 100%)) + 9 reading-block font-size bumps.
- `frontend/src/components/EstimateView.css` — 4 reading-block font-size
  bumps.

Those changes cover:
- On-screen preview (admin `<InvoiceView>` / `<EstimateView>`)
- Public magic-link customer-facing view (same components)
- Browser-print output (via base-rule propagation — no `@media print`
  overrides on the touched rules)

**Not covered — this follow-up's scope**: the ReportLab-generated
**Download-PDF** output produced by `backend/routers/quotes.py`.

## Gap

`backend/routers/quotes.py:1917–2157` renders the Download-PDF for both
`doc_type="invoice"` and `doc_type="quote"` via ReportLab (Python
`SimpleDocTemplate` + `Table` + `Paragraph` + `TableStyle`). Font sizes
are hardcoded in `TableStyle(("FONT", ..., "Helvetica", 10))` and the
default `getSampleStyleSheet()`. Logo dimensions live in
`backend/services/tenants/pdf_theme.py::build_header_footer_hooks` via
`logo_absolute_url` and header-band constants (`HEADER_BAND_HEIGHT`).

Result: customers who click "Download PDF" get the pre-B1 sizing;
customers who view on-screen or print-via-browser get the B1 sizing.
Visual inconsistency across channels.

## Required work

1. **Sizing math translation** — CSS px → ReportLab points
   (1 pt = 1.333px). B1 CSS bumps translate to:
   - `.iv-brand-logo` 216px max-height → ~162 pt max-height
   - `.iv-lines` / `.iv-notes` / `.iv-totals` 14.5px → ~10.9 pt
   - `.iv-total-due td` / `.ev-total-highlight td` 16px → 12 pt
   - `.iv-header-left` / `.iv-bill-to` / `.iv-prop-addr` 15px → ~11.25 pt
   - `.iv-kv` / `.iv-stub-cols` / `.ev-group-desc` 14px → ~10.5 pt
   - `.ev-line-card-desc` 16px → 12 pt (mobile-card path; may not
     apply to PDF — verify during implementation)

2. **File touches** (expected):
   - `backend/routers/quotes.py` — bump `TableStyle(("FONT", ..., 10))`
     entries and any `Paragraph` inline sizes; the ReportLab
     "header/body/total-due" rows map to the CSS bumps by row role.
   - `backend/services/tenants/pdf_theme.py` — bump `HEADER_BAND_HEIGHT`
     and the internal logo-render call to accept the new max-height.

3. **New test file**: `backend/tests/test_quote_pdf_b1_sizing.py` —
   pytest that invokes the PDF endpoint against a fixture tenant +
   fixture quote/invoice, parses the returned PDF bytes (via
   `pypdf` or `pdfplumber`), and asserts:
   - Extracted text renders in the expected font-size (approximate;
     ReportLab embeds the font-size in the content stream — direct
     probe possible via `pdfplumber.Page.chars[0]["size"]`).
   - The header-band image draw-op declares dimensions >= 162 pt.
   - Idempotency — endpoint returns the same size twice in a row for
     the same fixture.

4. **Regression** — run the existing invoice/quote PDF backend test
   set to confirm zero regressions on the pre-B1 assertions:
   - `backend/tests/test_iteration29_invoices_ar.py`
   - `backend/tests/test_estimator.py` (partially — checks PDF or
     HTML fallback)
   - Any `test_quote*pdf*.py` sibling files.

## Halt-and-ask trigger

Per Task B1's Phase 0 guardrail, backend touch on
`backend/routers/quotes.py` requires explicit user go-signal.
**Do NOT start B1-follow without a fresh brief.** This log entry is
tracking-only.

## Related

- Task B1 CSS-only commit: (paste SHA on land)
- Task B1 recon report: chat message preceding B1's Phase 1 rulings
- Task B1 ruling on scope (R7-1 · Option C): "browser surfaces only
  in this commit; log the PDF parity gap as a follow-up".
