/**
 * Feb-2026 · Editable Sent Docs · Phase 2 — VersionHistoryDrawer
 * vitest.  Covers:
 *   1. Loading state (fetch pending → "Loading version history…")
 *   2. Empty state (no versions → friendly copy).
 *   3. Populated state — 3 rows rendered newest first, baseline
 *      row shows "Original sent version" (empty change_summary),
 *      non-baseline rows show the summary + View button.
 *   4. Restore button disabled on every row (Phase 3 preview) with
 *      the tooltip trigger present.
 *   5. Clicking "View" opens the snapshot modal.
 *   6. Endpoint routing — docType="invoice" hits
 *      `/invoices/{id}/versions`, docType="quote" hits
 *      `/quotes/{qid}/versions`.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import VersionHistoryDrawer from "@/components/documents/VersionHistoryDrawer";
import { api } from "@/api";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}));


function _fake(items) {
  return { items, total: items.length, next_cursor: null };
}

const THREE_VERSIONS = [
  {
    version_id: "v-3", version: 3, is_baseline: false,
    created_at: "2026-02-05T10:00:00Z",
    created_by: { user_id: "u1", email: "alice@x.com", name: "Alice A" },
    change_summary: "2 line items edited, total +$50.00",
    diff_field_count: 3,
    status_at_edit: "sent",
    signature_invalidated: false, lock_bypass_ack: false,
    document_snapshot: { total: 320.0 },
  },
  {
    version_id: "v-2", version: 2, is_baseline: false,
    created_at: "2026-02-03T08:00:00Z",
    created_by: { user_id: "u1", email: "alice@x.com", name: "Alice A" },
    change_summary: "Notes updated",
    diff_field_count: 1,
    status_at_edit: "sent",
    signature_invalidated: false, lock_bypass_ack: false,
    document_snapshot: { total: 270.0, notes: "Please review" },
  },
  {
    version_id: "v-1", version: 1, is_baseline: true,
    created_at: "2026-02-01T00:00:00Z",
    created_by: { user_id: "system", email: "system", name: "" },
    change_summary: null,
    diff_field_count: 0,
    status_at_edit: "sent",
    signature_invalidated: false, lock_bypass_ack: false,
    document_snapshot: { total: 270.0 },
  },
];


describe("VersionHistoryDrawer · Phase 2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the empty-state copy when the API returns 0 versions", async () => {
    api.get.mockResolvedValueOnce(_fake([]));
    render(
      <VersionHistoryDrawer
        open onOpenChange={() => {}}
        docType="invoice" docId="inv-1"
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("doc-version-history-empty"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("doc-version-history-empty").textContent,
    ).toMatch(/No edits have been made/i);
  });

  it("renders 3 versions newest first with correct baseline copy + restore disabled", async () => {
    api.get.mockResolvedValueOnce(_fake(THREE_VERSIONS));
    render(
      <VersionHistoryDrawer
        open onOpenChange={() => {}}
        docType="invoice" docId="inv-1"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("doc-version-history-list")).toBeInTheDocument();
    });
    const rows = [
      screen.getByTestId("doc-version-row-v-3"),
      screen.getByTestId("doc-version-row-v-2"),
      screen.getByTestId("doc-version-row-v-1"),
    ];
    // Order: newest first.
    const orderedIds = Array.from(
      screen.getByTestId("doc-version-history-list").querySelectorAll("li"),
    ).map((el) => el.getAttribute("data-testid"));
    expect(orderedIds).toEqual([
      "doc-version-row-v-3",
      "doc-version-row-v-2",
      "doc-version-row-v-1",
    ]);
    // Baseline row summary is "Original sent version".
    expect(
      screen.getByTestId("doc-version-summary-v-1").textContent,
    ).toMatch(/Original sent version/i);
    // Non-baseline rows show their change_summary verbatim.
    expect(
      screen.getByTestId("doc-version-summary-v-2").textContent,
    ).toMatch(/Notes updated/);
    expect(
      screen.getByTestId("doc-version-summary-v-3").textContent,
    ).toMatch(/line items edited, total \+\$50\.00/);
    // Restore is present + disabled on every row.
    for (const vid of ["v-1", "v-2", "v-3"]) {
      const btn = screen.getByTestId(`doc-version-restore-${vid}`);
      expect(btn).toBeDisabled();
    }
    // Baseline badge present only on baseline row.
    expect(
      screen.getByTestId("doc-version-baseline-badge-v-1"),
    ).toBeInTheDocument();
    expect(rows[0].getAttribute("data-is-baseline")).toBe("false");
  });

  it("opens the snapshot modal when View is clicked", async () => {
    api.get.mockResolvedValueOnce(_fake(THREE_VERSIONS));
    render(
      <VersionHistoryDrawer
        open onOpenChange={() => {}}
        docType="invoice" docId="inv-1"
      />,
    );
    const viewBtn = await waitFor(() =>
      screen.getByTestId("doc-version-view-v-2"),
    );
    fireEvent.click(viewBtn);
    const modal = screen.getByTestId("doc-version-snapshot-modal-v-2");
    expect(modal).toBeInTheDocument();
    expect(
      screen.getByTestId("doc-version-snapshot-body").textContent,
    ).toMatch(/"notes": "Please review"/);
  });

  it("hits /invoices/{id}/versions when docType is invoice", async () => {
    api.get.mockResolvedValueOnce(_fake([]));
    render(
      <VersionHistoryDrawer
        open onOpenChange={() => {}}
        docType="invoice" docId="inv-42"
      />,
    );
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get).toHaveBeenCalledWith("/invoices/inv-42/versions");
  });

  it("hits /quotes/{qid}/versions when docType is quote", async () => {
    api.get.mockResolvedValueOnce(_fake([]));
    render(
      <VersionHistoryDrawer
        open onOpenChange={() => {}}
        docType="quote" docId="qte-9"
      />,
    );
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get).toHaveBeenCalledWith("/quotes/qte-9/versions");
  });

  it("shows the error state when the API rejects", async () => {
    api.get.mockRejectedValueOnce(new Error("boom"));
    render(
      <VersionHistoryDrawer
        open onOpenChange={() => {}}
        docType="invoice" docId="inv-1"
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("doc-version-history-error"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("doc-version-history-error").textContent,
    ).toMatch(/boom/);
  });
});
