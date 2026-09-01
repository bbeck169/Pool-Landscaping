/**
 * Phase I1 · Feb-2026 — ChargeTemplatePickerModal Jest tests.
 *
 * Covers:
 *   1. Renders templates from API on open.
 *   2. Search filters visible rows.
 *   3. Tap → apply calls applyChargeTemplate with tpl.id + jobId.
 *   4. Cancel closes without action.
 *   5. Load error surfaces error UI.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

const mockGetTemplates = jest.fn();
const mockApplyTemplate = jest.fn();

jest.mock("@/src/api/chargeTemplates", () => ({
  getChargeTemplates: (...a: any[]) => mockGetTemplates(...a),
  applyChargeTemplate: (...a: any[]) => mockApplyTemplate(...a),
}));

import ChargeTemplatePickerModal from
  "@/src/components/jobs/ChargeTemplatePickerModal";

const SAMPLE = {
  templates: [
    { id: "tpl-a", name: "Weekly service",
      category: "recurring",
      line_items: [{ description: "svc", subtotal: 50 }] },
    { id: "tpl-b", name: "Chemical add-on",
      category: "add-on",
      line_items: [{ description: "chlorine", subtotal: 15 }] },
    { id: "tpl-c", name: "Filter clean",
      category: "maintenance",
      line_items: [{ description: "filter", subtotal: 25 }] },
  ],
};


describe("ChargeTemplatePickerModal · I1 mobile parity", () => {
  beforeEach(() => {
    mockGetTemplates.mockReset();
    mockApplyTemplate.mockReset();
    jest.spyOn(Alert, "alert").mockImplementation(() => {});
  });

  it("renders the modal with templates fetched from the API",
     async () => {
    mockGetTemplates.mockResolvedValue(SAMPLE);
    const onClose = jest.fn();
    const onApplied = jest.fn();
    const { getByTestId } = render(
      <ChargeTemplatePickerModal
        visible={true} jobId="job-1"
        onClose={onClose} onApplied={onApplied} />,
    );
    await waitFor(() =>
      expect(getByTestId("charge-template-option-tpl-a")).toBeTruthy(),
    );
    expect(getByTestId("charge-template-option-tpl-b")).toBeTruthy();
    expect(getByTestId("charge-template-option-tpl-c")).toBeTruthy();
    expect(mockGetTemplates).toHaveBeenCalled();
  });

  it("search input filters visible templates by name", async () => {
    mockGetTemplates.mockResolvedValue(SAMPLE);
    const { getByTestId, queryByTestId } = render(
      <ChargeTemplatePickerModal
        visible={true} jobId="job-1"
        onClose={jest.fn()} onApplied={jest.fn()} />,
    );
    await waitFor(() =>
      expect(getByTestId("charge-template-option-tpl-a")).toBeTruthy(),
    );
    fireEvent.changeText(getByTestId("charge-template-search"),
                              "chemical");
    await waitFor(() => {
      expect(getByTestId("charge-template-option-tpl-b")).toBeTruthy();
      expect(queryByTestId("charge-template-option-tpl-a")).toBeNull();
    });
  });

  it("tapping a template calls applyChargeTemplate + onApplied",
     async () => {
    mockGetTemplates.mockResolvedValue(SAMPLE);
    mockApplyTemplate.mockResolvedValue({ added_count: 1 });
    const onApplied = jest.fn();
    const onClose = jest.fn();
    const { getByTestId } = render(
      <ChargeTemplatePickerModal
        visible={true} jobId="job-42"
        onClose={onClose} onApplied={onApplied} />,
    );
    await waitFor(() =>
      expect(getByTestId("charge-template-option-tpl-a")).toBeTruthy(),
    );
    fireEvent.press(getByTestId("charge-template-option-tpl-a"));
    await waitFor(() => expect(mockApplyTemplate).toHaveBeenCalledWith(
      "tpl-a", "job-42",
    ));
    expect(onApplied).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("Cancel closes without calling apply", async () => {
    mockGetTemplates.mockResolvedValue(SAMPLE);
    const onClose = jest.fn();
    const onApplied = jest.fn();
    const { getByTestId } = render(
      <ChargeTemplatePickerModal
        visible={true} jobId="job-1"
        onClose={onClose} onApplied={onApplied} />,
    );
    await waitFor(() =>
      expect(getByTestId("charge-template-cancel")).toBeTruthy(),
    );
    fireEvent.press(getByTestId("charge-template-cancel"));
    expect(onClose).toHaveBeenCalled();
    expect(mockApplyTemplate).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("shows error UI when the load call rejects", async () => {
    mockGetTemplates.mockRejectedValue(new Error("boom"));
    const { getByTestId } = render(
      <ChargeTemplatePickerModal
        visible={true} jobId="job-1"
        onClose={jest.fn()} onApplied={jest.fn()} />,
    );
    await waitFor(() =>
      expect(getByTestId("charge-template-error")).toBeTruthy(),
    );
  });
});
