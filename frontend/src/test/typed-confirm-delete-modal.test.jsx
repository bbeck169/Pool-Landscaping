/**
 * Feb-2026 · Item 3 · P0 fix — typed-confirm modal TextInput bug.
 *
 * Original bug: ``<TextInput onChange={setDeleteConfirmText} />`` in
 * ``QuoteInvoiceDetail.jsx`` set state to the native Event object
 * instead of the string. The next render's ``deleteConfirmText.trim()``
 * threw ``TypeError`` and the Delete button stayed disabled forever.
 *
 * Fix: ``<TextInput onChange={(e) => setDeleteConfirmText(e.target.value)} />``
 *
 * This test file combines three layers of regression coverage:
 *   1. **Source-regex guards** on ``QuoteInvoiceDetail.jsx`` that
 *      fail if the bug pattern reappears or the fix pattern
 *      disappears — cheap CI-level canary.
 *   2. **TextInput contract test** — mounts the shipped ``TextInput``
 *      component and verifies its ``onChange`` receives a native
 *      Event (not a string). If someone "helpfully" refactors it to
 *      pass a string, this test fires so we can audit callers.
 *   3. **Behavioural test** — mounts a tiny in-file harness that
 *      uses the EXACT same ``<TextInput value onChange={(e) =>
 *      setState(e.target.value)}>`` shape as the fixed
 *      QuoteInvoiceDetail modals + asserts:
 *        (a) no TypeError on keystroke,
 *        (b) button disabled on empty / wrong text,
 *        (c) button enabled once typed value matches token,
 *        for BOTH the invoice-delete and payment-delete flows.
 *
 * We don't mount ``<QuoteInvoiceDetail />`` directly — the repo
 * convention (see ``invoice-draft-send.test.jsx`` docstring) is that
 * it hangs under jsdom because of its Modal+Toast+fetch-on-mount
 * combo. The layer-1 source guard catches wire-up drift; the
 * layer-2/3 tests catch behavior.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { TextInput } from "@/components/ui-kit";


const QUOTE_DETAIL_SRC = readFileSync(
  resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


// ══════════════════════════════════════════════════════════════════
// Layer 1 — source guards on the two known-bad + known-good patterns.
// ══════════════════════════════════════════════════════════════════
describe("QuoteInvoiceDetail source · typed-confirm TextInput wiring", () => {
  it("does NOT use `onChange={setDeleteConfirmText}` (the bug pattern)", () => {
    // Either identifier bound directly as the handler is the shape
    // that broke TEST 4 — the string ``setState(evt)`` fails when
    // downstream code calls ``deleteConfirmText.trim()``.
    expect(QUOTE_DETAIL_SRC).not.toMatch(
      /onChange\s*=\s*\{\s*setDeleteConfirmText\s*\}/,
    );
  });

  it("uses `onChange={(e) => setDeleteConfirmText(e.target.value)}` for BOTH modals", () => {
    // Two call sites — one for the invoice-delete modal, one for
    // the payment-delete modal. Both must carry the value-extract
    // shape.
    const matches = QUOTE_DETAIL_SRC.match(
      /onChange\s*=\s*\{\s*\(e\)\s*=>\s*setDeleteConfirmText\(e\.target\.value\)\s*\}/g,
    ) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("both typed-confirm TextInputs still carry their testids", () => {
    expect(QUOTE_DETAIL_SRC).toMatch(/testid="id-delete-invoice-input"/);
    expect(QUOTE_DETAIL_SRC).toMatch(/testid="id-delete-payment-input"/);
  });
});


// ══════════════════════════════════════════════════════════════════
// Layer 2 — TextInput contract lock. If someone changes the
// component so ``onChange`` receives a bare string, we need to
// audit every caller — this test alerts us to the semver break.
// ══════════════════════════════════════════════════════════════════
describe("TextInput · onChange contract (Feb-2026 · P0)", () => {
  it("forwards the native Event to onChange (NOT a string value)", () => {
    const spy = vi.fn();
    render(<TextInput testid="ti-contract" onChange={spy} />);
    const input = screen.getByTestId("ti-contract");
    fireEvent.change(input, { target: { value: "hello" } });
    expect(spy).toHaveBeenCalledTimes(1);
    const arg = spy.mock.calls[0][0];
    // Received arg is a SyntheticEvent, not a raw string. If this
    // ever flips, every caller needs an audit — see approach (B) in
    // the P0 dispatch.
    expect(typeof arg).not.toBe("string");
    expect(arg).toBeTruthy();
    expect(arg.target).toBeTruthy();
    expect(arg.target.value).toBe("hello");
  });
});


// ══════════════════════════════════════════════════════════════════
// Layer 3 — behavioural harness that mirrors the EXACT shape from
// the fixed QuoteInvoiceDetail modals. Verifies the three
// spec-mandated behaviours for both invoice + payment flows.
// ══════════════════════════════════════════════════════════════════
function DeleteConfirmHarness({ token, testidPrefix }) {
  const [text, setText] = React.useState("");
  const disabled = text.trim() !== token;
  return (
    <div>
      <TextInput
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={token}
        testid={`${testidPrefix}-input`}
      />
      <button
        type="button"
        disabled={disabled}
        data-testid={`${testidPrefix}-confirm`}
      >
        Delete
      </button>
    </div>
  );
}


describe("Typed-confirm harness · invoice-delete flow", () => {
  it("does NOT throw on keystroke (root-cause regression guard)", () => {
    render(<DeleteConfirmHarness token="INV-2026-0001"
                                   testidPrefix="id-delete-invoice" />);
    // If the bug pattern (onChange={setState}) came back, this
    // fireEvent would set state = Event, and the next render's
    // ``text.trim()`` would throw. We simulate the exact keystroke
    // + assert nothing throws.
    expect(() => {
      fireEvent.change(screen.getByTestId("id-delete-invoice-input"),
        { target: { value: "I" } });
    }).not.toThrow();
  });

  it("Delete button disabled when input empty", () => {
    render(<DeleteConfirmHarness token="INV-2026-0001"
                                   testidPrefix="id-delete-invoice" />);
    const btn = screen.getByTestId("id-delete-invoice-confirm");
    expect(btn.disabled).toBe(true);
  });

  it("Delete button disabled when typed text does NOT match invoice number", () => {
    render(<DeleteConfirmHarness token="INV-2026-0001"
                                   testidPrefix="id-delete-invoice" />);
    fireEvent.change(screen.getByTestId("id-delete-invoice-input"),
      { target: { value: "INV-WRONG" } });
    expect(screen.getByTestId("id-delete-invoice-confirm").disabled)
      .toBe(true);
  });

  it("Delete button enabled ONLY once typed text matches invoice number", () => {
    render(<DeleteConfirmHarness token="INV-2026-0001"
                                   testidPrefix="id-delete-invoice" />);
    const input = screen.getByTestId("id-delete-invoice-input");
    const btn = screen.getByTestId("id-delete-invoice-confirm");
    // Partial → disabled.
    fireEvent.change(input, { target: { value: "INV-2026" } });
    expect(btn.disabled).toBe(true);
    // Full match → enabled.
    fireEvent.change(input, { target: { value: "INV-2026-0001" } });
    expect(btn.disabled).toBe(false);
    // Trailing whitespace stripped by the trim() the fix uses.
    fireEvent.change(input, { target: { value: "  INV-2026-0001  " } });
    expect(btn.disabled).toBe(false);
  });
});


describe("Typed-confirm harness · payment-delete flow", () => {
  const TOKEN = "abc12345"; // first-8 char short-hash pattern

  it("does NOT throw on keystroke", () => {
    render(<DeleteConfirmHarness token={TOKEN}
                                   testidPrefix="id-delete-payment" />);
    expect(() => {
      fireEvent.change(screen.getByTestId("id-delete-payment-input"),
        { target: { value: "a" } });
    }).not.toThrow();
  });

  it("Delete button disabled when input empty", () => {
    render(<DeleteConfirmHarness token={TOKEN}
                                   testidPrefix="id-delete-payment" />);
    expect(screen.getByTestId("id-delete-payment-confirm").disabled)
      .toBe(true);
  });

  it("Delete button disabled when typed text does NOT match short-hash", () => {
    render(<DeleteConfirmHarness token={TOKEN}
                                   testidPrefix="id-delete-payment" />);
    fireEvent.change(screen.getByTestId("id-delete-payment-input"),
      { target: { value: "wrong123" } });
    expect(screen.getByTestId("id-delete-payment-confirm").disabled)
      .toBe(true);
  });

  it("Delete button enabled ONLY once typed text matches short-hash", () => {
    render(<DeleteConfirmHarness token={TOKEN}
                                   testidPrefix="id-delete-payment" />);
    const input = screen.getByTestId("id-delete-payment-input");
    const btn = screen.getByTestId("id-delete-payment-confirm");
    fireEvent.change(input, { target: { value: "abc" } });
    expect(btn.disabled).toBe(true);
    fireEvent.change(input, { target: { value: TOKEN } });
    expect(btn.disabled).toBe(false);
  });
});
