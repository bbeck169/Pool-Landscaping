/**
 * Phase 56-e · Aug-2026 — Legacy ``cost`` field removed from the
 * Ops Hub Price Book "Add new item" modal.
 *
 * Locks:
 *   • The "Add new item" modal renders NO ``pb-new-cost`` input.
 *   • Save fires POST /api/items with NO ``cost`` key in the payload.
 *
 * Deleting the field entirely (vs. hiding it) means legacy callers
 * can't sneak a value in via a stale form state either.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    del: (...a) => delMock(...a),
  },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "a@x" } }),
  AuthProvider: ({ children }) => children,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));

import { PriceBook } from "@/pages/ops/OpsHub";


function seed(rows) {
  getMock.mockImplementation(async (path) => {
    if (path === "/items") return rows;
    if (path === "/service-categories") {
      return [{ id: "sc-1", name: "Pool", is_archived: false }];
    }
    if (path === "/income-categories") return { items: [] };
    if (path === "/pricebook/suppliers") return [];
    return [];
  });
}

function mount() {
  return render(
    <MemoryRouter>
      <PriceBook />
    </MemoryRouter>,
  );
}


describe("PriceBook · legacy cost field removed · Phase 56-e", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });
  afterEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });

  it("Add-item modal no longer renders the legacy pb-new-cost input", async () => {
    seed([]);
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    // Modal opened — Save button is present.
    await screen.findByTestId("pb-new-save");
    // Legacy cost input MUST NOT exist.
    expect(screen.queryByTestId("pb-new-cost")).not.toBeInTheDocument();
    // Surviving inputs are still there — service category, name, unit price, tax.
    expect(screen.getByTestId("pb-new-name")).toBeInTheDocument();
    expect(screen.getByTestId("pb-new-service-category")).toBeInTheDocument();
    expect(screen.getByTestId("pb-new-price")).toBeInTheDocument();
    expect(screen.getByTestId("pb-new-tax")).toBeInTheDocument();
  });

  it("Save fires POST /items with NO 'cost' key in the payload", async () => {
    seed([]);
    postMock.mockResolvedValueOnce({ id: "new-1" });
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-save");
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-name"), {
        target: { value: "Chlorine Post-Cleanup" },
      });
      fireEvent.change(screen.getByTestId("pb-new-service-category"), {
        target: { value: "sc-1" },
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("pb-new-save"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [path, payload] = postMock.mock.calls[0];
    expect(path).toBe("/items");
    // The critical assertion — the entire form-derived payload has
    // NO ``cost`` key. Not undefined-under-that-key, not a null
    // value. It literally must not appear on the object.
    expect(Object.hasOwn(payload, "cost")).toBe(false);
  });
});
