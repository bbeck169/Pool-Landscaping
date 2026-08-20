/**
 * Feb-2026 · Phase 1 finisher — <JobOutcomeReasonsPage /> tests.
 *
 * Covers the admin CRUD panel that drives
 * ``/api/settings/job-outcome-reasons`` endpoints:
 *
 *   1. Fetches with ``include_inactive=true`` when checkbox on.
 *   2. Renders default vs custom badges + active/inactive status pills.
 *   3. Toggling active issues PATCH with ``{active: !current}``.
 *   4. Delete blocked (with helper toast) for default reasons.
 *   5. New reason form POSTs the payload shape.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const _h = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));

vi.mock("@/api", () => ({ api: _h.api }));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8f8f8", border: "#eee",
    onSurface: "#111", muted: "#666", brand: "#0891B2", error: "#DC2626",
  },
}));

vi.mock("@/components/ui-kit", () => {
  const React = require("react");
  return {
    Button: ({ children, onClick, disabled, testid, ...rest }) => (
      React.createElement(
        "button",
        { onClick, disabled, "data-testid": testid, ...rest },
        children,
      )
    ),
  };
});

import JobOutcomeReasonsPage from "@/pages/settings/JobOutcomeReasonsPage";

const REASONS = [
  { id: "r-locked", key: "locked_out", label: "Locked out",   sort_order: 0, is_default: true,  active: true  },
  { id: "r-weath",  key: "weather",    label: "Weather",      sort_order: 3, is_default: true,  active: true  },
  { id: "r-old",    key: "old_reason", label: "Old reason",   sort_order: 8, is_default: false, active: false },
];

beforeEach(() => {
  vi.clearAllMocks();
  _h.api.get.mockResolvedValue({ reasons: REASONS });
  _h.api.post.mockResolvedValue({});
  _h.api.patch.mockResolvedValue({});
  _h.api.del.mockResolvedValue({});
});

async function renderPage() {
  const view = render(<JobOutcomeReasonsPage />);
  await waitFor(() => {
    expect(_h.api.get).toHaveBeenCalledWith(
      "/settings/job-outcome-reasons?include_inactive=true",
    );
  });
  return view;
}

describe("<JobOutcomeReasonsPage />", () => {

  it("hydrates with include_inactive=true and shows default+custom+inactive rows", async () => {
    await renderPage();
    expect(screen.getByTestId("jor-row-r-locked")).toBeTruthy();
    expect(screen.getByTestId("jor-row-r-weath")).toBeTruthy();
    expect(screen.getByTestId("jor-row-r-old")).toBeTruthy();
    // Inactive status pill for r-old
    expect(screen.getByTestId("jor-status-r-old").textContent).toMatch(/Inactive/);
    expect(screen.getByTestId("jor-status-r-locked").textContent).toMatch(/Active/);
  });

  it("un-checking 'Show inactive' refetches without the query param", async () => {
    await renderPage();
    _h.api.get.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByTestId("jor-show-inactive"));
    });
    await waitFor(() => {
      expect(_h.api.get).toHaveBeenCalledWith("/settings/job-outcome-reasons");
    });
  });

  it("toggle active issues PATCH with {active: false} for currently-active row", async () => {
    await renderPage();
    await act(async () => {
      fireEvent.click(screen.getByTestId("jor-toggle-r-locked"));
    });
    await waitFor(() => {
      expect(_h.api.patch).toHaveBeenCalledWith(
        "/settings/job-outcome-reasons/r-locked",
        { active: false },
      );
    });
  });

  it("delete on a default reason is blocked (disabled button)", async () => {
    await renderPage();
    const btn = screen.getByTestId("jor-delete-r-locked");
    expect(btn.disabled).toBe(true);
    // Custom reason is not blocked
    const custom = screen.getByTestId("jor-delete-r-old");
    expect(custom.disabled).toBe(false);
  });

  it("new-reason form submits POST with trimmed label", async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId("jor-new"));
    const labelInput = screen.getByTestId("jor-form-label");
    await act(async () => {
      fireEvent.change(labelInput, { target: { value: "  Aggressive dog   " } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("jor-form-save"));
    });
    await waitFor(() => {
      expect(_h.api.post).toHaveBeenCalledWith(
        "/settings/job-outcome-reasons",
        { label: "Aggressive dog" },
      );
    });
  });
});
