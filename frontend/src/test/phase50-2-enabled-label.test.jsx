/**
 * Phase 50.2 · Feb-2026 — AI Employees list enabled/disabled label
 * parity guard.
 *
 * The pre-Phase-50 UI read from ``e.enabled`` — a legacy field the
 * current seed no longer writes. Every card was rendering a stale
 * "disabled" label even when the backend row had ``active=true``.
 * This test locks in the fix: the label is now driven by ``e.active``.
 *
 * Also asserts the label is null-safe when ``memory_scope`` is
 * missing on newer rows (avoids the "Active · undefined" cosmetic
 * regression that showed up alongside the primary bug).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Stub the api layer — the factory returns a jest.fn() that each test
// primes via ``mockResolvedValueOnce``. ``vi.mock`` is hoisted above
// module scope, so we can't reference any test-local ``ROWS`` const
// here — we set the resolved value inside ``beforeEach`` instead.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));

import { api } from "@/api";
import { AiEmployeesList } from "@/pages/aiops/AiOpsPages";

const ROWS = [
  {
    id: "emp-active",
    slug: "billy",
    name: "Billy",
    role: "Billing concierge",
    avatar_url: "/avatars/personas/billy.jpg",
    active: true,
    memory_scope: "per-tenant",
  },
  {
    id: "emp-inactive",
    slug: "scouty",
    name: "Scouty",
    role: "Recruiting",
    avatar_url: "/avatars/personas/scouty.jpg",
    active: false,
    // memory_scope intentionally omitted — regression guard against
    // the "· undefined" trailer that used to show up in the label.
  },
];

describe("Phase 50.2 · AiEmployeesList enabled/disabled label", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockResolvedValue(ROWS);
  });
  it("renders 'Active' for a row with active=true", async () => {
    render(
      <MemoryRouter>
        <AiEmployeesList />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const el = screen.getByTestId("ai-emp-state-billy");
      expect(el.textContent).toMatch(/Active/i);
      expect(el.textContent).not.toMatch(/Disabled/i);
    });
  });

  it("renders 'Disabled' for a row with active=false", async () => {
    render(
      <MemoryRouter>
        <AiEmployeesList />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const el = screen.getByTestId("ai-emp-state-scouty");
      expect(el.textContent).toMatch(/Disabled/i);
      expect(el.textContent).not.toMatch(/Active/i);
    });
  });

  it("omits the memory_scope trailer when the field is missing (no 'undefined' leak)", async () => {
    render(
      <MemoryRouter>
        <AiEmployeesList />
      </MemoryRouter>,
    );
    await waitFor(() => {
      // Scouty has no memory_scope — the row must render *without*
      // the " · undefined" trailer.
      const card = screen.getByTestId("ai-emp-scouty");
      expect(card.textContent).not.toMatch(/undefined/);
    });
  });

  it("no card reads from the legacy ``enabled`` field (all inactive rows say Disabled)", async () => {
    // Regression guard — if a future refactor accidentally reintroduces
    // ``e.enabled ? … : …`` while ``e.active`` is still true, this test
    // would still pass. To lock the actual source of truth, we render
    // rows where ``enabled`` is DELIBERATELY the opposite of ``active``
    // and assert the label follows ``active`` (not ``enabled``).
    const conflictRow = [
      {
        id: "emp-conflict",
        slug: "riley",
        name: "Riley",
        role: "Scheduling",
        avatar_url: null,
        active: true,     // authoritative source of truth
        enabled: false,   // legacy misleading field
      },
    ];
    api.get.mockReset();
    api.get.mockResolvedValueOnce(conflictRow);
    render(
      <MemoryRouter>
        <AiEmployeesList />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const el = screen.getByTestId("ai-emp-state-riley");
      expect(el.textContent).toMatch(/Active/i);
      expect(el.textContent).not.toMatch(/Disabled/i);
    });
  });
});
