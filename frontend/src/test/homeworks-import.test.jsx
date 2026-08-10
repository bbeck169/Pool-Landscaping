/**
 * Phase 55-a · Aug-2026 — HomeworksImport (Copilot CRM importer)
 * frontend scaffold vitest.
 *
 * Covers the three shipped surfaces:
 *   1. Credentials card — save button POSTs to
 *      ``/imports/homeworks/credentials`` and reloads the presence
 *      indicator.
 *   2. New batch modal — fires ``POST /imports/homeworks/batches``
 *      with the selected entity_types_planned and refreshes the list.
 *   3. Batch list — renders empty state and populated rows,
 *      including the state pill + rollback CTA (hidden on
 *      ``rolled_back`` rows).
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Shared api mock — must come before component imports. ──
const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args),
          post: (...args) => postMock(...args) },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#fafafa",
    surfaceTertiary: "#eee", border: "#ddd",
    muted: "#666", onSurface: "#000", brand: "#0891B2",
  },
}));

vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

import HomeworksImport from "@/pages/settings/HomeworksImport";


function renderPage() {
  return render(
    <MemoryRouter>
      <HomeworksImport />
    </MemoryRouter>,
  );
}


describe("HomeworksImport · Phase 55-a scaffold", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });
  afterEach(() => { cleanup(); });

  it("renders the empty state when no batches exist", async () => {
    getMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        return Promise.resolve({ batches: [] });
      }
      if (url === "/imports/homeworks/credentials") {
        return Promise.resolve({ has_credentials: false });
      }
      return Promise.resolve({});
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("hw-batches-empty")).toBeTruthy();
    });
    expect(screen.getByTestId("homeworks-import-page")).toBeTruthy();
    expect(screen.getByTestId("hw-new-batch-btn")).toBeTruthy();
    // Credentials card starts in the "no creds cached" state.
    expect(screen.queryByTestId("hw-creds-cached-line")).toBeNull();
  });

  it("saves credentials via POST /imports/homeworks/credentials", async () => {
    getMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        return Promise.resolve({ batches: [] });
      }
      return Promise.resolve({ has_credentials: false });
    });
    postMock.mockResolvedValue({ ok: true, updated_at: "2026-08-10" });

    renderPage();

    await waitFor(() => screen.getByTestId("hw-creds-save"));

    fireEvent.change(screen.getByTestId("hw-creds-email"),
                      { target: { value: "user@copilot.com" } });
    fireEvent.change(screen.getByTestId("hw-creds-password"),
                      { target: { value: "hunter2" } });
    fireEvent.click(screen.getByTestId("hw-creds-save"));

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith(
        "/imports/homeworks/credentials",
        { email: "user@copilot.com", password: "hunter2" },
      );
    });
  });

  it("opens the new-batch modal and POSTs the selected entity types", async () => {
    let postCount = 0;
    getMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        return Promise.resolve({
          batches: postCount === 0 ? [] : [{
            id: "batch-abc123", state: "pending",
            entity_types_planned: ["customers"],
            started_at: null,
          }],
        });
      }
      return Promise.resolve({ has_credentials: false });
    });
    postMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        postCount += 1;
        return Promise.resolve({ id: "batch-abc123", state: "pending" });
      }
      return Promise.resolve({ ok: true });
    });

    renderPage();

    await waitFor(() => screen.getByTestId("hw-new-batch-btn"));
    fireEvent.click(screen.getByTestId("hw-new-batch-btn"));

    const modal = await screen.findByTestId("hw-new-batch-modal");
    // All 8 checkboxes render.
    expect(within(modal).getByTestId("hw-new-batch-entity-customers"))
      .toBeTruthy();
    expect(within(modal).getByTestId("hw-new-batch-entity-jobs"))
      .toBeTruthy();

    // Untick everything except "customers" — verify the POST body.
    ["properties", "jobs", "recurring_schedules", "invoices",
     "payments", "quotes", "attachments"].forEach((t) => {
      fireEvent.click(within(modal).getByTestId(`hw-new-batch-entity-${t}`));
    });

    fireEvent.click(within(modal).getByTestId("hw-new-batch-submit"));

    await waitFor(() => {
      const call = postMock.mock.calls.find(
        ([u]) => u === "/imports/homeworks/batches");
      expect(call).toBeTruthy();
      expect(call[1]).toEqual({
        entity_types_planned: ["customers"],
      });
    });

    // Modal closes and batch list re-renders with the new row.
    await waitFor(() => {
      expect(screen.queryByTestId("hw-new-batch-modal")).toBeNull();
    });
    await waitFor(() => {
      expect(screen.getByTestId("hw-batch-row-batch-abc123")).toBeTruthy();
    });
    // State pill visible + rollback button offered on pending batches.
    expect(screen.getByTestId("hw-batch-state-batch-abc123")).toBeTruthy();
    expect(screen.getByTestId("hw-batch-rollback-batch-abc123")).toBeTruthy();
  });
});


// ═════════════════════════════════════════════════════════════════
// Phase 55-f — Dry-run + Commit + Progress polling
// ═════════════════════════════════════════════════════════════════
describe("HomeworksImport · Phase 55-f detail drawer", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  function seedListMock(batchState) {
    const batch = {
      id: "batch-detail-1", state: batchState,
      entity_types_planned: ["customers"],
      started_at: null,
    };
    const dryrun = {
      batch_id: "batch-detail-1", state: batchState,
      entity_counts: {
        customers: { new: 3, matched: 1, conflict: 1, total: 5 },
      },
      warnings: [],
      error_count: 0,
    };
    const progress = {
      batch_id: "batch-detail-1", state: batchState,
      entity_counts_completed: {},
      entity_counts_total: {},
      current_entity_type: null,
      error_count: 0,
    };
    getMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        return Promise.resolve({ batches: [batch] });
      }
      if (url === "/imports/homeworks/credentials") {
        return Promise.resolve({ has_credentials: false });
      }
      if (url === `/imports/homeworks/batches/${batch.id}/dryrun`) {
        return Promise.resolve(dryrun);
      }
      if (url === `/imports/homeworks/batches/${batch.id}/progress`) {
        return Promise.resolve(progress);
      }
      return Promise.resolve({});
    });
    return { batch, dryrun, progress };
  }

  it("renders the dry-run report table when the drawer opens", async () => {
    seedListMock("paused");
    renderPage();

    await waitFor(() => screen.getByTestId("hw-batch-view-batch-detail-1"));
    fireEvent.click(screen.getByTestId("hw-batch-view-batch-detail-1"));

    const drawer = await screen.findByTestId("hw-detail-drawer");
    await waitFor(() => {
      expect(within(drawer).getByTestId("hw-detail-dryrun-table"))
        .toBeTruthy();
    });
    // Row for customers with per-status counts.
    const row = within(drawer).getByTestId("hw-detail-row-customers");
    expect(row.textContent).toContain("customers");
    expect(row.textContent).toContain("3");   // new
    expect(row.textContent).toContain("5");   // total
  });

  it("disables the Commit button unless state == paused", async () => {
    seedListMock("pending");
    renderPage();

    await waitFor(() => screen.getByTestId("hw-batch-view-batch-detail-1"));
    fireEvent.click(screen.getByTestId("hw-batch-view-batch-detail-1"));

    await screen.findByTestId("hw-detail-drawer");
    // With batch in "pending" state, neither commit nor resume CTAs
    // render — canCommit==false, canResume==false.
    expect(screen.queryByTestId("hw-commit-btn")).toBeNull();
    expect(screen.queryByTestId("hw-resume-btn")).toBeNull();
  });

  it("polls the /progress endpoint every 2s once commit is clicked", async () => {
    seedListMock("paused");
    postMock.mockResolvedValue({
      ok: true, batch_id: "batch-detail-1", state: "committed",
      entity_counts_completed: { customers: 5 }, error_count: 0,
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });

    renderPage();
    await waitFor(() => screen.getByTestId("hw-batch-view-batch-detail-1"));
    fireEvent.click(screen.getByTestId("hw-batch-view-batch-detail-1"));

    const drawer = await screen.findByTestId("hw-detail-drawer");
    await waitFor(() =>
      expect(within(drawer).getByTestId("hw-commit-btn")).toBeTruthy());

    // Snapshot initial progress-endpoint call count from the opening
    // parallel-fetch, then click commit.
    const progressUrl = "/imports/homeworks/batches/batch-detail-1/progress";
    const baselineCalls = getMock.mock.calls
      .filter(([u]) => u === progressUrl).length;

    fireEvent.click(within(drawer).getByTestId("hw-commit-btn"));

    // Fast-forward 2s → one poll tick.
    await vi.advanceTimersByTimeAsync(2100);
    await waitFor(() => {
      const now = getMock.mock.calls
        .filter(([u]) => u === progressUrl).length;
      expect(now).toBeGreaterThan(baselineCalls);
    });
    // The POST /commit call fired.
    expect(postMock).toHaveBeenCalledWith(
      "/imports/homeworks/batches/batch-detail-1/commit", {});
  });
});
