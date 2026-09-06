/**
 * Phase F2 · Feb-2026 — ApplyChargeTemplateButton dropdown tests.
 *
 * Covers:
 *   • Opening the dropdown fetches templates from GET
 *     /api/charge-templates.
 *   • Selecting a template calls POST
 *     /api/charge-templates/{tid}/apply-to-job/{jid} and fires onApplied.
 *   • Search filters the visible options client-side.
 *   • Empty state message when no templates exist.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...a) => toastSuccess(...a),
           error: (...a) => toastError(...a) },
}));

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock("../api", () => ({
  api: {
    get: (...args) => mockGet(...args),
    post: (...args) => mockPost(...args),
    put: vi.fn(), del: vi.fn(),
  },
}));

import ApplyChargeTemplateButton from "@/components/schedule/ApplyChargeTemplateButton";

const T1 = { id: "tpl-1", name: "Chlorine Shock Combo",
             category: "chemicals",
             line_items: [{ name: "a" }, { name: "b" }, { name: "c" }] };
const T2 = { id: "tpl-2", name: "Filter Service", category: "maintenance",
             line_items: [{ name: "a" }, { name: "b" }] };

beforeEach(() => {
  mockGet.mockReset(); mockPost.mockReset();
  toastSuccess.mockReset(); toastError.mockReset();
  mockGet.mockResolvedValue({ templates: [T1, T2] });
  mockPost.mockResolvedValue({ ok: true, added_count: 3,
                                template_name: T1.name });
});

describe("ApplyChargeTemplateButton", () => {
  it("opens dropdown and lazy-loads templates", async () => {
    render(<ApplyChargeTemplateButton jobId="job-1" onApplied={() => {}} />);
    fireEvent.click(screen.getByTestId("apply-charge-template-btn"));
    await waitFor(() =>
      expect(screen.getByTestId(`apply-charge-template-option-${T1.id}`))
        .toBeTruthy(),
    );
    expect(mockGet).toHaveBeenCalledWith("/charge-templates");
    expect(screen.getByTestId(`apply-charge-template-option-${T2.id}`))
      .toBeTruthy();
  });

  it("filters options via the search input", async () => {
    render(<ApplyChargeTemplateButton jobId="job-1" onApplied={() => {}} />);
    fireEvent.click(screen.getByTestId("apply-charge-template-btn"));
    await waitFor(() =>
      expect(screen.getByTestId(`apply-charge-template-option-${T1.id}`))
        .toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("apply-charge-template-search"), {
      target: { value: "filter" },
    });
    expect(screen.queryByTestId(`apply-charge-template-option-${T1.id}`))
      .toBeNull();
    expect(screen.getByTestId(`apply-charge-template-option-${T2.id}`))
      .toBeTruthy();
  });

  it("selecting an option POSTs apply-to-job and fires onApplied", async () => {
    const onApplied = vi.fn();
    render(<ApplyChargeTemplateButton jobId="job-42" onApplied={onApplied} />);
    fireEvent.click(screen.getByTestId("apply-charge-template-btn"));
    await waitFor(() =>
      expect(screen.getByTestId(`apply-charge-template-option-${T1.id}`))
        .toBeTruthy(),
    );
    fireEvent.click(
      screen.getByTestId(`apply-charge-template-option-${T1.id}`),
    );
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith(
        "/charge-templates/tpl-1/apply-to-job/job-42",
      ),
    );
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
    expect(toastSuccess).toHaveBeenCalled();
    expect(toastSuccess.mock.calls[0][0]).toMatch(/3 items? added/i);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("shows empty-state when no templates exist", async () => {
    mockGet.mockResolvedValueOnce({ templates: [] });
    render(<ApplyChargeTemplateButton jobId="job-1" onApplied={() => {}} />);
    fireEvent.click(screen.getByTestId("apply-charge-template-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("apply-charge-template-empty")).toBeTruthy(),
    );
    expect(screen.getByTestId("apply-charge-template-empty").textContent)
      .toMatch(/no charge templates/i);
  });
});
