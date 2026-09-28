/**
 * HARD-DELETE · Sub-phase HD-A · Feb-2026 — Trash page vitest.
 *
 * Verifies:
 *   1. Renders every entity-type filter tab.
 *   2. Restore button hits /hard-delete/:type/:id/restore.
 *   3. Purge button is HIDDEN for admin (only visible for super_admin).
 *   4. Purge modal appears, confirmation calls the purge endpoint.
 *   5. Empty state renders when zero rows.
 *   6. Filter tab click filters the row set client-side.
 *   7. Nightly-purge controls only render for super_admin.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: (m) => toastSuccess(m),
    error: (m) => toastError(m),
  },
}));

import TrashPage from "@/pages/admin/TrashPage";

const TRASH_ROWS = [
  {
    id: "cust-1",
    entity_type: "customer",
    name: "Alice Smith",
    deleted_at: "2026-02-15T00:00:00Z",
    cascade_role: "root",
    cascade_batch_id: "cbatch_1",
    _collection: "customers",
  },
  {
    id: "job-1",
    entity_type: "job",
    title: "Weekly pool clean",
    deleted_at: "2026-02-14T00:00:00Z",
    cascade_role: "child",
    cascade_batch_id: "cbatch_1",
    _collection: "jobs",
  },
  {
    id: "inv-1",
    entity_type: "quote",
    invoice_number: "INV-1001",
    deleted_at: "2026-02-13T00:00:00Z",
    cascade_role: "child",
    cascade_batch_id: "cbatch_1",
    _collection: "quotes",
  },
];

function mockGet(rowsByPath = {}) {
  getMock.mockImplementation((path) => {
    if (path.startsWith("/hard-delete/trash")) {
      return Promise.resolve({
        count: TRASH_ROWS.length,
        items: rowsByPath.trash || TRASH_ROWS,
      });
    }
    if (path === "/auth/me") {
      return Promise.resolve(rowsByPath.me || { role: "admin" });
    }
    return Promise.resolve({});
  });
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

afterEach(cleanup);

describe("TrashPage", () => {
  it("renders trash rows fetched from the backend", async () => {
    mockGet();
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await screen.findByTestId("admin-trash-page");
    await waitFor(() =>
      expect(screen.getByTestId("trash-row-customer-cust-1")).toBeInTheDocument()
    );
    expect(screen.getByTestId("trash-row-job-job-1")).toBeInTheDocument();
    expect(screen.getByTestId("trash-row-quote-inv-1")).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith("/hard-delete/trash");
  });

  it("renders entity-type filter tabs", async () => {
    mockGet();
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await screen.findByTestId("trash-filter-all");
    expect(screen.getByTestId("trash-filter-customer")).toBeInTheDocument();
    expect(screen.getByTestId("trash-filter-job")).toBeInTheDocument();
    expect(screen.getByTestId("trash-filter-quote")).toBeInTheDocument();
    expect(screen.getByTestId("trash-filter-service_report")).toBeInTheDocument();
    expect(screen.getByTestId("trash-filter-file")).toBeInTheDocument();
  });

  it("hides Purge button and nightly controls for non-super admin", async () => {
    mockGet({ me: { role: "admin" } });
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("trash-row-customer-cust-1")).toBeInTheDocument()
    );
    expect(
      screen.queryByTestId("trash-purge-customer-cust-1")
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("trash-purge-hint-customer-cust-1")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("trash-super-controls")).not.toBeInTheDocument();
  });

  it("shows Purge button + nightly controls for super_admin", async () => {
    mockGet({ me: { role: "super_admin" } });
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("trash-super-controls")).toBeInTheDocument()
    );
    expect(
      screen.getByTestId("trash-purge-customer-cust-1")
    ).toBeInTheDocument();
    expect(screen.getByTestId("trash-nightly-dryrun")).toBeInTheDocument();
    expect(screen.getByTestId("trash-nightly-run")).toBeInTheDocument();
  });

  it("Restore posts to the correct endpoint and reloads", async () => {
    mockGet();
    postMock.mockResolvedValue({ ok: true });
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("trash-row-job-job-1")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId("trash-restore-job-job-1"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/job/job-1/restore",
        null
      )
    );
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("Purge flow: opens modal, confirms, posts with reason + skip_trash", async () => {
    mockGet({ me: { role: "super_admin" } });
    postMock.mockResolvedValue({ ok: true });
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("trash-purge-customer-cust-1")
      ).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId("trash-purge-customer-cust-1"));
    await screen.findByTestId("trash-purge-modal");
    fireEvent.change(screen.getByTestId("trash-purge-reason"), {
      target: { value: "GDPR request" },
    });
    fireEvent.click(screen.getByTestId("trash-purge-skip-trash"));
    fireEvent.click(screen.getByTestId("trash-purge-confirm"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/customer/cust-1/purge",
        { reason: "GDPR request", skip_trash: true }
      )
    );
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("shows empty state when no rows", async () => {
    getMock.mockResolvedValue({ count: 0, items: [] });
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("trash-empty")).toBeInTheDocument()
    );
  });

  it("entity-type tab click refetches with filter param", async () => {
    mockGet();
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await screen.findByTestId("trash-filter-customer");
    fireEvent.click(screen.getByTestId("trash-filter-customer"));
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        "/hard-delete/trash?entity_type=customer"
      )
    );
  });

  it("nightly dry-run button posts to dry-run endpoint (super only)", async () => {
    mockGet({ me: { role: "super_admin" } });
    getMock.mockImplementation((path) => {
      if (path.startsWith("/hard-delete/trash"))
        return Promise.resolve({ count: 0, items: [] });
      if (path === "/auth/me")
        return Promise.resolve({ role: "super_admin" });
      if (path === "/hard-delete/admin/nightly-purge/dry-run")
        return Promise.resolve({ candidates: 3, purged: 0, blocked: [] });
      return Promise.resolve({});
    });
    render(
      <MemoryRouter>
        <TrashPage />
      </MemoryRouter>
    );
    await screen.findByTestId("trash-nightly-dryrun");
    fireEvent.click(screen.getByTestId("trash-nightly-dryrun"));
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        "/hard-delete/admin/nightly-purge/dry-run"
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("trash-nightly-result")).toBeInTheDocument()
    );
  });
});
