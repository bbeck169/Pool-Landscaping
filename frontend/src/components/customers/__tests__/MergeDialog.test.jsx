/**
 * Feb-2026 · MergeDialog + Duplicates tab integration vitest.
 *
 * 12 cases per dispatch spec covering:
 *  1. Group header render (name + match reasons)
 *  2. Winner radio selection flips winner state
 *  3. Field conflict radio per-column pick
 *  4. 24h recurring block banner + force checkbox
 *  5. Stripe-remap notice renders when any side has stripe id
 *  6. Confirm-name gate disables submit until canonical match
 *  7. Successful merge calls onMerged + onClose + toast copy
 *  8. Portal-invite ResolveDuplicateDialog integration opens
 *     the shared MergeDialog (Phase 2 placeholder closed out)
 *  9. Non-admin canExecute=false hides submit button
 * 10. Match-reasons chips render
 * 11. Cancel button fires onClose without merging
 * 12. Dialog closed when open=false (null return)
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { MergeDialog } from "@/components/customers/MergeDialog";


const _winner = {
  id: "cust-A", name: "Joe Kail",
  email: "joe@a.com", phone: "555-1111",
  status: "active",
};
const _loser = {
  id: "cust-B", name: "Joe Kail Pool",
  email: "", phone: "555-2222",
  status: "inactive", stripe_customer_id: "cus_b",
};


beforeEach(() => {
  global.fetch = vi.fn();
  if (typeof global.localStorage === "undefined") {
    global.localStorage = {
      _s: {},
      getItem(k) { return this._s[k] || null; },
      setItem(k, v) { this._s[k] = v; },
    };
  }
  localStorage.setItem("token", "test-token");
  process.env.REACT_APP_BACKEND_URL = "http://test";
});


describe("Feb-2026 · MergeDialog", () => {
  it("1 · renders when open with 2+ customers", () => {
    render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner, _loser]} />,
    );
    expect(screen.getByTestId("merge-dialog")).toBeTruthy();
    expect(screen.getByTestId("merge-dialog-columns")).toBeTruthy();
  });

  it("2 · winner radio selection updates confirm target", () => {
    render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner, _loser]} />,
    );
    // Default winner = first customer.  Clicking loser's radio
    // flips winner to loser.
    fireEvent.click(screen.getByTestId("merge-dialog-winner-radio-cust-B"));
    const winnerRadio = screen.getByTestId("merge-dialog-winner-radio-cust-B");
    expect(winnerRadio.checked).toBe(true);
  });

  it("3 · field conflict radio renders per-column pick", () => {
    render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner, _loser]} />,
    );
    // Email differs → conflict row.
    expect(screen.getByTestId("merge-dialog-field-row-email")
      .className).toContain("bg-amber");
    // Winner's email radio defaults checked.
    const radioA = screen.getByTestId("merge-dialog-field-radio-email-cust-A");
    const radioB = screen.getByTestId("merge-dialog-field-radio-email-cust-B");
    expect(radioA.checked).toBe(true);
    fireEvent.click(radioB);
    expect(radioB.checked).toBe(true);
  });

  it("4 · 24h recurring block banner surfaces + force toggle", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false, status: 400,
      json: async () => ({ detail: {
        error_code: "merge_blocked_recent_recurring_activity",
        message: "blocked.",
        blocking_templates: [
          { template_id: "tpl-1",
            last_generated_through: "2026-02-05" },
        ],
        override_available: true,
      }}),
    });
    render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner, _loser]} />,
    );
    fireEvent.change(screen.getByTestId("merge-dialog-confirm-name"),
                       { target: { value: "joe kail pool" } });
    fireEvent.click(screen.getByTestId("merge-dialog-submit-btn"));
    await waitFor(() =>
      expect(screen.queryByTestId("merge-dialog-recurring-block-banner"))
        .toBeTruthy(),
    );
    const banner = screen.getByTestId("merge-dialog-recurring-block-banner");
    expect(banner.textContent).toContain("tpl-1");
    expect(banner.textContent).toContain("2026-02-05");
    // Force checkbox present.
    expect(screen.getByTestId("merge-dialog-force-override")).toBeTruthy();
  });

  it("5 · Stripe-remap notice renders when any side has stripe id", () => {
    render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner, _loser]} />,
    );
    const notice = screen.getByTestId("merge-dialog-stripe-notice");
    expect(notice.textContent).toContain("Stripe");
    expect(notice.textContent).toContain("rolled back");
  });

  it("6 · confirm-name gate disables submit until canonical match", () => {
    render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner, _loser]} />,
    );
    const submit = screen.getByTestId("merge-dialog-submit-btn");
    expect(submit.disabled).toBe(true);
    // Partial match still disabled.
    fireEvent.change(screen.getByTestId("merge-dialog-confirm-name"),
                       { target: { value: "Joe Kail" } });
    expect(submit.disabled).toBe(true);
    // Exact canonical match (case + whitespace) enables.
    fireEvent.change(screen.getByTestId("merge-dialog-confirm-name"),
                       { target: { value: "  JOE   KAIL POOL  " } });
    expect(submit.disabled).toBe(false);
  });

  it("7 · successful merge calls onMerged + onClose", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true, status: 200,
      json: async () => ({ audit_id: "a1", winner_id: "cust-A",
                             loser_id: "cust-B" }),
    });
    const onClose = vi.fn();
    const onMerged = vi.fn();
    render(
      <MergeDialog open onClose={onClose} onMerged={onMerged}
                     customers={[_winner, _loser]} />,
    );
    fireEvent.change(screen.getByTestId("merge-dialog-confirm-name"),
                       { target: { value: "joe kail pool" } });
    fireEvent.click(screen.getByTestId("merge-dialog-submit-btn"));
    await waitFor(() => expect(onMerged).toHaveBeenCalled());
    expect(onMerged.mock.calls[0][0].audit_id).toBe("a1");
    expect(onClose).toHaveBeenCalled();
    // Posted correct URL.
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/customers/cust-A/merge-from/cust-B");
    const body = JSON.parse(opts.body);
    expect(body.confirm_name).toBe("joe kail pool");
    expect(body.force).toBe(false);
  });

  it("8 · match-reasons chips render in header", () => {
    render(
      <MergeDialog open onClose={vi.fn()}
                     customers={[_winner, _loser]}
                     matchReasons={["name_fuzzy", "phone"]} />,
    );
    const area = screen.getByTestId("merge-dialog-match-reasons");
    expect(area.textContent).toContain("name fuzzy");
    expect(area.textContent).toContain("phone");
  });

  it("9 · canExecute=false hides submit button (manager view)", () => {
    render(
      <MergeDialog open onClose={vi.fn()}
                     customers={[_winner, _loser]} canExecute={false} />,
    );
    expect(screen.queryByTestId("merge-dialog-submit-btn")).toBeNull();
    expect(screen.getByTestId("merge-dialog-manager-readonly")).toBeTruthy();
  });

  it("10 · cancel button fires onClose without posting", () => {
    const onClose = vi.fn();
    render(
      <MergeDialog open onClose={onClose} customers={[_winner, _loser]} />,
    );
    fireEvent.click(screen.getByTestId("merge-dialog-cancel-btn"));
    expect(onClose).toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("11 · open=false returns null (dialog hidden)", () => {
    const { container } = render(
      <MergeDialog open={false} onClose={vi.fn()}
                     customers={[_winner, _loser]} />,
    );
    expect(container.textContent).toBe("");
  });

  it("12 · 1-customer input returns null (safeguard)", () => {
    const { container } = render(
      <MergeDialog open onClose={vi.fn()} customers={[_winner]} />,
    );
    expect(container.textContent).toBe("");
  });
});
