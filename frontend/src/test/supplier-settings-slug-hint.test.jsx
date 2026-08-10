/**
 * Aug-2026 · UX cleanup for the Supplier Settings page.
 *
 * The "Test connection" button now:
 *   • shows the supplier's ``display_name`` inline (e.g.
 *     "Test connection · Pool360 (PoolCorp)") so operators aren't
 *     surprised when backend logs mention the ``poolcorp`` slug.
 *   • renders a small monospace ``<code>`` hint next to the button
 *     with the raw slug for debugging.
 *
 * Locked by two focused assertions rendered against a minimal
 * SupplierSettings mount with a single supplier row.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a), post: vi.fn(), put: vi.fn(),
    del: vi.fn(), patch: vi.fn(),
  },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", email: "s@x", role: "super_admin" } }),
  AuthProvider: ({ children }) => children,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));

import SupplierSettings from "@/pages/settings/SupplierSettings";

const POOL360 = {
  id: "s-poolcorp",
  slug: "poolcorp",
  display_name: "Pool360 (PoolCorp)",
  active: true,
  sync_frequency: "weekly",
};

describe("Fix UX · Supplier Settings — display_name + slug hint next to Test connection", () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockImplementation(async (path) => {
      if (path === "/suppliers") return [POOL360];
      if (path.endsWith("/credentials")) {
        return { has_credentials: true, updated_at: "2026-08-10T00:00:00Z" };
      }
      if (path.endsWith("/sync-jobs")) return [];
      return {};
    });
  });
  afterEach(() => { getMock.mockReset(); });

  it("renders the display_name inline on the Test connection button", async () => {
    await act(async () => {
      render(
        <MemoryRouter>
          <SupplierSettings />
        </MemoryRouter>,
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("supplier-poolcorp-test-connection-btn"))
        .toBeInTheDocument(),
    );
    const btn = screen.getByTestId("supplier-poolcorp-test-connection-btn");
    expect(btn.textContent).toMatch(/Test connection/);
    expect(btn.textContent).toMatch(/Pool360 \(PoolCorp\)/);
    // Tooltip carries the raw slug for admin debugging correlation.
    expect(btn.getAttribute("title")).toBe("Slug: poolcorp");
  });

  it("renders the raw slug in a monospace hint next to the button", async () => {
    await act(async () => {
      render(
        <MemoryRouter>
          <SupplierSettings />
        </MemoryRouter>,
      );
    });
    await waitFor(() =>
      expect(screen.getByTestId("supplier-poolcorp-slug-hint"))
        .toBeInTheDocument(),
    );
    const hint = screen.getByTestId("supplier-poolcorp-slug-hint");
    expect(hint.textContent).toBe("poolcorp");
    expect(hint.tagName.toLowerCase()).toBe("code");
  });
});
