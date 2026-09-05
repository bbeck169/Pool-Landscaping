/**
 * Phase K52.1a · Feb-2026 — LeadsDashboardPage mount smoke test.
 *
 * The K52.1 filter-strip additions referenced ``colors.nav.*`` on
 * a page that carried a LOCAL ``const colors = {…}`` shadow (no
 * ``nav`` sub-object) — the page blew up at render with
 * ``TypeError: Cannot read properties of undefined (reading 'bg')``.
 *
 * K52.1a swapped the shadow for the shared ``@/theme`` import.
 * This test is the belt-and-braces regression guard: a runtime
 * mount that asserts (a) the page does NOT throw during render and
 * (b) the navy filter-strip marker element is present on the DOM
 * with the K52.1 background.  A future local-shadow re-introduction
 * fails this test rather than shipping a runtime crash to Prod.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiDel = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    del: (...a) => apiDel(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
  }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(() => Promise.resolve(true)),
}));

// Two microtask ticks — enough for the ``load()`` effect to
// resolve and paint the tenant-populated tree.
async function tick() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiDel.mockReset();
});

describe("K52.1a · LeadsDashboardPage renders without throwing", () => {
  it("mounts without a runtime crash and paints the navy filter strip", async () => {
    // Empty leads list — cheapest happy path.  The failure mode
    // being guarded is a render-time TypeError, which fires
    // regardless of the API payload.
    apiGet.mockResolvedValueOnce([]);

    // Any runtime crash inside ``render`` propagates as a thrown
    // error before we can assert on the DOM — wrap in a
    // try/expect so the test message is actionable.
    let LeadsDashboardPage;
    let renderResult;
    let renderError = null;
    try {
      LeadsDashboardPage = (await import("@/pages/leads/LeadsDashboardPage")).default;
      renderResult = render(<LeadsDashboardPage />);
      await tick();
    } catch (err) {
      renderError = err;
    }

    // Explicit failure message so a future local-shadow of ``colors``
    // that drops the ``nav`` sub-object surfaces as an actionable
    // test failure, NOT a runtime crash in Prod.
    expect(
      renderError,
      renderError
        ? `LeadsDashboardPage threw during render — likely a local ``colors`` shadow missing the ``nav`` sub-object.  Import shared ``@/theme`` colors. Underlying error: ${renderError.message}`
        : "should mount cleanly",
    ).toBeNull();

    // Navy filter-strip marker present in the DOM.
    const strip = screen.getByTestId("leads-filters");
    expect(strip).toBeInTheDocument();
    expect(strip.getAttribute("data-k52-navy-strip")).toBe("true");
    // Inline ``backgroundColor: colors.nav.bg`` (``#1B1F5C``)
    // resolves to ``rgb(27, 31, 92)`` when React normalises the
    // style prop.
    expect(strip.style.backgroundColor).toBe("rgb(27, 31, 92)");

    renderResult.unmount();
  });
});
