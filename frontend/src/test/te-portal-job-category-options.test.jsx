/**
 * Feb-2026 · TE-portal-job · Frontend category-dropdown coverage.
 *
 * The Marketing Templates admin surface exposes ``CATEGORY_OPTIONS``
 * in TWO places:
 *   1. Filter dropdown on the list page (``MarketingTemplatesListPage``).
 *   2. Category selector on the detail page
 *      (``MarketingTemplateDetailPage``).
 *
 * Both must render the new ``portal_invite`` + ``job_completion``
 * options for this commit to be user-visible.
 *
 * Test contract:
 *   * Filter dropdown renders both new options with correct
 *     ``value`` + ``label`` strings.
 *   * Detail-page selector renders both new options.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


// ─── Shared mocks (mirror the N5-T1 test file's approach) ────────
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => new Promise(() => {})),
    post: vi.fn(() => new Promise(() => {})),
    put: vi.fn(() => new Promise(() => {})),
    del: vi.fn(() => new Promise(() => {})),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: "admin", name: "Admin Test", id: "u-1" },
    role: "admin",
    loading: false,
  }),
}));

// Merge-tag palette makes a network call on mount — stub the
// component so the render tree is deterministic.
vi.mock("@/components/marketing/MergeTagPalette", () => ({
  MergeTagPalette: () => null,
}));

// TemplateEditor is a heavy TipTap wrapper — stub with a bare
// textarea proxy so the detail page mounts.
vi.mock("@/components/marketing/TemplateEditor", () => ({
  TemplateEditor: ({ value }) => (
    <textarea readOnly data-testid="template-editor-stub" value={value || ""} />
  ),
  computeSmsSegments: () => ({ segments: 1, chars: 0 }),
}));

// Confirm-dialog import guard.
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: () => Promise.resolve(true),
}));

// Sonner toast is a side effect — stub to a no-op so the module
// registers without a portal target.
vi.mock("sonner", () => ({
  toast: { success: () => {}, error: () => {}, info: () => {} },
}));


beforeEach(() => {
  window.localStorage?.clear?.();
});
afterEach(() => {
  cleanup();
});


// ═════════════════════════════════════════════════════════════════
// 1 · Filter dropdown on the list page
// ═════════════════════════════════════════════════════════════════
describe("TE-portal-job · MarketingTemplatesListPage filter dropdown", () => {
  it("renders 'Portal Invite' + 'Job Completion' options in the filter", async () => {
    const mod = await import("@/pages/marketing/MarketingTemplatesAdmin");
    const ListPage = mod.default;
    render(
      <MemoryRouter>
        <ListPage />
      </MemoryRouter>,
    );
    // Filter dropdown testid comes from the wire target
    // (``templates-filter-category``). The <select> owns the
    // <option> children; assert their text content directly.
    const filter = await screen.findByTestId("templates-filter-category");
    const values = Array.from(filter.querySelectorAll("option")).map(
      (o) => o.value,
    );
    const labels = Array.from(filter.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(values).toContain("portal_invite");
    expect(values).toContain("job_completion");
    expect(labels).toContain("Portal Invite");
    expect(labels).toContain("Job Completion");
  });
});


// ═════════════════════════════════════════════════════════════════
// 2 · Detail-page category selector
// ═════════════════════════════════════════════════════════════════
describe("TE-portal-job · MarketingTemplateDetailPage category selector", () => {
  it("renders both new options in the detail-page category selector", async () => {
    // Feed the detail-page fetch so the render-with-data branch
    // commits (``api.get('/marketing/templates/:id')`` is the
    // sole gate for the editor form).
    const apiMod = await import("@/api");
    apiMod.api.get.mockImplementation((path) => {
      if (typeof path === "string" && path.startsWith("/marketing/templates/")) {
        return Promise.resolve({
          id: "tpl-1",
          name: "Sample",
          channel: "email",
          category: "general",
          subject: "Hello",
          body: "Hi {{customer.first_name}}",
          active: true,
          system: false,
        });
      }
      return new Promise(() => {});
    });
    const mod = await import("@/pages/marketing/MarketingTemplatesAdmin");
    const DetailPage = mod.MarketingTemplateDetailPage;
    render(
      <MemoryRouter initialEntries={["/marketing/templates/tpl-1"]}>
        <Routes>
          <Route
            path="/marketing/templates/:id"
            element={<DetailPage />}
          />
        </Routes>
      </MemoryRouter>,
    );
    const selector = await screen.findByTestId(
      "template-detail-category",
    );
    await waitFor(() => {
      const values = Array.from(selector.querySelectorAll("option")).map(
        (o) => o.value,
      );
      expect(values).toContain("portal_invite");
      expect(values).toContain("job_completion");
    });
    const labels = Array.from(selector.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(labels).toContain("Portal Invite");
    expect(labels).toContain("Job Completion");
  });
});
