/**
 * Feb-2026 · Phase 25 · AI Photo + Voice → Repair Estimate vitest.
 *
 * Renders the RepairCalculatorPage and drives:
 *  - "📷 Snap a photo" button → clicks file input → posts multipart to
 *    /api/ai/estimate-from-photo → hydrates parts rows + labor hours
 *    and surfaces the AI result banner with confidence + pricebook match count.
 *  - "🎙️ Voice memo" button when voice provider is disabled → surfaces a
 *    graceful yellow "voice_provider_disabled" banner instead of hydrating.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, apiPostMock, apiPatchMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
  apiPatchMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: apiPostMock, patch: apiPatchMock,
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/components/layout/SafeScrollContainer", () => ({
  __esModule: true,
  default: ({ children, ...rest }) => <div {...rest}>{children}</div>,
}));


const DEFAULT_CONFIG = {
  sales_tax_pct: 0.07, parts_markup_pct: 0.5, merchant_fees_pct: 0.03,
  customer_labor_rate: 175, internal_labor_rate: 75, profit_margin_floor: 0.3,
};

beforeEach(() => {
  apiGetMock.mockReset(); apiPostMock.mockReset(); apiPatchMock.mockReset();
  // Config + customers loads.
  apiGetMock.mockImplementation((path) => {
    if (path === "/ops/repair-calculator/config") return Promise.resolve(DEFAULT_CONFIG);
    if (path === "/customers") return Promise.resolve({ customers: [] });
    return Promise.resolve({});
  });
  // Live quote recompute — return an empty-total quote so the preview
  // stays in its empty state until AI hydrates.
  apiPostMock.mockImplementation((path) => {
    if (path === "/ops/repair-calculator/quote") {
      return Promise.resolve({
        line_items: [], parts_subtotal: 0, sales_tax: 0, parts_total: 0,
        markup: 0, labor: 0, merchant_fees: 0, estimate_total: 0,
        company_cost: 0, profit_margin: 0, profit_margin_pct: 0,
        profit_margin_tier: "red", config_used: DEFAULT_CONFIG,
      });
    }
    return Promise.resolve({});
  });
  // Stub localStorage so the auth header wire-up doesn't blow up.
  window.localStorage.setItem("token", "fake-token");
});

afterEach(() => {
  window.localStorage.removeItem("token");
  vi.restoreAllMocks();
});


describe("Phase 25 · Repair Calculator AI CTAs", () => {
  it("renders both CTAs on the page", async () => {
    const { default: RepairCalculatorPage } = await import(
      "@/pages/ops/RepairCalculatorPage"
    );
    render(<MemoryRouter><RepairCalculatorPage /></MemoryRouter>);
    expect(await screen.findByTestId("repair-calculator-page")).toBeInTheDocument();
    expect(await screen.findByTestId("repair-calc-ai-cta-bar")).toBeInTheDocument();
    expect(await screen.findByTestId("repair-calc-ai-photo-btn")).toBeInTheDocument();
    expect(await screen.findByTestId("repair-calc-ai-voice-btn")).toBeInTheDocument();
  });

  it("photo button POSTs multipart and hydrates parts + labor hours + banner", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        generation_id: "g-1",
        handoff_url: "/ops/repair-calculator",
        provider: "claude",
        input_kind: "photo",
        confidence: 82,
        labor_hours_estimated: 1.5,
        concerns: ["Verify motor gasket"],
        raw_analysis: "Pump seal is weeping under load.",
        parts: [
          { name: "Pump seal kit", cost: 42.5, source: "pricebook_match",
            matched_pricebook_id: "pb-1", confidence: 85 },
          { name: "O-ring 2in", cost: 3.5, source: "ai_inferred",
            matched_pricebook_id: null, confidence: 70 },
        ],
      }),
    });

    const { default: RepairCalculatorPage } = await import(
      "@/pages/ops/RepairCalculatorPage"
    );
    render(<MemoryRouter><RepairCalculatorPage /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");

    const fileInput = document.querySelector('[data-testid="repair-calc-ai-photo-input"]');
    const file = new File([new Uint8Array([137, 80, 78, 71])], "pump.png",
                            { type: "image/png" });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe("http://test.example/api/ai/estimate-from-photo");
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
    expect(opts.body.get("file")).toBeInstanceOf(File);
    expect(opts.headers?.Authorization).toBe("Bearer fake-token");

    // Banner surfaces with confidence + match count + analysis + concerns.
    const banner = await screen.findByTestId("repair-calc-ai-result-banner");
    expect(banner).toBeInTheDocument();
    expect(screen.getByTestId("repair-calc-ai-result-confidence"))
      .toHaveTextContent("82%");
    expect(screen.getByTestId("repair-calc-ai-result-match-count"))
      .toHaveTextContent("1/2 parts matched pricebook");
    expect(screen.getByTestId("repair-calc-ai-result-analysis"))
      .toHaveTextContent(/Pump seal is weeping/);

    // Parts hydrated + labor hours filled.
    expect(screen.getByTestId("repair-calculator-labor-hours").value).toBe("1.5");
    // The two AI parts should now be present as inputs — we look for the
    // name values.
    const nameInputs = screen.getAllByPlaceholderText(/^Part \d+ description/);
    const names = nameInputs.map((el) => el.value);
    expect(names).toEqual(expect.arrayContaining(["Pump seal kit", "O-ring 2in"]));
  });

  it("photo button surfaces provider error toast without hydrating", async () => {
    const { toast } = await import("sonner");
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        error: "llm_error", reason: "Claude timed out",
        parts: [], labor_hours_estimated: 0, concerns: [], confidence: 0,
      }),
    });

    const { default: RepairCalculatorPage } = await import(
      "@/pages/ops/RepairCalculatorPage"
    );
    render(<MemoryRouter><RepairCalculatorPage /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");

    const fileInput = document.querySelector('[data-testid="repair-calc-ai-photo-input"]');
    fireEvent.change(fileInput, {
      target: { files: [new File([new Uint8Array([1])], "x.png", { type: "image/png" })] },
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/Claude timed out|llm_error/),
      ),
    );
    // Banner should NOT appear.
    expect(screen.queryByTestId("repair-calc-ai-result-banner")).toBeNull();
    // Labor hours stays empty.
    expect(screen.getByTestId("repair-calculator-labor-hours").value).toBe("");
  });

  it("voice_provider_disabled response shows the yellow degrade banner + toast", async () => {
    const { toast } = await import("sonner");
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        error: "voice_provider_disabled",
        reason: "OPENAI_API_KEY not configured",
        parts: [], labor_hours_estimated: 0, concerns: [], confidence: 0,
      }),
    });

    // Stub MediaRecorder + getUserMedia so we can trigger a fake stop
    // that flushes an audio blob → posts to the endpoint.
    class FakeMR {
      constructor(stream) { this.stream = stream; this.state = "inactive"; }
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        // Emit a single chunk, then fire onstop synchronously.
        this.ondataavailable?.({ data: new Blob(["a"], { type: "audio/webm" }) });
        this.onstop?.();
      }
    }
    global.MediaRecorder = FakeMR;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }) },
    });

    const { default: RepairCalculatorPage } = await import(
      "@/pages/ops/RepairCalculatorPage"
    );
    render(<MemoryRouter><RepairCalculatorPage /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");

    fireEvent.click(await screen.findByTestId("repair-calc-ai-voice-btn"));
    // Wait for the recorder to be armed, then stop.
    await waitFor(() => screen.getByTestId("repair-calc-ai-voice-stop"));
    fireEvent.click(screen.getByTestId("repair-calc-ai-voice-stop"));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/Voice memo is disabled/i),
      ),
    );
    expect(
      await screen.findByTestId("repair-calc-ai-voice-disabled"),
    ).toBeInTheDocument();
  });
});
