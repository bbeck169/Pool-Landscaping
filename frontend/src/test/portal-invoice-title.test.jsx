/**
 * TD-71 · Feb-2026 — Customer-portal invoice-row title resolver +
 * created-date formatter regression lock.
 *
 * Pre-TD-71 the ``/portal/invoices`` row rendered:
 *   * ``r.title`` directly — imported invoices with the ugly
 *     ``Import #259`` placeholder leaked straight to customers.
 *   * ``No due date`` as the only date line when ``due_date`` was
 *     missing — no ``created_at`` context so customers couldn't
 *     tell when the invoice was raised.
 *
 * This file pins the full contract (title fallback chain across
 * all four branches + created-date formatter + the wire-up in
 * ``PortalPages.jsx``).
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

import {
  resolvePortalInvoiceTitle,
  isImportedPlaceholderTitle,
  formatInvoiceCreatedDate,
} from "../lib/portalInvoiceTitle";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const PP_SRC = R("../pages/portal/PortalPages.jsx");


// ═══════════════════════════════════════════════════════════════════
// 1 · isImportedPlaceholderTitle — pure predicate.
// ═══════════════════════════════════════════════════════════════════
describe("TD-71 · isImportedPlaceholderTitle", () => {
  it("matches canonical 'Import #259'", () => {
    expect(isImportedPlaceholderTitle({ title: "Import #259" })).toBe(true);
  });
  it("matches whitespace variants + case-insensitive", () => {
    expect(isImportedPlaceholderTitle({ title: "  Import #  259  " })).toBe(true);
    expect(isImportedPlaceholderTitle({ title: "import #259" })).toBe(true);
    expect(isImportedPlaceholderTitle({ title: "IMPORT#259" })).toBe(true);
  });
  it("does NOT match legitimate titles that happen to contain 'Import'", () => {
    // Guards against false-positives — real customer-facing titles
    // like "Imported water-feature spec" must pass through
    // untouched. The regex pins start-of-string + end-of-string so
    // only the exact ugly shape is matched.
    expect(isImportedPlaceholderTitle({ title: "Imported pool chemicals" })).toBe(false);
    expect(isImportedPlaceholderTitle({ title: "Pool service Import #259" })).toBe(false);
    expect(isImportedPlaceholderTitle({ title: "Weekly service" })).toBe(false);
  });
  it("null-safe", () => {
    expect(isImportedPlaceholderTitle(null)).toBe(false);
    expect(isImportedPlaceholderTitle({})).toBe(false);
    expect(isImportedPlaceholderTitle({ title: null })).toBe(false);
    expect(isImportedPlaceholderTitle({ title: "" })).toBe(false);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2 · resolvePortalInvoiceTitle — fallback chain × 4 branches.
// ═══════════════════════════════════════════════════════════════════
describe("TD-71 · resolvePortalInvoiceTitle · fallback chain", () => {

  const _import = (extra = {}) => ({ title: "Import #259", ...extra });

  it("Branch 1 — service_description wins when present", () => {
    expect(resolvePortalInvoiceTitle(_import({
      service_description: "Monthly pool service — March",
      line_items: [{ title: "Line item A" }],  // ignored
      notes: "Billed per contract",             // ignored
    }))).toBe("Monthly pool service — March");
  });

  it("Branch 1b — service_summary is the fallback alias", () => {
    expect(resolvePortalInvoiceTitle(_import({
      service_summary: "Spa reheat",
    }))).toBe("Spa reheat");
  });

  it("Branch 2 — line_items[0].title when no service_description", () => {
    expect(resolvePortalInvoiceTitle(_import({
      line_items: [{ title: "Weekly landscape maintenance" }],
    }))).toBe("Weekly landscape maintenance");
  });

  it("Branch 2b — line_items[0].description as the fallback alias", () => {
    expect(resolvePortalInvoiceTitle(_import({
      line_items: [{ description: "Chemical dosing — Mar 2026" }],
    }))).toBe("Chemical dosing — Mar 2026");
  });

  it("Branch 3 — notes (trimmed, kept intact when ≤ 80 chars)", () => {
    expect(resolvePortalInvoiceTitle(_import({
      notes: "  Billed per contract  ",
    }))).toBe("Billed per contract");
  });

  it("Branch 3b — notes truncated to 80 chars with ellipsis when > 80", () => {
    const longNote = "A".repeat(85);
    const result = resolvePortalInvoiceTitle(_import({ notes: longNote }));
    expect(result).toBe("A".repeat(80) + "…");
    expect(result.length).toBe(81);  // 80 chars + 1 ellipsis
  });

  it("Branch 4 — neutral 'Invoice' fallback when nothing else is populated", () => {
    expect(resolvePortalInvoiceTitle(_import({}))).toBe("Invoice");
    expect(resolvePortalInvoiceTitle(_import({ line_items: [] }))).toBe("Invoice");
    expect(resolvePortalInvoiceTitle(_import({ notes: "" }))).toBe("Invoice");
  });

  it("Non-imported invoice — title passes through untouched", () => {
    expect(resolvePortalInvoiceTitle({ title: "Weekly service · March 14" }))
      .toBe("Weekly service · March 14");
    expect(resolvePortalInvoiceTitle({ title: "Pool chemicals invoice #42" }))
      .toBe("Pool chemicals invoice #42");
  });

  it("Returns 'Invoice' for null / non-object / missing title", () => {
    expect(resolvePortalInvoiceTitle(null)).toBe("Invoice");
    expect(resolvePortalInvoiceTitle({})).toBe("Invoice");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 3 · formatInvoiceCreatedDate — Created MM/DD/YYYY.
// ═══════════════════════════════════════════════════════════════════
describe("TD-71 · formatInvoiceCreatedDate", () => {
  it("formats created_at as 'Created MM/DD/YYYY'", () => {
    // Use a mid-year date to avoid TZ-rollover ambiguity on the
    // test host. March 14 2025 is far from any midnight edge.
    expect(formatInvoiceCreatedDate({ created_at: "2025-03-14T12:00:00Z" }))
      .toBe("Created 03/14/2025");
  });

  it("zero-pads single-digit months + days", () => {
    expect(formatInvoiceCreatedDate({ created_at: "2025-01-05T12:00:00Z" }))
      .toBe("Created 01/05/2025");
  });

  it("falls back to invoice_date when created_at is missing", () => {
    expect(formatInvoiceCreatedDate({ invoice_date: "2024-11-20T12:00:00Z" }))
      .toBe("Created 11/20/2024");
  });

  it("prefers created_at over invoice_date when both present", () => {
    expect(formatInvoiceCreatedDate({
      created_at: "2025-03-14T12:00:00Z",
      invoice_date: "2024-11-20T12:00:00Z",
    })).toBe("Created 03/14/2025");
  });

  it("returns '' when both fields are missing / unparseable", () => {
    expect(formatInvoiceCreatedDate({})).toBe("");
    expect(formatInvoiceCreatedDate({ created_at: null })).toBe("");
    expect(formatInvoiceCreatedDate({ created_at: "" })).toBe("");
    expect(formatInvoiceCreatedDate({ created_at: "not-a-date" })).toBe("");
  });

  it("null-safe", () => {
    expect(formatInvoiceCreatedDate(null)).toBe("");
    expect(formatInvoiceCreatedDate(undefined)).toBe("");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 4 · PortalPages.jsx wire-up locks.
// ═══════════════════════════════════════════════════════════════════
describe("TD-71 · PortalPages.jsx wires through the shared helpers", () => {
  it("imports both helpers from the shared module", () => {
    expect(PP_SRC).toMatch(
      /import\s*\{\s*(?:[\w,\s]*,\s*)?resolvePortalInvoiceTitle(?:[\s\S]*?)\}\s*from\s*["']@\/lib\/portalInvoiceTitle["']/,
    );
    expect(PP_SRC).toMatch(
      /import\s*\{\s*(?:[\w,\s]*,\s*)?formatInvoiceCreatedDate(?:[\s\S]*?)\}\s*from\s*["']@\/lib\/portalInvoiceTitle["']/,
    );
  });

  it("LIST row renders via shared <InvoiceTable /> primitive (Ticket FF)", () => {
    // Ticket FF · Feb-2026 — the pre-TD-71 ``<li>`` card list was
    // replaced with the shared ``<InvoiceTable />`` primitive.
    // The title still flows through ``getInvoiceDisplayTitle``
    // (now owned by the primitive) and the FF case-reorder
    // handles the ``Import #<n>`` retroactive promise.  The
    // ``resolvePortalInvoiceTitle`` composition that TD-71 added
    // to this surface is intentionally dropped — Date column
    // replaces the ``Created MM/DD/YYYY`` affordance per FF spec.
    expect(PP_SRC).toMatch(
      /import\s+InvoiceTable\s+from\s+"@\/components\/invoices\/InvoiceTable"/,
    );
    expect(PP_SRC).toMatch(
      /<InvoiceTable[\s\S]{0,300}testidPrefix="portal-invoices"/,
    );
    expect(PP_SRC).toMatch(
      /viewHref=\{\(r\)\s*=>\s*`\/portal\/invoices\/\$\{r\.id\}`\}/,
    );
  });

  it("Pre-FF ``_displayTitle`` + ``_createdLine`` card wiring is retired on /portal/invoices", () => {
    // The PortalInvoices body should no longer carry the TD-71
    // ``_displayTitle = resolvePortalInvoiceTitle(r)`` composition
    // or the ``_createdLine`` line.  ``PortalEstimates`` below is
    // unchanged (its own test block in §5 locks that).
    const invBlock = PP_SRC.match(
      /export function PortalInvoices\(\)[\s\S]*?^\}/m,
    );
    expect(invBlock).not.toBeNull();
    expect(invBlock[0]).not.toMatch(/_displayTitle/);
    expect(invBlock[0]).not.toMatch(/_createdLine/);
    expect(invBlock[0]).not.toMatch(/port-inv-title-/);
    expect(invBlock[0]).not.toMatch(/port-inv-created-/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 5 · TD-72b · PortalEstimates reuses the same title resolver.
// ═══════════════════════════════════════════════════════════════════
describe("TD-72b · PortalEstimates reuses resolvePortalInvoiceTitle", () => {
  it("Estimates list row reads title via resolvePortalInvoiceTitle(r)", () => {
    // Positive — the LIST row title now flows through the shared
    // helper (same abstraction as /portal/invoices). Scope the
    // match to the PortalEstimates block by anchoring on the
    // ``navigate(`/portal/estimates/${r.id}`)`` click handler.
    //
    // SS · Feb-2026 — de-staled to accept both the pre-TD-72b bare-
    // arg shape ``resolvePortalInvoiceTitle(r)`` AND the TD-72b-
    // adjacent spread-and-override shape ``resolvePortalInvoiceTitle(
    // { ...r, title: getInvoiceDisplayTitle(r) })`` (imported-
    // placeholder title normalisation layered in front of the
    // fallback chain).  The invariant is that the Estimates
    // click-navigation row's title flows through the shared
    // resolver — not the specific argument shape.
    expect(PP_SRC).toMatch(
      /_displayTitle\s*=\s*resolvePortalInvoiceTitle\([\s\S]{0,160}?r[\s\S]{0,500}?navigate\(`\/portal\/estimates\/\$\{r\.id\}`\)/,
    );
    expect(PP_SRC).toMatch(/data-testid=\{`port-est-title-\$\{r\.id\}`\}/);
  });

  it("Pre-TD-72b bare `{r.title}` render inside the port-est list row is gone", () => {
    // Negative lock — the one remaining ``{r.title}`` render in
    // the file is OUTSIDE the port-est row (it's in the related
    // detail / preview surfaces which are out of scope).
    const estRowMatch = PP_SRC.match(
      /data-testid=\{`port-est-\$\{r\.id\}`\}[\s\S]{0,500}?<\/li>/,
    );
    expect(estRowMatch).not.toBeNull();
    expect(estRowMatch[0]).not.toMatch(/>\s*\{r\.title\}\s*</);
    expect(estRowMatch[0]).toMatch(/>\s*\{_displayTitle\}\s*</);
  });

  it("Resolver branches apply equally to estimate records (unit smoke)", () => {
    // Estimates have the same ``title`` / ``line_items`` / ``notes``
    // / ``created_at`` schema shape as invoices (both live in
    // ``db.quotes`` with different ``doc_type``). The shared
    // helper is schema-agnostic.
    expect(resolvePortalInvoiceTitle({
      title: "Import #42",
      line_items: [{ description: "Pool renovation quote" }],
    })).toBe("Pool renovation quote");
    expect(resolvePortalInvoiceTitle({
      title: "Import #42",
      notes: "Scope — rebuild tile line",
    })).toBe("Scope — rebuild tile line");
    expect(resolvePortalInvoiceTitle({
      title: "Import #42",
      created_at: "2025-07-04T00:00:00Z",
    })).toBe("Invoice");  // FE helper's fallback literal (not the BE "Service — MM/DD/YYYY" fallback — see TD-72)
    // Non-imported estimate title passes through unchanged.
    expect(resolvePortalInvoiceTitle({
      title: "Spa refresh · Q2 2026",
    })).toBe("Spa refresh · Q2 2026");
  });
});
