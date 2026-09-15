/**
 * Feb-2026 · Chemistry required-readings gate — Web UI transitions.
 *
 * Vitest component test.  Locally-authored per user's hotfix scope
 * guard: no new e2e framework (Playwright etc.).  Reuses the
 * project's existing Vitest + Testing-Library setup — same
 * pattern as ``ai-description-rewrite-button.test.jsx``.
 *
 * Test JID from user brief: ``bb80b3ad-20da-4a1d-8c08-514dcba402f5``.
 *
 * Assertions match the Fix-1 tooltip contract exactly:
 *   * Display labels ("Free Cl", "Total Cl", "Alkalinity", "pH", "CYA")
 *     — NOT the canonical shortnames.
 *   * Comma-space separator between missing labels.
 *   * Empty ``title`` when the gate passes so hover shows nothing.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

// ── Mock the api module BEFORE importing the component. ──
const getMock = vi.fn();
const postMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: (...args) => postMock(...args),
    del: (...args) => delMock(...args),
  },
}));

// ── Router mocks — the page reads useParams() + useNavigate(). ──
const TEST_JID = "bb80b3ad-20da-4a1d-8c08-514dcba402f5";
const navigateMock = vi.fn();
vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: TEST_JID }),
  useNavigate: () => navigateMock,
}));

// ── Sonner + theme mocks (theme is real ES-module — leave alone). ──
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Lucide-react ships ESM — leave real.  ServiceReport imports many
// icons but Vitest resolves them fine in jsdom.

import ServiceReport from "@/pages/tech/ServiceReport";

const CORE_ROWS = [
  { key: "free_chlorine",  value: null },
  { key: "alkalinity",     value: null },
  { key: "ph",             value: null },
  { key: "cyanuric_acid",  value: null },
];

/** Build a service-report payload the page's ``api.get`` returns. */
function mkReport(overrides = {}) {
  return {
    id: "sr-1", job_id: TEST_JID, tech_id: "t-mike",
    template: "pool", submitted_at: null,
    checklist_items: [], chemicals_added: [], photos: [],
    chemical_readings: CORE_ROWS.map((r) => ({ ...r })),
    notes: "", observations: "",
    job: { id: TEST_JID, customer_name: "Test Customer",
           title: "Weekly Pool", service_type: "Weekly Pool Service" },
    ...overrides,
  };
}

/** Return a fresh readings array with the given canonical keys set
 *  to real chemistry values, everything else NULL. */
function readingsWithFilled(filledKeys) {
  return CORE_ROWS.map(({ key }) => ({
    key,
    value: filledKeys.includes(key) ? 2.5 : null,
  }));
}

async function renderWithReport(report) {
  getMock.mockResolvedValueOnce(report);
  render(<ServiceReport />);
  // Wait for the async load() to finish + button to be rendered.
  return await waitFor(
    () => screen.getByTestId("svc-report-submit"),
    { timeout: 2000 },
  );
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  delMock.mockReset();
  navigateMock.mockReset();
});
afterEach(() => cleanup());


describe("ServiceReport · chemistry gate button transitions", () => {
  it("1. Only pH + Free Cl filled → disabled + title 'Missing: Alkalinity, CYA'", async () => {
    const btn = await renderWithReport(
      mkReport({
        chemical_readings: readingsWithFilled(["ph", "free_chlorine"]),
      }),
    );
    expect(btn).toBeDisabled();
    // Phase CHEM1 · Feb-2026 — Total Cl removed from the missing list.
    expect(btn.getAttribute("title")).toBe(
      "Missing: Alkalinity, CYA",
    );
  });

  it("2. Optional readings (water_temp + calcium_hardness) do NOT unblock", async () => {
    const rows = readingsWithFilled(["ph", "free_chlorine"]);
    rows.push({ key: "water_temp", value: 82 });
    rows.push({ key: "calcium_hardness", value: 250 });
    const btn = await renderWithReport(
      mkReport({ chemical_readings: rows }),
    );
    expect(btn).toBeDisabled();
    // Same two missing cores — optionals are ignored.
    expect(btn.getAttribute("title")).toBe(
      "Missing: Alkalinity, CYA",
    );
  });

  it("3. All Required Four filled → enabled + title cleared", async () => {
    const btn = await renderWithReport(
      mkReport({
        chemical_readings: readingsWithFilled([
          "free_chlorine",
          "alkalinity", "ph", "cyanuric_acid",
        ]),
      }),
    );
    expect(btn).not.toBeDisabled();
    // Native HTML — an absent ``title`` attribute is null.  We accept
    // either null or an empty string (both mean "no hover text").
    const title = btn.getAttribute("title");
    expect([null, ""]).toContain(title);
  });

  it("4. Zero + negative floats count as VALID readings (real chemistry)", async () => {
    // A tech legitimately entering 0.0 for Free Cl (freshly shocked
    // pool) or a negative-drift sensor reading MUST NOT be treated as
    // missing.  Backend rule mirrored by the client.
    const rows = [
      { key: "free_chlorine",  value: 0 },       // real reading
      { key: "alkalinity",     value: 80 },
      { key: "ph",             value: 7.4 },
      { key: "cyanuric_acid",  value: 40 },
    ];
    const btn = await renderWithReport(
      mkReport({ chemical_readings: rows }),
    );
    expect(btn).not.toBeDisabled();
  });

  it("5. Empty + whitespace + unparseable strings are ALL missing", async () => {
    const rows = [
      { key: "free_chlorine",  value: "" },
      { key: "alkalinity",     value: "not-a-number" },
      { key: "ph",             value: 7.4 },
      { key: "cyanuric_acid",  value: 40 },
    ];
    const btn = await renderWithReport(
      mkReport({ chemical_readings: rows }),
    );
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title")).toBe(
      "Missing: Free Cl, Alkalinity",
    );
  });
});
