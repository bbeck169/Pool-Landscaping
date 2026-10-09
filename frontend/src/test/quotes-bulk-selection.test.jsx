/**
 * Phase 4b · Feb-2026 — Quotes bulk selection + bulk actions.
 *
 * Locks the frontend contract for the Phase 4b checkboxes +
 * sticky bulk toolbar on ``/quotes``:
 *
 *   1. Row + select-all checkboxes render for admin / super_admin
 *      / owner / manager.
 *   2. Toolbar appears when ≥1 row is checked; count is accurate.
 *   3. Select-all checkbox goes indeterminate on a partial subset
 *      and checked when every visible row is checked.
 *   4. Accept / Decline fire the matching ``POST
 *      /quotes/bulk-{accept,decline}`` with the exact id list.
 *   5. Delete opens a confirm modal first; firing OK on the modal
 *      calls ``POST /quotes/bulk-delete``.
 *   6. Toolbar + checkboxes are NOT rendered for the technician
 *      role (regression lock on the role gate).
 *   7. Toast text reflects the ``succeeded / skipped`` envelope
 *      shape (e.g. "3 accepted, 2 skipped (ineligible)").
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


let currentRole = "admin";

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: currentRole, email: `${currentRole}@x.y` },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));

const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock:  vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:   apiGetMock,
    post:  apiPostMock,
    patch: vi.fn(),
    put:   vi.fn(),
    del:   vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/components/customers/CustomerFilterBar", () => ({
  default: () => null,
}));


const _mockQuotes = [
  {
    id: "q-a", title: "Alpha quote", customer_id: "c-a",
    customer_name: "Alpha", total: 100, status: "draft",
    doc_type: "quote",
  },
  {
    id: "q-b", title: "Bravo quote", customer_id: "c-b",
    customer_name: "Bravo", total: 200, status: "sent",
    doc_type: "quote",
  },
  {
    id: "q-c", title: "Charlie quote", customer_id: "c-c",
    customer_name: "Charlie", total: 300, status: "draft",
    doc_type: "quote",
  },
];


beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  currentRole = "admin";
  apiGetMock.mockImplementation(async (url) => {
    if (url.startsWith("/quotes?")) return _mockQuotes;
    return [];
  });
  apiPostMock.mockResolvedValue({
    succeeded: ["q-a", "q-b"],
    skipped:   [],
    counts: { succeeded: 2, skipped: 0, total: 2 },
  });
});

afterEach(() => cleanup());


async function _renderList() {
  const { default: QuotesList } = await import(
    "@/pages/quotes/QuotesList.jsx"
  );
  const utils = render(
    <MemoryRouter initialEntries={["/quotes"]}>
      <QuotesList />
    </MemoryRouter>,
  );
  await waitFor(() => screen.getByTestId("quote-row-q-a"));
  return utils;
}


describe("Phase 4b · Quotes bulk — checkboxes, select-all, toolbar", () => {
  it("renders row + select-all checkboxes for admin role", async () => {
    await _renderList();
    expect(screen.getByTestId("quotes-select-all-checkbox")).toBeTruthy();
    expect(screen.getByTestId("quote-row-checkbox-q-a")).toBeTruthy();
    expect(screen.getByTestId("quote-row-checkbox-q-b")).toBeTruthy();
    expect(screen.getByTestId("quote-row-checkbox-q-c")).toBeTruthy();
  });

  it("toolbar is hidden when no row is checked", async () => {
    await _renderList();
    expect(screen.queryByTestId("quotes-bulk-toolbar")).toBeNull();
  });

  it("toolbar appears + shows accurate count when 1 row is checked", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    const toolbar = await screen.findByTestId("quotes-bulk-toolbar");
    expect(toolbar).toBeTruthy();
    expect(screen.getByTestId("quotes-bulk-toolbar-count").textContent)
      .toMatch(/1 quote selected/);
  });

  it("count updates as more rows are checked / unchecked", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-b"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-c"));
    expect(screen.getByTestId("quotes-bulk-toolbar-count").textContent)
      .toMatch(/3 quotes selected/);
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-b"));
    expect(screen.getByTestId("quotes-bulk-toolbar-count").textContent)
      .toMatch(/2 quotes selected/);
  });

  it("select-all checks every visible row + toggles back off", async () => {
    await _renderList();
    const header = screen.getByTestId("quotes-select-all-checkbox");
    fireEvent.click(header);
    expect(screen.getByTestId("quote-row-checkbox-q-a").checked).toBe(true);
    expect(screen.getByTestId("quote-row-checkbox-q-b").checked).toBe(true);
    expect(screen.getByTestId("quote-row-checkbox-q-c").checked).toBe(true);
    expect(screen.getByTestId("quotes-bulk-toolbar-count").textContent)
      .toMatch(/3 quotes selected/);
    fireEvent.click(screen.getByTestId("quotes-select-all-checkbox"));
    expect(screen.queryByTestId("quotes-bulk-toolbar")).toBeNull();
  });

  it("select-all goes INDETERMINATE on a partial subset", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    const header = screen.getByTestId("quotes-select-all-checkbox");
    expect(header.indeterminate).toBe(true);
    expect(header.checked).toBe(false);
    // Check the rest → indeterminate drops, checked flips true.
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-b"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-c"));
    expect(screen.getByTestId("quotes-select-all-checkbox").indeterminate)
      .toBe(false);
    expect(screen.getByTestId("quotes-select-all-checkbox").checked)
      .toBe(true);
  });

  it("Clear selection button empties the selection + hides the toolbar", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quotes-bulk-clear-btn"));
    expect(screen.queryByTestId("quotes-bulk-toolbar")).toBeNull();
  });
});


describe("Phase 4b · Quotes bulk — API wiring + toast", () => {
  it("Accept fires POST /quotes/bulk-accept with the exact id list", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-c"));
    fireEvent.click(screen.getByTestId("quotes-bulk-accept-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalled());
    const call = apiPostMock.mock.calls.find(
      (c) => c[0] === "/quotes/bulk-accept",
    );
    expect(call).toBeTruthy();
    expect(call[1]).toEqual({ quote_ids: ["q-a", "q-c"] });
  });

  it("Decline fires POST /quotes/bulk-decline with the exact id list", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-b"));
    fireEvent.click(screen.getByTestId("quotes-bulk-decline-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalled());
    const call = apiPostMock.mock.calls.find(
      (c) => c[0] === "/quotes/bulk-decline",
    );
    expect(call).toBeTruthy();
    expect(call[1]).toEqual({ quote_ids: ["q-b"] });
  });

  it("Delete requires confirm modal — NO POST until Delete button in modal is clicked", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quotes-bulk-delete-btn"));
    // Confirm modal renders.
    const modal = await screen.findByTestId("quotes-bulk-delete-confirm");
    expect(modal).toBeTruthy();
    // No bulk-delete POST yet.
    expect(
      apiPostMock.mock.calls.find((c) => c[0] === "/quotes/bulk-delete"),
    ).toBeUndefined();
    // Confirm fires the delete.
    fireEvent.click(screen.getByTestId("quotes-bulk-delete-confirm-ok"));
    await waitFor(() => {
      const call = apiPostMock.mock.calls.find(
        (c) => c[0] === "/quotes/bulk-delete",
      );
      expect(call).toBeTruthy();
      expect(call[1]).toEqual({ quote_ids: ["q-a"] });
    });
  });

  it("Delete confirm modal Cancel does NOT fire the POST", async () => {
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quotes-bulk-delete-btn"));
    await screen.findByTestId("quotes-bulk-delete-confirm");
    fireEvent.click(screen.getByTestId("quotes-bulk-delete-confirm-cancel"));
    expect(screen.queryByTestId("quotes-bulk-delete-confirm")).toBeNull();
    expect(
      apiPostMock.mock.calls.find((c) => c[0] === "/quotes/bulk-delete"),
    ).toBeUndefined();
  });

  it("Toast reflects partial-eligibility response envelope", async () => {
    apiPostMock.mockResolvedValueOnce({
      succeeded: ["q-a", "q-b", "q-c"],
      skipped:   [
        { id: "q-x", reason: "not_found" },
        { id: "q-y", reason: "already_declined" },
      ],
      counts: { succeeded: 3, skipped: 2, total: 5 },
    });
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-b"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-c"));
    fireEvent.click(screen.getByTestId("quotes-bulk-accept-btn"));
    // The Toast component renders by testid ``toast-root`` in ui-kit;
    // whichever node carries the text, assert the substring surface.
    await waitFor(() => {
      expect(document.body.textContent)
        .toMatch(/3 accepted, 2 skipped \(ineligible\)/);
    });
  });

  it("Toast reflects 'N <verb>' when every row succeeds", async () => {
    apiPostMock.mockResolvedValueOnce({
      succeeded: ["q-a", "q-b"], skipped: [],
      counts: { succeeded: 2, skipped: 0, total: 2 },
    });
    await _renderList();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-b"));
    fireEvent.click(screen.getByTestId("quotes-bulk-decline-btn"));
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/2 declined/);
      expect(document.body.textContent).not.toMatch(/skipped/);
    });
  });
});


describe("Phase 4b · Quotes bulk — role gate", () => {
  it("Technician does NOT see checkboxes or the toolbar", async () => {
    currentRole = "technician";
    await _renderList();
    expect(screen.queryByTestId("quotes-select-all-checkbox")).toBeNull();
    expect(screen.queryByTestId("quote-row-checkbox-q-a")).toBeNull();
    expect(screen.queryByTestId("quotes-bulk-toolbar")).toBeNull();
  });

  it("Manager DOES see checkboxes and can trigger the toolbar", async () => {
    currentRole = "manager";
    await _renderList();
    expect(screen.getByTestId("quotes-select-all-checkbox")).toBeTruthy();
    fireEvent.click(screen.getByTestId("quote-row-checkbox-q-a"));
    expect(screen.getByTestId("quotes-bulk-toolbar")).toBeTruthy();
  });
});
