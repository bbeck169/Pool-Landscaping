/**
 * Phase P1 · Feb-2026 — Multi-Property Support on Job Create / Edit.
 *
 * Locks the frontend contract for both entry points to the
 * ``property_id`` field:
 *
 *   1. ``JobNew.jsx`` (create form)
 *      • 0 properties → picker hidden, no ``property_id`` on payload.
 *      • 1 property   → picker hidden, ``property_id`` auto-assigned
 *                        (server also auto-assigns as belt+suspenders).
 *      • ≥2 properties → picker visible + required + primary
 *                         (``sort_order === 0``) is preselected.
 *      • Changing the customer clears any previously-picked
 *        ``property_id`` before the new fetch fires.
 *      • ``property_id`` is added to the POST /jobs payload only when
 *        set.
 *
 *   2. ``ScheduleJobEditModal.jsx`` (edit modal)
 *      • Initial ``property_id`` state pre-fills from ``job.property_id``.
 *      • Picker is ONLY rendered when the customer has ≥2 properties.
 *      • The address dropdown option label formats the property doc's
 *        canonical dict address (``line1, city, state``) — never
 *        ``"[object Object]"``.
 *      • ``property_id`` is included in the diffing loop that builds
 *        the PUT /jobs/{id} patch.
 *
 * Uses the same source-string pattern as
 * ``job-new-customer-picker.test.jsx`` so we don't have to boot the
 * full JobNew tree (which pulls in the router, api client, toast
 * provider, and a dozen shadcn primitives).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const JOBNEW = readFileSync(
  resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);
const SCHEDMODAL = readFileSync(
  resolve(__dirname, "../pages/schedule/ScheduleJobEditModal.jsx"),
  "utf8",
);

// ───────────────────────────────────────────────────────────────────
// 1 · JobNew.jsx — create-path property picker
// ───────────────────────────────────────────────────────────────────
describe("Phase P1 · JobNew — property picker create-path contract", () => {
  it("fetches the picked customer's properties on customer change", () => {
    // The effect keys off ``form.customer_id`` and hits the
    // per-customer properties endpoint.
    expect(JOBNEW).toMatch(
      /api\.get\(`\/customers\/\$\{form\.customer_id\}\/properties`\)/,
    );
    // The useEffect is wired to the customer_id dep.
    expect(JOBNEW).toMatch(/\}, \[form\.customer_id\]\);/);
  });

  it("clears the previously-picked property_id when the customer changes", () => {
    // Phase P1 explicit fix — the previous "preserve user pick"
    // clause leaked the outgoing customer's property_id into the
    // new customer's payload. The current code stamps
    // ``property_id: ""`` before refetching whenever the
    // customer_id actually changed.
    expect(JOBNEW).toMatch(/previousCustomerRef/);
    expect(JOBNEW).toMatch(
      /previousCustomerRef\.current !== form\.customer_id/,
    );
    expect(JOBNEW).toMatch(/setForm\(\(f\) => \(\{ \.\.\.f, property_id: "" \}\)\)/);
  });

  it("auto-selects when exactly ONE active property exists", () => {
    // 1-property fast path — no picker rendered, property_id
    // stamped silently so the create call succeeds.
    expect(JOBNEW).toMatch(
      /if \(active\.length === 1\)[\s\S]*?property_id:\s*active\[0\]\.id/,
    );
  });

  it("preselects the primary (sort_order 0) property when ≥2 exist", () => {
    // Multi-property preselect — the user still confirms via the
    // required picker, but the default is the primary property so
    // the common case is a single click.
    expect(JOBNEW).toMatch(/if \(active\.length >= 2\)/);
    expect(JOBNEW).toMatch(/sort_order.*?\?\?.*?99\).*?===.*?0/);
    expect(JOBNEW).toMatch(/primary\.id/);
  });

  it("renders the picker ONLY for customers with ≥2 active properties", () => {
    // Zero + one property → picker hidden. Locking the exact JSX
    // guard so a refactor can't relax it.
    expect(JOBNEW).toMatch(
      /form\.customer_id && properties\.length >= 2/,
    );
    // Picker element carries the stable testid E2E targets.
    expect(JOBNEW).toMatch(/data-testid="jf-property"/);
  });

  it("shows the 'pick a property' hint when the multi-property picker is empty", () => {
    // Required-field affordance for the ≥2 branch — user sees a
    // red hint instead of a silent submit failure.
    expect(JOBNEW).toMatch(/data-testid="jf-property-required"/);
    expect(JOBNEW).toMatch(/This customer has \{properties\.length\} properties/);
  });

  it("blocks submit + toasts when the multi-property picker is unset", () => {
    // The submit handler validates BEFORE calling the API so the
    // user never sees a raw 400 from the backend's "property_id
    // required" 422.
    expect(JOBNEW).toMatch(
      /properties\.length >= 2 && !form\.property_id/,
    );
    expect(JOBNEW).toMatch(/Pick a property for this job/);
  });

  it("includes property_id in the /jobs POST payload only when set", () => {
    // ``property_id`` is conditionally added so single-prop and
    // legacy zero-prop customers don't send a bogus empty string.
    expect(JOBNEW).toMatch(
      /if \(form\.property_id\) payload\.property_id = form\.property_id;/,
    );
    // Same shape on the recurring-template branch.
    expect(JOBNEW).toMatch(
      /if \(form\.property_id\) tplPayload\.property_id = form\.property_id;/,
    );
  });

  it("initial form state carries the preselected property_id", () => {
    // The URL / props ``property_id`` (deep-link from customer
    // detail's "New job for this property" affordance) hydrates the
    // form so the user lands on the right pick.
    expect(JOBNEW).toMatch(/property_id: preselectedProperty/);
  });
});

// ───────────────────────────────────────────────────────────────────
// 2 · ScheduleJobEditModal.jsx — edit-path property picker
// ───────────────────────────────────────────────────────────────────
describe("Phase P1 · ScheduleJobEditModal — property picker edit-path contract", () => {
  it("pre-fills property_id state from job.property_id on open", () => {
    // Both the initial useState AND the re-seed useEffect (when
    // the caller swaps to a different job) must hydrate from the
    // job doc.
    const initialStateMatches =
      SCHEDMODAL.match(/property_id:\s*job\??\.property_id\s*\|\|\s*""/g) || [];
    expect(initialStateMatches.length).toBeGreaterThanOrEqual(2);
  });

  it("fetches the customer's properties on open + on job.customer_id change", () => {
    // The customer_id must be part of the effect deps so switching
    // between jobs with different customers refetches the correct
    // property set.
    expect(SCHEDMODAL).toMatch(
      /api\.get\(`\/customers\/\$\{job\.customer_id\}\/properties`\)/,
    );
    expect(SCHEDMODAL).toMatch(/job\?\.customer_id/);
  });

  it("renders the picker ONLY when the customer has ≥2 properties", () => {
    // Hidden entirely for zero/one-property customers so the
    // schedule modal stays uncluttered.
    expect(SCHEDMODAL).toMatch(/properties\.length >= 2/);
    // Testid on the picker so E2E can target it.
    expect(SCHEDMODAL).toMatch(/data-testid="schedule-job-edit-property"/);
  });

  it("formats option labels as 'Main — line1, city, state' (no [object Object])", () => {
    // Phase P1 fix — property doc's ``address`` is a dict, so a
    // naive ``p.address || ""`` was rendering "[object Object]".
    // The current shape joins line1/city/state inline.
    expect(SCHEDMODAL).toMatch(/addrObj\.line1/);
    expect(SCHEDMODAL).toMatch(/addrObj\.city/);
    expect(SCHEDMODAL).toMatch(/addrObj\.state/);
    // Guard: no bare stringification of a dict address survives.
    // (Search only within the property picker option body — same
    // pattern as job-new-customer-picker.test.jsx's scoped block
    // trick, so we don't false-positive on the LineItems import.)
    const optIdx = SCHEDMODAL.indexOf("schedule-job-edit-property");
    expect(optIdx).toBeGreaterThan(-1);
    const optBlock = SCHEDMODAL.slice(optIdx, optIdx + 1200);
    expect(optBlock).not.toMatch(/\{p\.address \|\| ""\}/);
  });

  it("emits per-option testids for deterministic E2E selection", () => {
    // ``schedule-job-edit-property-{id}`` on each option so the
    // testing agent can click by id.
    expect(SCHEDMODAL).toMatch(
      /data-testid=\{`schedule-job-edit-property-\$\{p\.id\}`\}/,
    );
  });

  it("includes property_id in the PUT /jobs/{id} diff loop", () => {
    // Only-changed-fields diff — must list property_id so a retag
    // reaches the backend.
    expect(SCHEDMODAL).toMatch(
      /\["title", "service_type", "scheduled_date",\s*"technician_id", "notes", "status",\s*"work_class", "property_id", "crew_id"\]/,
    );
    // Uses PUT (matches the retag path the backend accepts). The
    // 24h post-completion PATCH endpoint does NOT accept
    // property_id — locked behavior.
    expect(SCHEDMODAL).toMatch(/api\.put\(`\/jobs\/\$\{job\.id\}`, patch\)/);
  });
});
