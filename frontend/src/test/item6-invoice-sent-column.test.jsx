// Backlog Item #6 · Feb-2026 — Invoice list "Sent" column.
//
// Locks the FE-side wiring for the Sent column via source
// inspection (same style as `k47-invoice-view-tracking.test.jsx`
// for the Viewed column that landed in Phase K47):
//
//   * The column header + sortable control exist.
//   * The body cell reads the four denorm fields written by
//     backend/services/invoice_sent_denorm.py:
//       - last_sent_via ("email" | "sms" | "both")
//       - last_sent_at
//       - last_email_sent_at
//       - last_sms_sent_at
//   * The empty state ("—") renders when `last_sent_at` is absent
//     (historical invoices with no denorm — operator spec · no
//     backfill).
//   * The three via states (email / sms / both) each render a
//     distinct icon chain.
//   * The sort key resolver is wired into the sort switch.
//
// Source-inspection style avoids pulling in the entire InvoicesList
// render tree (which depends on dozens of imports + API mocks) and
// matches the sibling K47 / TD-95 suites.

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(__dirname, "../../..");
const R = (rel) => readFileSync(resolve(ROOT, rel), "utf8");


describe("Item #6 · Backend denorm shape", () => {
  it("services/invoice_sent_denorm.py exports stamp_invoice_sent", () => {
    const src = R("backend/services/invoice_sent_denorm.py");
    expect(src).toContain("async def stamp_invoice_sent");
    // All four denorm fields are mentioned by name.
    expect(src).toContain("last_sent_at");
    expect(src).toContain("last_sent_via");
    expect(src).toContain("last_email_sent_at");
    expect(src).toContain("last_sms_sent_at");
    // Idempotent $max writes + $set for via.
    expect(src).toContain('"$max"');
    expect(src).toContain('"$set": {"last_sent_via": via}');
  });
});


describe("Item #6 · FE InvoicesList — Sent column wiring", () => {
  const SRC = R("frontend/src/pages/invoices/InvoicesList.jsx");

  it("imports Mail + MessageSquare icons from lucide-react", () => {
    // Both icons must be destructured out of the lucide-react
    // import at the top of the file.
    expect(SRC).toMatch(/import\s*\{[^}]*Mail[^}]*\}\s*from\s*"lucide-react"/);
    expect(SRC).toMatch(/import\s*\{[^}]*MessageSquare[^}]*\}\s*from\s*"lucide-react"/);
  });

  it("declares the _sentSortValue resolver", () => {
    expect(SRC).toContain("function _sentSortValue(r)");
    expect(SRC).toContain('return r.last_sent_at || "";');
  });

  it("wires 'sent' into the sort switch", () => {
    expect(SRC).toMatch(/case "sent":\s*return _sentSortValue\(r\);/);
  });

  it("renders a sortable 'Sent' column header adjacent to Viewed", () => {
    // Both <_SortableTh>s must exist AND Sent must come AFTER
    // Viewed so the on-screen column order is Viewed → Sent.
    const viewedIdx = SRC.indexOf('col="viewed"');
    const sentIdx = SRC.indexOf('col="sent"');
    expect(viewedIdx).toBeGreaterThan(-1);
    expect(sentIdx).toBeGreaterThan(-1);
    expect(sentIdx).toBeGreaterThan(viewedIdx);
    // The header label is exactly "Sent".
    expect(SRC).toMatch(/label="Sent"\s+col="sent"/);
  });

  it("exposes a stable testid on the body cell", () => {
    expect(SRC).toContain('data-testid={`invoice-sent-${r.id}`}');
    expect(SRC).toContain('data-testid={`invoice-sent-via-${r.id}`}');
    expect(SRC).toContain('data-testid={`invoice-sent-empty-${r.id}`}');
  });

  it("renders '—' empty state when last_sent_at is null (historical)", () => {
    // Branch guard is on `r.last_sent_at`.
    expect(SRC).toMatch(/\{r\.last_sent_at\s*\?/);
    // Em dash in the empty-state <span>.
    expect(SRC).toContain("invoice-sent-empty-");
    expect(SRC).toMatch(/—\s*<\/span>/);
  });

  it("branches on last_sent_via for the three channel states", () => {
    // email branch.
    expect(SRC).toMatch(/r\.last_sent_via === "email"/);
    // sms branch.
    expect(SRC).toMatch(/r\.last_sent_via === "sms"/);
    // both branch — renders Mail + MessageSquare side by side.
    expect(SRC).toMatch(/r\.last_sent_via === "both"/);
  });

  it("surfaces per-channel timestamps in the title attribute", () => {
    expect(SRC).toContain("last_email_sent_at");
    expect(SRC).toContain("last_sms_sent_at");
    // Title string references the per-channel ISO fields.
    expect(SRC).toMatch(/email:\s*\$\{r\.last_email_sent_at\}/);
    expect(SRC).toMatch(/sms:\s*\$\{r\.last_sms_sent_at\}/);
  });

  it("tags the via state via a data-sent-via attribute (for ops/testing)", () => {
    expect(SRC).toContain('data-sent-via={r.last_sent_via || "unknown"}');
  });
});
