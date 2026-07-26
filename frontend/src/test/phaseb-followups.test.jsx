/**
 * Feb-2026 · Phase B follow-ups — vitest.
 *
 * Covers the two deferred UI additions:
 *
 * 1. GbpPostsPage · "✨ Generate branded image" per-draft button opens
 *    a composer modal that POSTs /media/image/generate with
 *    surface="gbp" and PATCHes the draft with the returned image URL.
 *    Feature-flagged on the Supercool connection status.
 *
 * 2. RepairCalculatorPage · "🎨 Generate 'after' concept render"
 *    button appears once an AI photo estimate + photo data URL are
 *    available. Clicking POSTs /media/image/edit with source_image_url
 *    set to the customer photo's data URI, then renders a side-by-side
 *    BEFORE|AFTER grid with the strict legal caption. "Attach to quote
 *    email" flips a chip into the email confirm modal.
 *
 * All API calls are mocked at the `@/api` boundary so the Supercool
 * MCP + Emergent LLM keys are NEVER burned during the test run.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── shared shadcn mocks ─────────────────────────────────────────────
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));

// The shadcn Dialog uses radix portals — reduce to a straight render so
// jsdom queries resolve.
vi.mock("@/components/ui/dialog", () => ({
  __esModule: true,
  Dialog: ({ open, children }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children, ...rest }) => <div {...rest}>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <div>{children}</div>,
  DialogDescription: ({ children }) => <div>{children}</div>,
  DialogFooter: ({ children }) => <div>{children}</div>,
  DialogTrigger: ({ children }) => <>{children}</>,
  DialogClose: ({ children }) => <>{children}</>,
  DialogPortal: ({ children }) => <>{children}</>,
  DialogOverlay: () => null,
}));

vi.mock("@/components/ui/button", () => ({
  __esModule: true,
  Button: ({ children, ...rest }) => <button {...rest}>{children}</button>,
}));

vi.mock("@/components/ui/checkbox", () => ({
  __esModule: true,
  Checkbox: ({ checked, onCheckedChange, ...rest }) => (
    <input
      type="checkbox"
      checked={!!checked}
      onChange={(e) => onCheckedChange?.(e.target.checked)}
      {...rest}
    />
  ),
}));

vi.mock("@/components/ui/label", () => ({
  __esModule: true,
  Label: ({ children, ...rest }) => <label {...rest}>{children}</label>,
}));

vi.mock("@/components/layout/SafeScrollContainer", () => ({
  __esModule: true,
  default: ({ children, ...rest }) => <div {...rest}>{children}</div>,
}));


// ─── shared API mocks ────────────────────────────────────────────────
const { apiGetMock, apiPostMock, apiPatchMock, apiDelMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(), apiPostMock: vi.fn(),
  apiPatchMock: vi.fn(), apiDelMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: apiPostMock,
    patch: apiPatchMock, del: apiDelMock,
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));


beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  apiPatchMock.mockReset();
  apiDelMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});


// ─── 1. GbpPostsPage · Composer modal ────────────────────────────────
describe("Phase B follow-up · GBP composer modal", () => {
  const draft = {
    id: "draft-1", tenant_id: "t-1",
    purpose: "promo", tone: "friendly",
    headline: "Salt cell tune-up special",
    body_150w: "Save 20% this week on salt cell replacements.",
    cta_text: "Book",
    image_prompt: "A bright backyard pool with a technician servicing the salt cell.",
    image_url: null,
    status: "draft",
    generated_at: new Date().toISOString(),
  };

  it("shows the button disabled + tooltip when Supercool is not connected", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/marketing/gbp-posts") return Promise.resolve({ items: [draft] });
      if (path === "/integrations/supercool/status") return Promise.resolve({ connected: false });
      return Promise.resolve({});
    });

    const { default: Page } = await import(
      "@/pages/marketing/GbpPostsPage");
    render(<MemoryRouter><Page /></MemoryRouter>);

    const btn = await screen.findByTestId(`gbp-gen-image-btn-${draft.id}`);
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title") || "").toMatch(/Connect Supercool/i);
    // Modal should NOT auto-mount.
    expect(screen.queryByTestId("gbp-image-composer-modal")).toBeNull();
  });

  it("opens the modal and POSTs /media/image/generate with surface=gbp + default 4:5", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/marketing/gbp-posts") return Promise.resolve({ items: [draft] });
      if (path === "/integrations/supercool/status") return Promise.resolve({ connected: true });
      return Promise.resolve({});
    });
    apiPostMock.mockImplementation((path) => {
      if (path === "/media/image/generate") {
        return Promise.resolve({
          image_id: "img-gbp-1",
          url: "/uploads/generated/img-gbp-1.png",
          provider: "supercool", tool_used: "image_generate",
          prompt: draft.image_prompt, aspect_ratio: "4:5",
        });
      }
      return Promise.resolve({});
    });

    const { default: Page } = await import(
      "@/pages/marketing/GbpPostsPage");
    render(<MemoryRouter><Page /></MemoryRouter>);

    const openBtn = await screen.findByTestId(`gbp-gen-image-btn-${draft.id}`);
    expect(openBtn).not.toBeDisabled();
    fireEvent.click(openBtn);

    const promptInput = await screen.findByTestId("gbp-composer-prompt-input");
    // Pre-filled from the draft's image_prompt.
    expect(promptInput.value).toContain("technician servicing the salt cell");

    // Default aspect is 4:5 — the button should be highlighted (we
    // don't assert the visual, just that the mock click works).
    fireEvent.click(screen.getByTestId("gbp-composer-generate-btn"));

    await waitFor(() => expect(apiPostMock).toHaveBeenCalled());
    const [postPath, body] = apiPostMock.mock.calls[0];
    expect(postPath).toBe("/media/image/generate");
    expect(body.surface).toBe("gbp");
    expect(body.aspect_ratio).toBe("4:5");
    // Brand elements ON by default → the suffix is appended.
    expect(String(body.prompt)).toMatch(/on-brand for a pool/i);

    // Preview should now be visible.
    expect(await screen.findByTestId("gbp-composer-preview")).toBeInTheDocument();
  });

  it("Attach-to-draft PATCHes the GBP draft with the new image_url", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/marketing/gbp-posts") return Promise.resolve({ items: [draft] });
      if (path === "/integrations/supercool/status") return Promise.resolve({ connected: true });
      return Promise.resolve({});
    });
    apiPostMock.mockResolvedValue({
      image_id: "img-gbp-2", url: "/uploads/generated/img-gbp-2.png",
      provider: "supercool", tool_used: "image_generate",
      prompt: draft.image_prompt, aspect_ratio: "4:5",
    });
    apiPatchMock.mockResolvedValue({
      ...draft, image_url: "/uploads/generated/img-gbp-2.png",
    });

    const { default: Page } = await import(
      "@/pages/marketing/GbpPostsPage");
    render(<MemoryRouter><Page /></MemoryRouter>);

    fireEvent.click(await screen.findByTestId(`gbp-gen-image-btn-${draft.id}`));
    // Turn OFF brand elements to prove the checkbox is wired.
    const brandChk = await screen.findByTestId("gbp-composer-brand-checkbox");
    fireEvent.click(brandChk);
    fireEvent.click(screen.getByTestId("gbp-composer-generate-btn"));

    // After generate, the primary button flips to "Attach to draft".
    const attachBtn = await screen.findByTestId("gbp-composer-attach-btn");
    fireEvent.click(attachBtn);

    await waitFor(() => expect(apiPatchMock).toHaveBeenCalled());
    const [patchPath, patchBody] = apiPatchMock.mock.calls[0];
    expect(patchPath).toBe(`/marketing/gbp-posts/${draft.id}`);
    expect(patchBody.image_url).toBe("/uploads/generated/img-gbp-2.png");

    // Also — the second POST call should have gone without the brand suffix.
    const [, body] = apiPostMock.mock.calls[0];
    expect(String(body.prompt)).not.toMatch(/on-brand for a pool/i);
  });
});


// ─── 2. RepairCalculatorPage · BEFORE/AFTER concept render ───────────
describe("Phase B follow-up · Repair Calculator concept render", () => {
  const DEFAULT_CONFIG = {
    sales_tax_pct: 0.07, parts_markup_pct: 0.5, merchant_fees_pct: 0.03,
    customer_labor_rate: 175, internal_labor_rate: 75, profit_margin_floor: 0.3,
  };

  const setupBasicMocks = ({ supercoolConnected = true } = {}) => {
    apiGetMock.mockImplementation((path) => {
      if (path === "/ops/repair-calculator/config") return Promise.resolve(DEFAULT_CONFIG);
      if (path === "/customers") return Promise.resolve({ customers: [] });
      if (path === "/integrations/supercool/status")
        return Promise.resolve({ connected: supercoolConnected });
      return Promise.resolve({});
    });
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
    window.localStorage.setItem("token", "fake-token");
  };

  const uploadPhotoAndHydrate = async () => {
    // Stub FileReader.readAsDataURL synchronously so photoDataUrl
    // is populated before the test asserts.
    const OrigFR = global.FileReader;
    class FakeFR {
      readAsDataURL() {
        this.result = "data:image/png;base64,QUJDRA==";
        setTimeout(() => this.onload?.(), 0);
      }
    }
    global.FileReader = FakeFR;

    // Stub fetch for the AI photo estimate endpoint.
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        generation_id: "g-1",
        handoff_url: "/ops/repair-calculator",
        provider: "claude",
        input_kind: "photo",
        confidence: 82,
        labor_hours_estimated: 1.5,
        concerns: [],
        raw_analysis: "Pump seal is weeping under load.",
        parts: [
          { name: "Pump seal kit", cost: 42.5,
             source: "pricebook_match", matched_pricebook_id: "pb-1",
             confidence: 85 },
          { name: "Motor gasket", cost: 12.0,
             source: "pricebook_match", matched_pricebook_id: "pb-2",
             confidence: 78 },
        ],
      }),
    });

    const fileInput = document.querySelector('[data-testid="repair-calc-ai-photo-input"]');
    fireEvent.change(fileInput, {
      target: { files: [new File([new Uint8Array([1, 2, 3, 4])], "pump.png",
                                     { type: "image/png" })] },
    });
    // Restore FileReader after the picker.
    setTimeout(() => { global.FileReader = OrigFR; }, 10);
  };

  it("does NOT render the before/after tile until a photo + AI result are both present", async () => {
    setupBasicMocks();
    const { default: Page } = await import(
      "@/pages/ops/RepairCalculatorPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");
    // Neither photo nor result yet → no before/after section.
    expect(screen.queryByTestId("repair-calc-before-after")).toBeNull();
  });

  it("shows the before/after tile after AI hydrate and disables 'Generate' when Supercool is off", async () => {
    setupBasicMocks({ supercoolConnected: false });
    const { default: Page } = await import(
      "@/pages/ops/RepairCalculatorPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");

    await uploadPhotoAndHydrate();
    await screen.findByTestId("repair-calc-ai-result-banner");
    // The BEFORE/AFTER section now appears.
    const tile = await screen.findByTestId("repair-calc-before-after");
    expect(tile).toBeInTheDocument();
    // Legal caption is present + correct verbatim.
    expect(screen.getByTestId("repair-calc-after-legal-caption"))
      .toHaveTextContent("AI-generated concept render — actual results may vary.");
    // Generate button is disabled with the Supercool tooltip.
    const genBtn = screen.getByTestId("repair-calc-generate-after-btn");
    expect(genBtn).toBeDisabled();
    expect(genBtn.getAttribute("title") || "").toMatch(/Connect Supercool/i);
    // Yellow degrade hint is rendered.
    expect(screen.getByTestId("repair-calc-before-after-supercool-hint"))
      .toBeInTheDocument();
    // BEFORE image sourced from the data URL.
    const beforeImg = screen.getByTestId("repair-calc-before-image");
    expect(beforeImg.getAttribute("src")).toMatch(/^data:image\/png/);
  });

  it("POSTs /media/image/edit with source_image_url + surface=estimate and renders the AFTER tile", async () => {
    setupBasicMocks({ supercoolConnected: true });
    // Wire the edit endpoint mock at the mock table level.
    apiPostMock.mockImplementation((path) => {
      if (path === "/media/image/edit") {
        return Promise.resolve({
          image_id: "img-after-1",
          url: "/uploads/generated/img-after-1.png",
          provider: "supercool",
          tool_used: "image_generate",
        });
      }
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

    const { default: Page } = await import(
      "@/pages/ops/RepairCalculatorPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");

    await uploadPhotoAndHydrate();
    await screen.findByTestId("repair-calc-ai-result-banner");
    const genBtn = await screen.findByTestId("repair-calc-generate-after-btn");
    await waitFor(() => expect(genBtn).not.toBeDisabled());

    fireEvent.click(genBtn);

    await waitFor(() => {
      const editCall = apiPostMock.mock.calls.find(([p]) => p === "/media/image/edit");
      expect(editCall).toBeTruthy();
      const [, body] = editCall;
      expect(body.surface).toBe("estimate");
      expect(body.aspect_ratio).toBe("4:5");
      // The customer's data URL comes through as source_image_url.
      expect(String(body.source_image_url)).toMatch(/^data:image\/png/);
      // Prompt should reference the matched parts + technician analysis.
      expect(String(body.prompt)).toMatch(/Pump seal kit/i);
      expect(String(body.prompt)).toMatch(/Motor gasket/i);
      expect(String(body.prompt)).toMatch(/Pump seal is weeping/i);
    });

    // AFTER tile now has the concept render image + Attach button.
    const afterImg = await screen.findByTestId("repair-calc-after-image");
    expect(afterImg.getAttribute("src"))
      .toBe("http://test.example/uploads/generated/img-after-1.png");
    expect(screen.getByTestId("repair-calc-attach-render-btn"))
      .toBeInTheDocument();
  });

  it("Attach to quote email shows the chip inside the email modal", async () => {
    setupBasicMocks({ supercoolConnected: true });
    apiPostMock.mockImplementation((path) => {
      if (path === "/media/image/edit") {
        return Promise.resolve({
          image_id: "img-after-2",
          url: "/uploads/generated/img-after-2.png",
          provider: "supercool", tool_used: "image_generate",
        });
      }
      if (path === "/ops/repair-calculator/quote") {
        return Promise.resolve({
          line_items: [{ name: "Pump seal kit", cost: 42.5 }],
          parts_subtotal: 42.5, sales_tax: 3.0, parts_total: 45.5,
          markup: 21.25, labor: 262.5, merchant_fees: 9.94,
          estimate_total: 339.19, company_cost: 190.0,
          profit_margin: 0.44, profit_margin_pct: 44.0,
          profit_margin_tier: "green", config_used: DEFAULT_CONFIG,
        });
      }
      return Promise.resolve({});
    });

    const { default: Page } = await import(
      "@/pages/ops/RepairCalculatorPage");
    render(<MemoryRouter><Page /></MemoryRouter>);
    await screen.findByTestId("repair-calculator-page");

    await uploadPhotoAndHydrate();
    await screen.findByTestId("repair-calc-ai-result-banner");
    const genBtn = await screen.findByTestId("repair-calc-generate-after-btn");
    await waitFor(() => expect(genBtn).not.toBeDisabled());
    fireEvent.click(genBtn);
    await screen.findByTestId("repair-calc-after-image");

    // Attach the render to the email flow, then open the modal.
    fireEvent.click(screen.getByTestId("repair-calc-attach-render-btn"));
    // Open the email confirm modal.
    fireEvent.click(await screen.findByTestId("rc-preview-email"));

    expect(await screen.findByTestId("rc-email-render-attached-chip"))
      .toHaveTextContent(/AI concept render will be attached/i);
  });
});
