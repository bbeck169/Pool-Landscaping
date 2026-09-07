/**
 * Hotfix #4 · Feb-2026 — Trainings designation visibility (frontend guard).
 *
 * The API is the source of truth for visibility — it already applies
 * the "both designations = see EVERY training" rule. This test
 * confirms the ``TrainingList`` page has NO client-side department
 * filter that would silently drop trainings the API returned.
 *
 * Concretely: mount ``TrainingList`` with an API that returns one
 * module per department (pool / landscaping / both). Every module
 * must render as a card. If someone re-introduces a
 * ``modules.filter(m => m.department === user.department)`` line the
 * card count will drop and this test will red.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => {
  const state = { modulesResponse: [] };
  const api = {
    get: vi.fn(async (path) => {
      if (path.startsWith("/training/modules")) return state.modulesResponse;
      return null;
    }),
  };
  return { __esModule: true, default: api, api, __state: state };
});

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "technician" }),
}));

import TrainingList from "@/pages/training/TrainingList";
import * as apiMod from "@/api";

const _mod = (code, department) => ({
  code, title: `${code} title`, department,
  description: "", badge_label: "", disclaimer: "",
  is_system: false, lesson_count: 1, question_count: 1,
  progress: { lessons_completed: 0, lessons_total: 1, percent: 0 },
});

describe("TrainingList · Hotfix #4 designation visibility", () => {
  beforeEach(() => {
    apiMod.default.get.mockClear();
  });

  it("renders every module the API returns (no client-side dept filter)", async () => {
    apiMod.__state.modulesResponse = [
      _mod("m-pool", "pool"),
      _mod("m-land", "landscaping"),
      _mod("m-both", "both"),
    ];
    render(<MemoryRouter><TrainingList /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("training-module-card-m-pool")).toBeTruthy(),
    );
    expect(screen.getByTestId("training-module-card-m-land")).toBeTruthy();
    expect(screen.getByTestId("training-module-card-m-both")).toBeTruthy();
  });

  it("renders a single card if the API returns only one", async () => {
    apiMod.__state.modulesResponse = [_mod("m-only-land", "landscaping")];
    render(<MemoryRouter><TrainingList /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("training-module-card-m-only-land")).toBeTruthy(),
    );
    // Confirm no other cards leaked in.
    expect(screen.queryByTestId("training-module-card-m-pool")).toBeNull();
    expect(screen.queryByTestId("training-module-card-m-both")).toBeNull();
  });

  it("shows the empty state when API returns []", async () => {
    apiMod.__state.modulesResponse = [];
    render(<MemoryRouter><TrainingList /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("training-list-empty")).toBeTruthy(),
    );
  });
});
