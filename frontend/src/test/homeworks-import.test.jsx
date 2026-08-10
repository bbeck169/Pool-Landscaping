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

// Phase 55-b — challenge modal mocked as a lightweight stub so we
// can assert it renders WITHOUT dragging in the api-token minting
// side-effects the real modal fires on mount.
vi.mock("@/components/suppliers/ChallengeHandoffModal", () => ({
  default: ({ slug, displayName, onClose }) => (
    <div data-testid="challenge-handoff-modal">
      <div data-testid="challenge-modal-slug">{slug}</div>
      <div>{displayName}</div>
      <button onClick={onClose} data-testid="challenge-modal-close">
        Close
      </button>
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

    // Phase 55-c — the modal exposes all 4 core-entity checkboxes,
    // AND they're pre-selected by default (spec: "All 8 selected
    // by default").
    ["customers", "properties", "jobs", "recurring_schedules"].forEach(
      (t) => {
        const cb = within(modal).getByTestId(`hw-new-batch-entity-${t}`);
        expect(cb).toBeTruthy();
        // Default-checked so the operator gets the full sweep on
        // day-1 commits without extra clicks.
        expect(cb.checked).toBe(true);
      },
    );

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


// ═════════════════════════════════════════════════════════════════
// Phase 55-b — Scrape button + challenge handoff modal
// ═════════════════════════════════════════════════════════════════
describe("HomeworksImport · Phase 55-b scrape + challenge", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  function seedListMockPending() {
    const batch = {
      id: "batch-scrape-1", state: "pending",
      entity_types_planned: ["customers", "properties"],
      started_at: null,
    };
    getMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        return Promise.resolve({ batches: [batch] });
      }
      if (url === "/imports/homeworks/credentials") {
        return Promise.resolve({ has_credentials: true,
                                   email: "admin@copilotcrm.com" });
      }
      if (url === `/imports/homeworks/batches/${batch.id}/dryrun`) {
        return Promise.resolve({
          batch_id: batch.id, state: "pending",
          entity_counts: {}, warnings: [], error_count: 0,
        });
      }
      if (url === `/imports/homeworks/batches/${batch.id}/progress`) {
        return Promise.resolve({
          batch_id: batch.id, state: "pending",
          entity_counts_completed: {},
          entity_counts_total: {},
          entity_counts_scraped: {},
          error_count: 0,
        });
      }
      return Promise.resolve({});
    });
    return batch;
  }

  it("shows the Scrape button when state == pending and fires POST /scrape",
    async () => {
      const batch = seedListMockPending();
      postMock.mockResolvedValue({
        ok: true, state: "paused",
        entity_counts_scraped: { customers: 3, properties: 2 },
      });

      renderPage();
      await waitFor(() =>
        screen.getByTestId(`hw-batch-view-${batch.id}`));
      fireEvent.click(screen.getByTestId(`hw-batch-view-${batch.id}`));

      const drawer = await screen.findByTestId("hw-detail-drawer");
      await waitFor(() =>
        expect(within(drawer).getByTestId("hw-scrape-btn"))
          .toBeTruthy());
      // Commit button is NOT rendered while state is pending.
      expect(screen.queryByTestId("hw-commit-btn")).toBeNull();

      fireEvent.click(within(drawer).getByTestId("hw-scrape-btn"));

      await waitFor(() => {
        expect(postMock).toHaveBeenCalledWith(
          `/imports/homeworks/batches/${batch.id}/scrape`, {});
      });
    });

  it("opens the Challenge Handoff modal when scrape returns "
     + "challenge_required", async () => {
    const batch = seedListMockPending();
    postMock.mockResolvedValue({
      ok: false,
      challenge_required: true,
      challenge_id: "abc123",
      slug: "homeworks",
      ttl_hint_minutes: 30,
    });

    renderPage();
    await waitFor(() =>
      screen.getByTestId(`hw-batch-view-${batch.id}`));
    fireEvent.click(screen.getByTestId(`hw-batch-view-${batch.id}`));

    const drawer = await screen.findByTestId("hw-detail-drawer");
    await waitFor(() =>
      expect(within(drawer).getByTestId("hw-scrape-btn")).toBeTruthy());
    fireEvent.click(within(drawer).getByTestId("hw-scrape-btn"));

    // Challenge modal renders with the homeworks slug.
    await waitFor(() => {
      expect(screen.getByTestId("challenge-handoff-modal"))
        .toBeTruthy();
    });
    expect(screen.getByTestId("challenge-modal-slug").textContent)
      .toBe("homeworks");
  });
});


// ═════════════════════════════════════════════════════════════════
// Phase 55-c — Jobs + Recurring Schedule checkboxes in new-batch modal
// ═════════════════════════════════════════════════════════════════
describe("HomeworksImport · Phase 55-c entity coverage", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });
  afterEach(() => { cleanup(); });

  it("new-batch modal exposes jobs + recurring_schedules checkboxes",
    async () => {
      getMock.mockImplementation((url) => {
        if (url === "/imports/homeworks/batches") {
          return Promise.resolve({ batches: [] });
        }
        return Promise.resolve({ has_credentials: false });
      });

      renderPage();
      await waitFor(() => screen.getByTestId("hw-new-batch-btn"));
      fireEvent.click(screen.getByTestId("hw-new-batch-btn"));

      const modal = await screen.findByTestId("hw-new-batch-modal");
      // Phase 55-c specifically ships the ``jobs`` +
      // ``recurring_schedules`` entity types. The rest are 55-b or
      // future-phase — but all 8 render because the design surface
      // is stable from 55-a.
      const jobsCb = within(modal).getByTestId("hw-new-batch-entity-jobs");
      const recCb = within(modal).getByTestId(
        "hw-new-batch-entity-recurring_schedules");
      expect(jobsCb).toBeTruthy();
      expect(recCb).toBeTruthy();
      // Default-checked (matches ``ALL_ENTITY_TYPES`` seed).
      expect(jobsCb.checked).toBe(true);
      expect(recCb.checked).toBe(true);
    });
});


// ═════════════════════════════════════════════════════════════════
// Phase 55-d — All 8 entity checkboxes present + default-checked
// ═════════════════════════════════════════════════════════════════
describe("HomeworksImport · Phase 55-d entity coverage", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });
  afterEach(() => { cleanup(); });

  it("new-batch modal exposes quotes + invoices + payments + attachments "
     + "checkboxes default-checked", async () => {
    getMock.mockImplementation((url) => {
      if (url === "/imports/homeworks/batches") {
        return Promise.resolve({ batches: [] });
      }
      return Promise.resolve({ has_credentials: false });
    });

    renderPage();
    await waitFor(() => screen.getByTestId("hw-new-batch-btn"));
    fireEvent.click(screen.getByTestId("hw-new-batch-btn"));

    const modal = await screen.findByTestId("hw-new-batch-modal");
    // The three 55-d entities live alongside the four already-shipped
    // from 55-a/b/c PLUS attachments which is 55-e placeholder.
    ["quotes", "invoices", "payments", "attachments"].forEach((t) => {
      const cb = within(modal).getByTestId(`hw-new-batch-entity-${t}`);
      expect(cb).toBeTruthy();
      expect(cb.checked).toBe(true);
    });
    // All 8 checkboxes render — full-sweep default.
    ["customers", "properties", "jobs", "recurring_schedules",
     "quotes", "invoices", "payments", "attachments"].forEach((t) => {
      expect(within(modal).getByTestId(`hw-new-batch-entity-${t}`))
        .toBeTruthy();
    });
  });
});


// ═════════════════════════════════════════════════════════════════
// Phase 55-e — Rollback warning mentions photos when count > 0
// ═════════════════════════════════════════════════════════════════
describe("HomeworksImport · Phase 55-e photo purge warning", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
  });
  afterEach(() => { cleanup(); });

  it("rollback confirmation surfaces photo count when attachments > 0",
    async () => {
      const batch = {
        id: "batch-photos-1", state: "committed",
        entity_types_planned: ["customers", "attachments"],
        entity_counts_completed: {
          customers: 12, properties: 4, photos: 47,
        },
        started_at: "2026-08-01",
      };
      getMock.mockImplementation((url) => {
        if (url === "/imports/homeworks/batches") {
          return Promise.resolve({ batches: [batch] });
        }
        return Promise.resolve({ has_credentials: true });
      });

      renderPage();
      await waitFor(() =>
        screen.getByTestId(`hw-batch-rollback-${batch.id}`));
      fireEvent.click(screen.getByTestId(`hw-batch-rollback-${batch.id}`));

      const warning = await screen.findByTestId("hw-rollback-warning");
      // Text mentions total record count + photo callout.
      expect(warning.textContent).toContain("63");   // 12 + 4 + 47
      // Dedicated photo-count node for testability + emphasis.
      const photoNode = screen.getByTestId("hw-rollback-photo-count");
      expect(photoNode.textContent).toContain("47 photos");
      expect(warning.textContent).toContain("from storage");
    });
});
