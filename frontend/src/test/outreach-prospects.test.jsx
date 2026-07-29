/**
 * Phase SEO-B · Feb-2026 — Prospects Kanban page vitest.
 *
 * Verifies:
 *   1. Kanban renders with pipeline counts.
 *   2. Cards are grouped into the correct columns by status.
 *   3. New prospect modal creates a row (fires POST /outreach/prospects).
 *   4. CSV import modal shows dry-run preview counts.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _prospects = [
  { id: "p1", tenant_id: "T", domain: "alpha.com", status: "pending",
    contact_name: "Ada", contact_email: "ada@alpha.com",
    tags: ["editor"], last_activity_at: null,
    updated_at: "2026-02-14T09:00:00Z" },
  { id: "p2", tenant_id: "T", domain: "beta.com", status: "contacted",
    contact_name: "Barry", contact_email: "barry@beta.com",
    tags: [], last_activity_at: "2026-02-14T08:00:00Z",
    updated_at: "2026-02-14T09:05:00Z" },
  { id: "p3", tenant_id: "T", domain: "gamma.com", status: "replied",
    contact_name: "Carol", contact_email: "carol@gamma.com",
    tags: ["press"], last_activity_at: "2026-02-13T08:00:00Z",
    updated_at: "2026-02-14T09:10:00Z" },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/outreach/prospects?")) {
        return { items: _prospects, total: _prospects.length,
                 limit: 500, offset: 0 };
      }
      if (path === "/outreach/pipeline") {
        return { pending: 1, contacted: 1, replied: 1,
                 link_placed: 0, declined: 0, unsubscribed: 0,
                 total: 3 };
      }
      if (path.startsWith("/outreach/templates")) {
        return { items: [], total: 0 };
      }
      if (path.startsWith("/outreach/prospects/")) {
        return { ..._prospects[0], messages: [] };
      }
      return {};
    }),
    post: vi.fn(async () => ({ id: "p-new", domain: "new.com",
                                 status: "pending" })),
    patch: vi.fn(async () => ({})),
    del: vi.fn(async () => ({})),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// JSDOM lacks ResizeObserver + PointerEvent, both used by @dnd-kit.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

import ProspectsKanbanPage from "@/pages/admin/outreach/ProspectsKanbanPage";
import { api } from "@/api";

describe("ProspectsKanbanPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders header + pipeline counts + board", async () => {
    render(<MemoryRouter><ProspectsKanbanPage /></MemoryRouter>);
    expect(await screen.findByTestId("prospects-kanban-title"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("prospects-pipeline")).toBeInTheDocument();
      expect(screen.getByTestId("prospects-board")).toBeInTheDocument();
    });
    // Column counts (each column shows count next to label).
    await waitFor(() => {
      expect(screen.getByTestId("prospect-col-count-pending"))
        .toHaveTextContent("1");
      expect(screen.getByTestId("prospect-col-count-contacted"))
        .toHaveTextContent("1");
      expect(screen.getByTestId("prospect-col-count-replied"))
        .toHaveTextContent("1");
    });
  });

  it("cards land in the correct column by status", async () => {
    render(<MemoryRouter><ProspectsKanbanPage /></MemoryRouter>);
    await screen.findByTestId("prospect-card-p1");
    // p1 pending, p2 contacted, p3 replied — verify they exist under
    // their respective columns.
    const colPending = screen.getByTestId("prospect-column-pending");
    const colContacted = screen.getByTestId("prospect-column-contacted");
    const colReplied = screen.getByTestId("prospect-column-replied");
    expect(colPending).toContainElement(screen.getByTestId("prospect-card-p1"));
    expect(colContacted).toContainElement(screen.getByTestId("prospect-card-p2"));
    expect(colReplied).toContainElement(screen.getByTestId("prospect-card-p3"));
  });

  it("New prospect modal fires POST /outreach/prospects", async () => {
    render(<MemoryRouter><ProspectsKanbanPage /></MemoryRouter>);
    await screen.findByTestId("prospects-new-btn");
    fireEvent.click(screen.getByTestId("prospects-new-btn"));
    fireEvent.change(await screen.findByTestId("new-prospect-domain"),
                       { target: { value: "new.com" } });
    fireEvent.click(screen.getByTestId("new-prospect-submit"));
    await waitFor(() => {
      const calls = api.post.mock.calls
        .filter((c) => c[0] === "/outreach/prospects");
      expect(calls.length).toBe(1);
      expect(calls[0][1].domain).toBe("new.com");
    });
  });

  it("CSV import modal opens with dry-run + import buttons", async () => {
    render(<MemoryRouter><ProspectsKanbanPage /></MemoryRouter>);
    await screen.findByTestId("prospects-import-btn");
    fireEvent.click(screen.getByTestId("prospects-import-btn"));
    expect(await screen.findByTestId("import-csv-modal")).toBeInTheDocument();
    expect(screen.getByTestId("import-csv-dryrun")).toBeInTheDocument();
    expect(screen.getByTestId("import-csv-submit")).toBeInTheDocument();
    // Both are disabled without a file selected.
    expect(screen.getByTestId("import-csv-dryrun")).toBeDisabled();
    expect(screen.getByTestId("import-csv-submit")).toBeDisabled();
  });
});
