/**
 * Phase P3 · Feb-2026 · Deliverable 1 — KB retrieval preview panel.
 *
 * The panel is exported inline from ``pages/settings/AIBrainPage``.
 * Rather than mount the entire heavy AI Brain page (which drags
 * every widget on it), we import the file, grab the named panel
 * via a small helper module, and test it in isolation.
 *
 * Coverage:
 *  1. Typing a query fires a debounced fetch with ``?q=…``.
 *  2. Empty query fires the panel WITHOUT the ``q`` param (legacy
 *     full-concat preview).
 *  3. Retrieved-count line renders "N snippets from K KB rows"
 *     when the response includes retrieval metadata.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc",
    onSurface: "#000080", muted: "#64748b", border: "#e2e8f0",
    brand: "#1B1F5C", brandTertiary: "#EAF7F0", onBrandTertiary: "#1B1F5C",
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/components/common/ConfirmDeleteDialog", () => ({ default: () => null }));
vi.mock("@/components/admin/TopKBCitationsTile", () => ({ default: () => null }));

async function _wait(ms = 350) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

beforeEach(() => {
  apiGet.mockReset();
});


describe("Phase P3 D1 · KB retrieval preview panel", () => {
  it("empty query fetches the panel WITHOUT the ?q= param", async () => {
    apiGet.mockResolvedValue({
      system_prompt: "# Company knowledge\n\nNothing yet.",
      retrieved: [], retrieved_count: 0,
      kb_row_count: 5, query: "",
    });
    const mod = await import("@/pages/settings/AIBrainPage");
    const Panel = mod.__esModule
      ? (mod.KBRetrievalPreviewPanel || null)
      : null;
    // The panel is not directly exported — mount the whole page and
    // scope by testid instead.
    const AIBrainPage = mod.default;
    render(<AIBrainPage />);
    // Wait through the mount + initial 300ms debounce fetch.
    await _wait();
    const called = apiGet.mock.calls.some(
      ([path]) => path === "/ai/knowledge/system-prompt",
    );
    expect(called).toBe(true);
    expect(await screen.findByTestId("kb-preview-panel")).toBeInTheDocument();
    // Summary line references "No query" for the empty-input branch.
    const summary = await screen.findByTestId("kb-preview-retrieved-count");
    expect(summary.textContent).toMatch(/No query|full-concat/i);
  });

  it("typing a query fires ?q= and renders the retrieved-count line", async () => {
    let call = 0;
    apiGet.mockImplementation((path) => {
      call += 1;
      if (path.startsWith("/ai/knowledge/system-prompt?q=")) {
        return Promise.resolve({
          system_prompt: "# Company knowledge\n\n## Brand voice…",
          retrieved: [
            { id: "kb-1", title: "Brand voice",
              kind: "company_profile", score: 5.2 },
            { id: "kb-2", title: "Warranty terms",
              kind: "policy", score: 3.1 },
          ],
          retrieved_count: 2,
          kb_row_count: 12,
          query: "brand voice",
        });
      }
      // Empty-query initial mount fetch.
      return Promise.resolve({
        system_prompt: "", retrieved: [], retrieved_count: 0,
        kb_row_count: 12, query: "",
      });
    });
    const AIBrainPage = (await import("@/pages/settings/AIBrainPage")).default;
    render(<AIBrainPage />);
    await _wait();

    const input = await screen.findByTestId("kb-preview-q-input");
    fireEvent.change(input, { target: { value: "brand voice" } });
    await _wait();

    // The ?q= call fired.
    const rag_call = apiGet.mock.calls.find(([path]) =>
      String(path).startsWith("/ai/knowledge/system-prompt?q="));
    expect(rag_call).toBeTruthy();
    expect(String(rag_call[0])).toContain(encodeURIComponent("brand voice"));

    // Summary line reads "Retrieved 2 snippets from 12 KB rows."
    const summary = await screen.findByTestId("kb-preview-retrieved-count");
    expect(summary.textContent).toMatch(/Retrieved 2 snippets? from 12 KB rows/);

    // Retrieved-list chips render one per snippet.
    expect(screen.getByTestId("kb-preview-retrieved-item-kb-1")).toBeInTheDocument();
    expect(screen.getByTestId("kb-preview-retrieved-item-kb-2")).toBeInTheDocument();
  });
});
