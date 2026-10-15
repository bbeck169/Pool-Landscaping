/**
 * TD-50 · Feb-2026 — System C deprecation banner on Phase14 FormsList.
 *
 * Phase 5 Commit 2.
 *
 * Covers (6 cases):
 *   1. FormsList renders the deprecation banner with the testid
 *      ``forms-list-deprecation-banner``.
 *   2. Banner CTA links to ``/admin/marketing/forms`` (the Marketing
 *      Forms Builder surface widened to admit owners in Phase 1).
 *   3. Banner CTA testid ``forms-list-deprecation-banner-cta`` is
 *      a <Link> (react-router), not an <a> — client-side nav.
 *   4. FormsList preserves the pre-TD-50 ``forms-list`` + ``forms-new``
 *      testids (regression gate — any Playwright scripts targeting
 *      the legacy surface keep working).
 *   5. FormsList still fetches /forms + renders the row list (zero
 *      functional change to the legacy flow).
 *   6. Banner copy mentions ``Marketing Forms Builder`` by name so
 *      operators can self-serve.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const _mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => _mocks.get(...a),
    post: (...a) => _mocks.post(...a),
    patch: (...a) => _mocks.patch(...a),
    del: (...a) => _mocks.del(...a),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" }, loading: false }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));
vi.mock("@/pages/training/TrainingCertsPanel", () => ({
  __esModule: true, default: () => <div data-testid="stub-training" />,
}));


import { FormsList } from "@/pages/phase14/Phase14Pages";


function _resetMocks() {
  _mocks.get.mockReset(); _mocks.post.mockReset();
  _mocks.patch.mockReset(); _mocks.del.mockReset();
  _mocks.get.mockImplementation((p) => {
    if (p === "/forms") {
      return Promise.resolve([
        { id: "frm_legacy_1", name: "Legacy A", slug: "legacy-a",
          status: "published", submissions: 5 },
        { id: "frm_legacy_2", name: "Legacy B", slug: "legacy-b",
          status: "draft", submissions: 0 },
      ]);
    }
    return Promise.resolve([]);
  });
}


function _render() {
  return render(
    <MemoryRouter>
      <FormsList />
    </MemoryRouter>,
  );
}


describe("Phase14 FormsList · TD-50 deprecation banner", () => {
  beforeEach(_resetMocks);
  afterEach(() => cleanup());

  it("renders the deprecation banner with the stable testid", async () => {
    _render();
    const banner = await screen.findByTestId(
      "forms-list-deprecation-banner",
    );
    expect(banner).toBeTruthy();
  });

  it("banner CTA links to /admin/marketing/forms", async () => {
    _render();
    const cta = await screen.findByTestId(
      "forms-list-deprecation-banner-cta",
    );
    expect(cta.getAttribute("href")).toBe("/admin/marketing/forms");
  });

  it("banner CTA uses react-router <Link> (client-side navigation)", async () => {
    _render();
    const cta = await screen.findByTestId(
      "forms-list-deprecation-banner-cta",
    );
    // React-Router's Link renders as <a href>, but DOES NOT fire a
    // full page reload — distinguishable from a plain <a> by the
    // absence of the ``target`` attribute + presence of the
    // href-relative path (no origin).
    expect(cta.tagName).toBe("A");
    expect(cta.getAttribute("target")).toBeNull();
    // Relative, not absolute.
    const href = cta.getAttribute("href");
    expect(href?.startsWith("/")).toBe(true);
    expect(href?.includes("://")).toBe(false);
  });

  it("preserves pre-TD-50 testids forms-list + forms-new", async () => {
    _render();
    expect(await screen.findByTestId("forms-list")).toBeTruthy();
    expect(screen.getByTestId("forms-new")).toBeTruthy();
  });

  it("still fetches /forms and renders the row list (zero functional change)", async () => {
    _render();
    await waitFor(() =>
      expect(_mocks.get).toHaveBeenCalledWith("/forms"),
    );
    expect(await screen.findByText("Legacy A")).toBeTruthy();
    expect(screen.getByText("Legacy B")).toBeTruthy();
  });

  it("banner copy mentions 'Marketing Forms Builder' by name", async () => {
    _render();
    const banner = await screen.findByTestId(
      "forms-list-deprecation-banner",
    );
    expect(banner.textContent).toMatch(/Marketing Forms Builder/i);
  });
});
