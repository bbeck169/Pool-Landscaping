/**
 * Phase AIM0 · Feb-2026 — AI Measure page (POC) vitest suite.
 *
 * Covers:
 *  1. Source-level testid contract (address input, run button, both
 *     provider canvases, per-feature readouts, feedback buttons).
 *  2. Renders the address input + Run button + both provider panels
 *     for an admin (react-testing-library).
 *  3. Feedback buttons update in-memory state (feedback log shows).
 *  4. Non-privileged role (technician) shows the 403-shaped guard
 *     block instead of the page body.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── Source-level testid regression ────────────────────────────────
const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/AiMeasurePage.jsx"),
  "utf-8",
);

describe("AiMeasurePage · source-level contract", () => {
  it("exposes every required data-testid", () => {
    expect(SRC).toMatch(/data-testid="ai-measure-page"/);
    expect(SRC).toMatch(/data-testid="ai-measure-run"/);
    // Address input testid (via inputTestId prop to AddressAutocomplete).
    expect(SRC).toMatch(/testid="ai-measure-address"/);
    // Both provider canvases.
    expect(SRC).toMatch(/data-testid=\{`ai-measure-canvas-\$\{provider\}`\}/);
    // Per-feature readout + feedback testids.
    expect(SRC).toMatch(
      /data-testid=\{`ai-measure-result-\$\{provider\}-\$\{feature\.type\}`\}/,
    );
    expect(SRC).toMatch(
      /data-testid=\{`ai-measure-feedback-up-\$\{provider\}-\$\{feature\.type\}`\}/,
    );
    expect(SRC).toMatch(
      /data-testid=\{`ai-measure-feedback-down-\$\{provider\}-\$\{feature\.type\}`\}/,
    );
  });

  it("locks the polygon-overlay colour palette verbatim", () => {
    expect(SRC).toMatch(/rgba\(37,\s*99,\s*235,\s*0\.35\)/);   // pool fill
    expect(SRC).toMatch(/"#2563EB"/);                            // pool stroke
    expect(SRC).toMatch(/rgba\(217,\s*119,\s*6,\s*0\.35\)/);    // deck fill
    expect(SRC).toMatch(/"#D97706"/);                            // deck stroke
    expect(SRC).toMatch(/rgba\(22,\s*163,\s*74,\s*0\.35\)/);    // yard fill
    expect(SRC).toMatch(/"#16A34A"/);                            // yard stroke
  });

  it("uses AddressAutocomplete (P0 shared component)", () => {
    expect(SRC).toMatch(/import\s+AddressAutocomplete\s+from\s+"@\/components\/AddressAutocomplete"/);
  });

  it("does not persist detections to a job / quote / estimate", () => {
    // In-memory history + feedback only — no /api/quotes, /api/jobs, /api/estimates.
    expect(SRC).not.toMatch(/\/api\/quotes/);
    expect(SRC).not.toMatch(/\/api\/jobs/);
    expect(SRC).not.toMatch(/\/api\/estimates/);
    // Endpoint MUST be the POC preview only.
    expect(SRC).toMatch(/\/tools\/ai-measure\/preview/);
  });

  it("locks the admin+super_admin+owner role guard triple", () => {
    // Every role in the triple must appear in the guard.
    expect(SRC).toMatch(/role === "admin"/);
    expect(SRC).toMatch(/role === "super_admin"/);
    expect(SRC).toMatch(/role === "owner"/);
  });
});


// ─── Render-level tests ────────────────────────────────────────────
let currentRole = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: currentRole, email: `${currentRole}@x.y` },
    loading: false,
  }),
}));

// Neutralise AddressAutocomplete's Google Maps loader — render as a
// plain input with the expected testid so our tests don't need a
// network + window.google shim.
vi.mock("@/components/AddressAutocomplete", () => ({
  default: (props) => (
    <input
      data-testid={`${props.testid || "address-autocomplete"}-input`}
      value={props.value || ""}
      onChange={(e) => props.onChange?.(e.target.value)}
      placeholder={props.placeholder || ""}
    />
  ),
}));

// Neutralise the api module so the "Run" click doesn't hit the network.
const apiPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: (...args) => apiPost(...args),
    put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
  },
}));

// Import AFTER mocks so the module picks them up.
import AiMeasurePage from "../pages/admin/AiMeasurePage";


function _renderPage() {
  return render(
    <MemoryRouter>
      <AiMeasurePage />
    </MemoryRouter>,
  );
}


describe("AiMeasurePage · render + interaction", () => {
  beforeEach(() => {
    currentRole = "admin";
    apiPost.mockReset();
  });
  afterEach(() => cleanup());

  it("renders address input + run button + both provider panels for admin", () => {
    _renderPage();
    expect(screen.getByTestId("ai-measure-page")).toBeTruthy();
    expect(screen.getByTestId("ai-measure-address-input")).toBeTruthy();
    expect(screen.getByTestId("ai-measure-run")).toBeTruthy();
    expect(screen.getByTestId("ai-measure-canvas-openai_gpt-4o")).toBeTruthy();
    expect(screen.getByTestId("ai-measure-canvas-anthropic_claude")).toBeTruthy();
  });

  it("owner role also renders the page (not blocked by AdminOnly)", () => {
    currentRole = "owner";
    _renderPage();
    expect(screen.getByTestId("ai-measure-page")).toBeTruthy();
  });

  it("super_admin role also renders the page", () => {
    currentRole = "super_admin";
    _renderPage();
    expect(screen.getByTestId("ai-measure-page")).toBeTruthy();
  });

  it("technician role is blocked (shows forbidden state, no page body)", () => {
    currentRole = "technician";
    _renderPage();
    expect(screen.queryByTestId("ai-measure-page")).toBeNull();
    expect(screen.getByTestId("ai-measure-forbidden")).toBeTruthy();
  });

  it("customer role is blocked", () => {
    currentRole = "customer";
    _renderPage();
    expect(screen.queryByTestId("ai-measure-page")).toBeNull();
    expect(screen.getByTestId("ai-measure-forbidden")).toBeTruthy();
  });

  it("clicking a feedback thumb records the feedback entry", async () => {
    // Stub the API to return a canned result with one pool feature.
    apiPost.mockResolvedValueOnce({
      address_resolved: "1600 Fake St",
      lat: 33.4, lng: -112.07, zoom: 20,
      image_size: [1280, 1280],
      mpp_effective: 0.0298,
      satellite_image_data_url: "data:image/jpeg;base64,AAAA",
      requested_features: ["pool"],
      providers: [
        {
          provider: "openai_gpt-4o", latency_ms: 300, features: [
            { type: "pool", polygon: [[0, 0], [10, 0], [10, 10], [0, 10]],
              area_sqft: 500, area_sqyd: 55.6, confidence: 0.88, notes: "clean" },
          ],
        },
        { provider: "anthropic_claude", latency_ms: 400, features: [] },
      ],
    });

    _renderPage();
    // Type an address so validation passes.
    fireEvent.change(screen.getByTestId("ai-measure-address-input"),
      { target: { value: "1600 Fake St" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("ai-measure-run"));
    });

    // Result rendered → per-provider readout card is visible.
    const readout = await screen.findByTestId("ai-measure-result-openai_gpt-4o-pool");
    expect(readout.textContent).toMatch(/500/);
    expect(readout.textContent).toMatch(/sq ft/);
    expect(readout.textContent).toMatch(/88%/);

    // Thumbs-up updates the feedback log.
    fireEvent.click(screen.getByTestId("ai-measure-feedback-up-openai_gpt-4o-pool"));
    const log = screen.getByTestId("ai-measure-feedback-log");
    expect(log.textContent).toMatch(/pool/);
    expect(log.textContent).toMatch(/500/);
  });

  it("run button POSTs to /tools/ai-measure/preview with sanitized body", async () => {
    apiPost.mockResolvedValueOnce({
      address_resolved: "1600 Fake St", lat: 33.4, lng: -112.07,
      zoom: 20, image_size: [1280, 1280], mpp_effective: 0.03,
      satellite_image_data_url: "data:image/jpeg;base64,AAAA",
      requested_features: ["pool", "deck", "yard"],
      providers: [
        { provider: "openai_gpt-4o", latency_ms: 100, features: [] },
        { provider: "anthropic_claude", latency_ms: 100, features: [] },
      ],
    });
    _renderPage();
    fireEvent.change(screen.getByTestId("ai-measure-address-input"),
      { target: { value: "1600 Fake St" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("ai-measure-run"));
    });
    expect(apiPost).toHaveBeenCalledTimes(1);
    const [path_, body] = apiPost.mock.calls[0];
    expect(path_).toBe("/tools/ai-measure/preview");
    expect(body.zoom).toBe(20);
    expect(body.feature_types).toEqual(["pool", "deck", "yard"]);
    expect(body.address).toBe("1600 Fake St");
  });

  it("errors when no address and no coords are provided", async () => {
    _renderPage();
    await act(async () => {
      fireEvent.click(screen.getByTestId("ai-measure-run"));
    });
    const err = screen.getByTestId("ai-measure-error");
    expect(err.textContent.toLowerCase()).toMatch(/address|coord/);
    expect(apiPost).not.toHaveBeenCalled();
  });
});
