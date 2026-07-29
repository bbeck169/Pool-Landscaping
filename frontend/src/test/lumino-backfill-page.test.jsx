/**
 * LZ5 · Feb-2026 — Lumino Backfill page tests.
 *
 * Covers the two user-facing contracts:
 *   1. "Preview candidates" button hits the endpoint with dry_run=true.
 *   2. "Run backfill" button opens the confirm modal, and only fires
 *      the endpoint (with dry_run=false) after the user confirms.
 *   3. Super-admin gate — non-super_admin sees the "forbidden" panel.
 *   4. Live-run response is rendered as the results table.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Mocks (must come BEFORE the component import) ───────────
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...args) => postMock(...args) },
}));

const authState = { user: { role: "super_admin", email: "super@test" } };
vi.mock("@/auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", border: "#eee", muted: "#666",
    onSurface: "#000", onSurfaceSecondary: "#666",
    surfaceSecondary: "#fafafa",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

import LuminoBackfillPage from "@/pages/admin/LuminoBackfillPage";

const renderPage = () => render(
  <MemoryRouter>
    <LuminoBackfillPage />
  </MemoryRouter>,
);

beforeEach(() => {
  postMock.mockReset();
  authState.user = { role: "super_admin", email: "super@test" };
});

afterEach(() => cleanup());


describe("LuminoBackfillPage · super-admin gate", () => {
  it("shows the forbidden panel when user is not super_admin", () => {
    authState.user = { role: "admin", email: "admin@test" };
    renderPage();
    expect(screen.getByTestId("lumino-backfill-forbidden"))
      .toBeInTheDocument();
    // Form is not rendered for non-super users.
    expect(screen.queryByTestId("lumino-backfill-preview-btn"))
      .not.toBeInTheDocument();
  });
});


describe("LuminoBackfillPage · preview button", () => {
  it("POSTs to the endpoint with dry_run=true and renders the count", async () => {
    postMock.mockResolvedValueOnce({
      dry_run: true,
      total_candidates: 3,
      dispatched: 0, skipped: 0, errors: 0,
      results: [
        {invoice_id: "a", invoice_number: "INV-A", customer_name: "Alice",
          total: 100, status: "sent", created_at: "2026-01-01T00:00:00Z"},
        {invoice_id: "b", invoice_number: "INV-B", customer_name: "Bob",
          total: 200, status: "overdue", created_at: "2026-01-02T00:00:00Z"},
        {invoice_id: "c", invoice_number: "INV-C", customer_name: "Carol",
          total: 300, status: "sent", created_at: "2026-01-03T00:00:00Z"},
      ],
    });
    renderPage();
    const btn = screen.getByTestId("lumino-backfill-preview-btn");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledTimes(1);
    });
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/admin/lumino/backfill-payment-links");
    expect(body.dry_run).toBe(true);
    expect(body.limit).toBe(25); // default
    // Count rendered.
    await waitFor(() => {
      const el = screen.getByTestId("lumino-backfill-preview-count");
      expect(el.textContent).toMatch(/3 candidate/);
    });
    // Table rows for each invoice.
    expect(screen.getByTestId("lumino-backfill-preview-row-a"))
      .toBeInTheDocument();
    expect(screen.getByTestId("lumino-backfill-preview-row-b"))
      .toBeInTheDocument();
    expect(screen.getByTestId("lumino-backfill-preview-row-c"))
      .toBeInTheDocument();
  });
});


describe("LuminoBackfillPage · run backfill flow", () => {
  it("opens confirm modal, only fires POST after user confirms", async () => {
    // 1st call = preview to populate the candidate count.
    postMock.mockResolvedValueOnce({
      dry_run: true,
      total_candidates: 2,
      dispatched: 0, skipped: 0, errors: 0,
      results: [
        {invoice_id: "a", invoice_number: "INV-A", customer_name: "A",
          total: 100, status: "sent", created_at: "2026-01-01T00:00:00Z"},
        {invoice_id: "b", invoice_number: "INV-B", customer_name: "B",
          total: 200, status: "sent", created_at: "2026-01-01T00:00:00Z"},
      ],
    });
    renderPage();
    // Untick Dry-run so the Run button becomes enabled once we
    // have preview data.
    fireEvent.click(screen.getByTestId("lumino-backfill-dry-run-toggle"));
    // Run preview to populate the candidate count.
    fireEvent.click(screen.getByTestId("lumino-backfill-preview-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("lumino-backfill-preview-count"))
        .toBeInTheDocument();
    });
    // 1 POST so far (the preview).
    expect(postMock).toHaveBeenCalledTimes(1);
    // Click Run — should open confirm modal but NOT fire POST.
    const runBtn = screen.getByTestId("lumino-backfill-run-btn");
    expect(runBtn).not.toBeDisabled();
    fireEvent.click(runBtn);
    await waitFor(() => {
      expect(screen.getByTestId("lumino-backfill-confirm-modal"))
        .toBeInTheDocument();
    });
    // No new POST fired yet — still just the preview call.
    expect(postMock).toHaveBeenCalledTimes(1);
    // Prep the live-run response.
    postMock.mockResolvedValueOnce({
      dry_run: false,
      total_candidates: 2,
      dispatched: 2, skipped: 0, errors: 0,
      results: [
        {invoice_id: "a", invoice_number: "INV-A", status: "dispatched",
          correlation_id: "corr-a", reason: null},
        {invoice_id: "b", invoice_number: "INV-B", status: "dispatched",
          correlation_id: "corr-b", reason: null},
      ],
    });
    // Cancel first — POST should NOT fire.
    fireEvent.click(screen.getByTestId("lumino-backfill-confirm-cancel"));
    await waitFor(() => {
      expect(screen.queryByTestId("lumino-backfill-confirm-modal"))
        .not.toBeInTheDocument();
    });
    expect(postMock).toHaveBeenCalledTimes(1);
    // Now open again and confirm.
    fireEvent.click(screen.getByTestId("lumino-backfill-run-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("lumino-backfill-confirm-modal"))
        .toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("lumino-backfill-confirm-proceed"));
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledTimes(2);
    });
    const [path2, body2] = postMock.mock.calls[1];
    expect(path2).toBe("/admin/lumino/backfill-payment-links");
    expect(body2.dry_run).toBe(false);
    // Results table rendered.
    await waitFor(() => {
      expect(screen.getByTestId("lumino-backfill-results-panel"))
        .toBeInTheDocument();
    });
    expect(screen.getByTestId("lumino-backfill-dispatched-count")
              .textContent).toMatch(/2 dispatched/);
    expect(screen.getByTestId("lumino-backfill-result-row-a"))
      .toBeInTheDocument();
  });

  it("Run button stays disabled while dry_run is checked", async () => {
    postMock.mockResolvedValueOnce({
      dry_run: true,
      total_candidates: 5,
      dispatched: 0, skipped: 0, errors: 0,
      results: [],
    });
    renderPage();
    fireEvent.click(screen.getByTestId("lumino-backfill-preview-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("lumino-backfill-preview-count"))
        .toBeInTheDocument();
    });
    // Dry-run is on (default) — Run button must be disabled.
    expect(screen.getByTestId("lumino-backfill-run-btn")).toBeDisabled();
  });

  it("Run button is disabled when preview count is 0", async () => {
    postMock.mockResolvedValueOnce({
      dry_run: true,
      total_candidates: 0,
      dispatched: 0, skipped: 0, errors: 0,
      results: [],
    });
    renderPage();
    // Untick Dry-run.
    fireEvent.click(screen.getByTestId("lumino-backfill-dry-run-toggle"));
    fireEvent.click(screen.getByTestId("lumino-backfill-preview-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("lumino-backfill-preview-count"))
        .toBeInTheDocument();
    });
    expect(screen.getByTestId("lumino-backfill-run-btn")).toBeDisabled();
  });
});
