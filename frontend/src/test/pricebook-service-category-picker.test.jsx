/**
 * Aug-2026 · Fix P1 · Price Book "Add new item" — service category picker.
 *
 * Contract:
 *   • On modal mount the component fetches ``/service-categories`` and
 *     renders the active (non-archived) rows as <option>s under an
 *     empty "Select a service category…" placeholder.
 *   • The Save button is disabled while ``form.service_category_id``
 *     is empty AND when the fetch returns an empty list (with an
 *     inline hint about /settings/service-categories).
 *   • On Save with a picked category, ``POST /items`` fires with
 *     ``service_category_id`` in the body.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const delMock = vi.fn();
const patchMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    del: (...a) => delMock(...a),
    patch: (...a) => patchMock(...a),
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

const CATS = [
  { id: "sc-pool", name: "Pool", is_archived: false },
  { id: "sc-lawn", name: "Landscaping", is_archived: false },
  { id: "sc-old",  name: "Old Retired", is_archived: true },
];

function mount() {
  return render(
    <MemoryRouter>
      <PriceBook />
    </MemoryRouter>,
  );
}

describe("PriceBook · Add new item · service category picker · Fix P1", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset();
    delMock.mockReset(); patchMock.mockReset();
    getMock.mockImplementation(async (path) => {
      if (path === "/items") return [];
      if (path === "/service-categories") return CATS;
      return [];
    });
  });
  afterEach(() => { getMock.mockReset(); postMock.mockReset(); });

  it("renders the picker with only active (non-archived) categories", async () => {
    await act(async () => mount());
    await act(async () => {
      fireEvent.click(screen.getByTestId("pb-new"));
    });
    const select = await screen.findByTestId("pb-new-service-category");
    await waitFor(() => {
      const opts = Array.from(select.querySelectorAll("option"))
        .map((o) => o.textContent);
      expect(opts).toContain("Select a service category…");
      expect(opts).toContain("Pool");
      expect(opts).toContain("Landscaping");
      // Archived category MUST NOT appear.
      expect(opts).not.toContain("Old Retired");
    });
  });

  it("Save is disabled until a service category is picked", async () => {
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-service-category");
    const saveBtn = screen.getByTestId("pb-new-save");
    expect(saveBtn.disabled).toBe(true);
    // Pick a category.
    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-service-category"), {
        target: { value: "sc-pool" },
      });
    });
    expect(saveBtn.disabled).toBe(false);
  });

  it("Save fires POST /items with service_category_id included", async () => {
    postMock.mockResolvedValueOnce({ id: "item-1", name: "Test" });
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    await screen.findByTestId("pb-new-service-category");

    await act(async () => {
      fireEvent.change(screen.getByTestId("pb-new-name"), {
        target: { value: "Pentair IntelliFlo3" },
      });
      fireEvent.change(screen.getByTestId("pb-new-service-category"), {
        target: { value: "sc-pool" },
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("pb-new-save"));
    });
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledTimes(1);
    });
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/items");
    expect(body).toMatchObject({
      name: "Pentair IntelliFlo3",
      service_category_id: "sc-pool",
    });
  });

  it("empty categories list disables Save + shows the /settings/service-categories hint", async () => {
    // Override the mock to return no categories.
    getMock.mockImplementation(async (path) => {
      if (path === "/items") return [];
      if (path === "/service-categories") return [];
      return [];
    });
    await act(async () => mount());
    await act(async () => { fireEvent.click(screen.getByTestId("pb-new")); });
    // Wait for the fetch to settle.
    await waitFor(() =>
      expect(screen.getByTestId("pb-new-service-category-empty"))
        .toBeInTheDocument(),
    );
    const hint = screen.getByTestId("pb-new-service-category-empty");
    expect(hint.textContent).toMatch(/\/settings\/service-categories/);
    expect(screen.getByTestId("pb-new-save").disabled).toBe(true);
  });
});
