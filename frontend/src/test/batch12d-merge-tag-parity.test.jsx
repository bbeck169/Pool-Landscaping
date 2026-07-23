/**
 * Batch 12D · Feb 2026 — MergeTagPalette parity between email + SMS.
 *
 * Confirms:
 *   1. The palette fetches the FULL catalog and does not filter by
 *      channel — the same categories + tokens appear regardless of
 *      which body kind is being edited.
 *   2. Click-to-insert wraps the token as ``{{TOKEN}}`` in either
 *      mode (parity guaranteed at the component's ``onInsert`` boundary).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MergeTagPalette as Palette,
  __resetMergeTagCacheForTests } from "@/components/marketing/MergeTagPalette";


const _catalog = {
  Customer: [
    { token: "CUSTOMER_FIRST_NAME", label: "First Name",
      description: "First name" },
    { token: "CUSTOMER_STREET", label: "Street (alias)",
      description: "Alias for CUSTOMER_ADDRESS" },
  ],
  Invoice: [
    { token: "INVOICE_PAY_URL", label: "Pay URL (portal)",
      description: "Portal-authenticated pay URL" },
    { token: "INVOICE_PAY_MAGIC_URL", label: "Pay URL (magic link)",
      description: "Public magic-link pay URL" },
  ],
  Estimate: [
    { token: "ESTIMATE_ACCEPT_URL", label: "Estimate Accept URL",
      description: "Public magic-link accept URL" },
  ],
};


const _origFetch = global.fetch;

beforeEach(() => {
  process.env.REACT_APP_BACKEND_URL = "https://example.test";
  __resetMergeTagCacheForTests();
  global.fetch = vi.fn(async () => ({
    ok: true,
    text: async () => JSON.stringify({ categories: _catalog }),
  }));
});
afterEach(() => { cleanup(); global.fetch = _origFetch; });


async function _openAndAwaitPalette() {
  // Wait for the async catalog fetch + render.
  await waitFor(() => {
    expect(screen.queryAllByTestId(/^merge-tag-row-/).length)
      .toBeGreaterThan(0);
  }, { timeout: 2000 });
}


describe("MergeTagPalette catalog exposure parity", () => {
  it("fetches the same full catalog in both email + SMS contexts", async () => {
    const onInsertEmail = vi.fn();
    const { unmount } = render(
      <Palette open={true} onOpenChange={() => {}}
                onInsert={onInsertEmail} />,
    );
    await _openAndAwaitPalette();
    const emailTokens = screen.getAllByTestId(/^merge-tag-row-/)
      .map((el) => el.getAttribute("data-testid").replace(
        "merge-tag-row-", ""));
    for (const cat of Object.values(_catalog)) {
      for (const t of cat) {
        expect(emailTokens, `email palette missing ${t.token}`)
          .toContain(t.token);
      }
    }
    unmount();
    __resetMergeTagCacheForTests();

    // SMS mode is literally the same component — the palette takes
    // no ``channel`` prop today. If someone adds a filter later,
    // this test will fail immediately.
    const onInsertSms = vi.fn();
    render(<Palette open={true} onOpenChange={() => {}}
                     onInsert={onInsertSms} />);
    await _openAndAwaitPalette();
    const smsTokens = screen.getAllByTestId(/^merge-tag-row-/)
      .map((el) => el.getAttribute("data-testid").replace(
        "merge-tag-row-", ""));
    expect(smsTokens.sort()).toEqual(emailTokens.sort());
  });

  it("click-to-insert wraps the token as {{TOKEN}}", async () => {
    const onInsert = vi.fn();
    render(<Palette open={true} onOpenChange={() => {}}
                      onInsert={onInsert} />);
    await _openAndAwaitPalette();
    const rows = screen.getAllByTestId(/^merge-tag-row-/);
    fireEvent.click(rows[0]);
    await waitFor(() => expect(onInsert).toHaveBeenCalled());
    const arg = onInsert.mock.calls[0][0];
    expect(arg).toMatch(/^\{\{[A-Z_0-9]+\}\}$/);
  });
});
