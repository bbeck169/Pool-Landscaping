/**
 * Phase P3 · Feb-2026 · Deliverable 2 — Knowledge Library section.
 *
 * Mounts the full AI Brain page with a mocked KB list containing
 * both uploaded rows (``source_file_id`` set) and legacy manual
 * pastes (no ``source_file_id``).  Verifies:
 *
 *   1. Only rows with ``source_file_id`` render as Library cards.
 *   2. Search filters by title.
 *   3. Each card exposes View / Supersede / Delete affordances;
 *      Delete triggers the existing DELETE endpoint.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiDelete = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    patch: vi.fn(),
    delete: (...a) => apiDelete(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/components/common/ConfirmDeleteDialog", () => ({ default: () => null }));
vi.mock("@/components/admin/TopKBCitationsTile", () => ({ default: () => null }));

const _kbRows = [
  { id: "kb-pdf-1", title: "Pool Warranty Terms",
    kind: "policy", tags: ["warranty"],
    source_type: "pdf", source_file_id: "file-1",
    content_md: "The pump is covered for 2 years.",
    created_at: "2026-02-05T10:00:00Z", is_active: true },
  { id: "kb-docx-1", title: "Onboarding Checklist",
    kind: "custom", tags: [],
    source_type: "docx", source_file_id: "file-2",
    content_md: "New customer onboarding steps…",
    created_at: "2026-02-04T10:00:00Z", is_active: true },
  { id: "kb-manual-1", title: "Manually pasted FAQ",
    kind: "faq", tags: [],
    // NO source_file_id — legacy manual-paste, MUST NOT render.
    content_md: "Question / answer pasted directly.",
    created_at: "2026-02-03T10:00:00Z", is_active: true },
];

async function _wait(ms = 350) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiDelete.mockReset();
  apiGet.mockImplementation((path) => {
    if (path === "/ai/knowledge") return Promise.resolve({ items: _kbRows });
    if (String(path).startsWith("/ai/knowledge/system-prompt")) {
      return Promise.resolve({
        system_prompt: "…", retrieved: [], retrieved_count: 0,
        kb_row_count: 3, query: "",
      });
    }
    if (String(path).startsWith("/ai/copilot/top-questions")) {
      return Promise.resolve({ items: [] });
    }
    if (String(path).startsWith("/ai/employees/weekly-summary")) {
      return Promise.resolve({ ok: true });
    }
    if (String(path).startsWith("/tenants/business-card")) {
      return Promise.resolve({});
    }
    return Promise.resolve({});
  });
});


describe("Phase P3 D2 · Knowledge Library section", () => {
  it("renders only rows with source_file_id set", async () => {
    const AIBrainPage = (await import("@/pages/settings/AIBrainPage")).default;
    render(<AIBrainPage />);
    await _wait();

    // Uploaded rows render as cards.
    expect(await screen.findByTestId("kb-library-card-kb-pdf-1")).toBeInTheDocument();
    expect(screen.getByTestId("kb-library-card-kb-docx-1")).toBeInTheDocument();
    // Legacy manual-paste row is NOT in the grid.
    expect(screen.queryByTestId("kb-library-card-kb-manual-1")).toBeNull();
  });

  it("search filters the grid by title", async () => {
    const AIBrainPage = (await import("@/pages/settings/AIBrainPage")).default;
    render(<AIBrainPage />);
    await _wait();

    fireEvent.change(screen.getByTestId("kb-library-search"),
                       { target: { value: "warranty" } });

    expect(screen.getByTestId("kb-library-card-kb-pdf-1")).toBeInTheDocument();
    expect(screen.queryByTestId("kb-library-card-kb-docx-1")).toBeNull();
  });

  it("delete affordance calls the existing DELETE endpoint", async () => {
    apiDelete.mockResolvedValue({});
    const AIBrainPage = (await import("@/pages/settings/AIBrainPage")).default;
    render(<AIBrainPage />);
    await _wait();

    // View / Supersede / Delete all present on each card.
    expect(screen.getByTestId("kb-library-view-kb-pdf-1")).toBeInTheDocument();
    expect(screen.getByTestId("kb-library-supersede-kb-pdf-1")).toBeInTheDocument();
    const deleteBtn = screen.getByTestId("kb-library-delete-kb-pdf-1");
    await act(async () => {
      fireEvent.click(deleteBtn);
      await Promise.resolve();
    });
    expect(apiDelete).toHaveBeenCalledWith("/ai/knowledge/kb-pdf-1");
  });
});
