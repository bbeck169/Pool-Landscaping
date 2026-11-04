/**
 * TD-mass-text-merge-tag-toolbar · Feb-2026 — Insert-tag toolbar.
 *
 * Verifies the Mass Text modal:
 *   1. Renders the "Insert tag" button (``mass-text-insert-tag-btn``)
 *      alongside the existing AiRewriteButton slot.
 *   2. Clicking the button opens the shared MergeTagPalette dialog.
 *   3. On palette insert, the canonical ``{{UPPER_CASE_TAG}}`` is
 *      spliced at the textarea's current selection — before/after
 *      text is preserved (no clobber of the surrounding message).
 *   4. The palette self-closes after insert.
 *
 * Existing testIDs preserved regression check: the textarea
 * (``mass-text-body``), send CTA (``mass-text-send``), cancel
 * (``mass-text-cancel``), recipient count (``mass-text-recipient-count``),
 * segments readout (``mass-text-segments``), template picker
 * (``mass-text-template-picker``), and rewrite slot
 * (``mass-text-rewrite-slot``) all still render.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, act,
} from "@testing-library/react";
import MassTextModal from "@/components/customers/MassTextModal";
import {
  __resetMergeTagCacheForTests,
} from "@/components/marketing/MergeTagPalette";


const _catalog = {
  Customer: [
    { token: "CUSTOMER_FIRST_NAME", label: "First Name",
      description: "First name of the customer" },
    { token: "CUSTOMER_LAST_NAME", label: "Last Name",
      description: "Last name of the customer" },
  ],
};


function _mockFetch(url) {
  // Templates endpoint — empty list is the safe default so the
  // picker renders "Write a custom message".
  if (/\/marketing\/templates\/sms(\?|$)/.test(url)) {
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ items: [] }),
    };
  }
  // Merge-tag catalog — the palette expects ``{ categories: {...} }``.
  if (/\/marketing\/merge-tags(\?|$)/.test(url)) {
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ categories: _catalog }),
    };
  }
  // Fail-safe for any other call so a test never silently hangs on
  // an un-mocked endpoint.
  return {
    ok: false,
    status: 404,
    text: async () => JSON.stringify({ detail: "not mocked" }),
  };
}


const _origFetch = global.fetch;


beforeEach(() => {
  process.env.REACT_APP_BACKEND_URL = "https://example.test";
  __resetMergeTagCacheForTests();
  global.fetch = vi.fn(async (url) => _mockFetch(String(url)));
});


afterEach(() => {
  cleanup();
  global.fetch = _origFetch;
});


describe("MassTextModal · merge-tag insert toolbar", () => {
  it("renders the Insert-tag button alongside the rewrite slot", async () => {
    render(
      <MassTextModal
        open={true}
        customerIds={["c1", "c2"]}
        onClose={() => {}}
        onSent={() => {}}
      />,
    );
    const btn = await screen.findByTestId("mass-text-insert-tag-btn");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/Insert tag/i);
    // Rewrite slot (and the live rewrite button inside it) must
    // still be present — we extend the toolbar, we don't replace it.
    expect(screen.getByTestId("mass-text-rewrite-slot")).toBeTruthy();
    expect(screen.getByTestId("mass-text-rewrite-btn")).toBeTruthy();
  });

  it("opens the MergeTagPalette dialog on click", async () => {
    render(
      <MassTextModal
        open={true}
        customerIds={["c1"]}
        onClose={() => {}}
        onSent={() => {}}
      />,
    );
    const btn = await screen.findByTestId("mass-text-insert-tag-btn");
    // Palette is unmounted until the button opens it.
    expect(screen.queryByTestId("merge-tag-palette-dialog")).toBeNull();
    fireEvent.click(btn);
    await waitFor(() => {
      expect(screen.queryAllByTestId(/^merge-tag-row-/).length)
        .toBeGreaterThan(0);
    }, { timeout: 3000 });
    expect(screen.getByTestId("merge-tag-palette-dialog")).toBeTruthy();
  });

  it("splices the canonical {{TOKEN}} at the textarea cursor "
     + "and preserves before/after text", async () => {
    render(
      <MassTextModal
        open={true}
        customerIds={["c1"]}
        onClose={() => {}}
        onSent={() => {}}
      />,
    );
    const textarea = await screen.findByTestId("mass-text-body");
    // Operator types a mid-message cursor position — "Hi | — welcome!"
    // and we park the caret between "Hi " and "— welcome!".
    fireEvent.change(textarea, { target: { value: "Hi  — welcome!" } });
    // Place the caret right after "Hi " (index 3).
    textarea.focus();
    textarea.setSelectionRange(3, 3);
    expect(textarea.selectionStart).toBe(3);

    fireEvent.click(await screen.findByTestId("mass-text-insert-tag-btn"));
    await waitFor(() => {
      expect(screen.queryAllByTestId(/^merge-tag-row-/).length)
        .toBeGreaterThan(0);
    }, { timeout: 3000 });

    // Click the CUSTOMER_FIRST_NAME row — MergeTagPalette wraps the
    // token as ``{{CUSTOMER_FIRST_NAME}}`` before calling onInsert.
    fireEvent.click(
      screen.getByTestId("merge-tag-row-CUSTOMER_FIRST_NAME"),
    );

    // Before: "Hi  — welcome!" with caret at 3
    // After:  "Hi {{CUSTOMER_FIRST_NAME}} — welcome!"
    await waitFor(() => {
      expect(textarea.value).toBe(
        "Hi {{CUSTOMER_FIRST_NAME}} — welcome!",
      );
    });
  });

  it("closes the palette after inserting a tag", async () => {
    render(
      <MassTextModal
        open={true}
        customerIds={["c1"]}
        onClose={() => {}}
        onSent={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("mass-text-insert-tag-btn"));
    await waitFor(() => {
      expect(screen.queryAllByTestId(/^merge-tag-row-/).length)
        .toBeGreaterThan(0);
    }, { timeout: 3000 });
    fireEvent.click(
      screen.getByTestId("merge-tag-row-CUSTOMER_FIRST_NAME"),
    );
    await waitFor(() => {
      expect(screen.queryByTestId("merge-tag-palette-dialog")).toBeNull();
    });
  });

  it("preserves all existing Mass Text modal testIDs", async () => {
    render(
      <MassTextModal
        open={true}
        customerIds={["c1", "c2", "c3"]}
        onClose={() => {}}
        onSent={() => {}}
      />,
    );
    // Smoke-check every testID the KK + LL tickets guaranteed —
    // this ticket extends the toolbar, it must not break any of them.
    await screen.findByTestId("mass-text-modal");
    expect(screen.getByTestId("mass-text-recipient-count")).toBeTruthy();
    expect(screen.getByTestId("mass-text-template-picker")).toBeTruthy();
    expect(screen.getByTestId("mass-text-body")).toBeTruthy();
    expect(screen.getByTestId("mass-text-segments")).toBeTruthy();
    expect(screen.getByTestId("mass-text-rewrite-slot")).toBeTruthy();
    expect(screen.getByTestId("mass-text-rewrite-btn")).toBeTruthy();
    expect(screen.getByTestId("mass-text-cancel")).toBeTruthy();
    expect(screen.getByTestId("mass-text-send")).toBeTruthy();
    // New: the Insert-tag button.
    expect(screen.getByTestId("mass-text-insert-tag-btn")).toBeTruthy();
  });
});
