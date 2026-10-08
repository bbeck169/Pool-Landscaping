/**
 * Templates Library — Phase 3 (Mobile) · field helpers + table + renderer.
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

const mockShowConfirm = jest.fn();
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: (o: any) => mockShowConfirm(o) }));
jest.mock("@/src/components/templates/SignaturePadModal", () => () => null);

import { parseNumberInput, numberRangeError, makeSignatureStamp, todayISODate } from "@/src/components/templates/fieldUtils";
import TemplateTableField from "@/src/components/templates/TemplateTableField";
import TemplateFieldRenderer from "@/src/components/templates/TemplateFieldRenderer";

beforeEach(() => mockShowConfirm.mockReset());

describe("fieldUtils", () => {
  it("parseNumberInput keeps partial decimals as strings and commits numbers", () => {
    expect(parseNumberInput("")).toBe("");
    expect(parseNumberInput("7")).toBe(7);
    expect(parseNumberInput("7.")).toBe("7.");
    expect(parseNumberInput("7.5")).toBe(7.5);
    expect(parseNumberInput("7.50")).toBe("7.50");
    expect(parseNumberInput("-")).toBe("-");
    expect(parseNumberInput("3,2")).toBe(3.2);
    expect(parseNumberInput("12abc")).toBe(12);
  });

  it("numberRangeError enforces min/max", () => {
    const f = { min: 0, max: 10 };
    expect(numberRangeError(f, "")).toBeNull();
    expect(numberRangeError(f, 5)).toBeNull();
    expect(numberRangeError(f, 0)).toBeNull();
    expect(numberRangeError(f, 10)).toBeNull();
    expect(numberRangeError(f, -1)).toBe("Must be ≥ 0");
    expect(numberRangeError(f, 11)).toBe("Must be ≤ 10");
    expect(numberRangeError({}, 9999)).toBeNull();
  });

  it("makeSignatureStamp produces `${name} • ${ISO}` and backend-compatible keys", () => {
    const d = new Date("2026-10-08T12:34:56.000Z");
    expect(makeSignatureStamp("Mike Tech", d)).toEqual({
      signer_name: "Mike Tech",
      signed_at: "2026-10-08T12:34:56.000Z",
      stamp: "Mike Tech • 2026-10-08T12:34:56.000Z",
    });
    expect(makeSignatureStamp("  ", d).signer_name).toBe("Unknown user");
  });

  it("todayISODate formats YYYY-MM-DD", () => {
    expect(todayISODate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("TemplateTableField (vertical stacked rows)", () => {
  const field = {
    key: "readings",
    columns: [
      { key: "ph", label: "pH", type: "number" },
      { key: "note", label: "Note", type: "text" },
      { key: "day", label: "Day", type: "date" },
      { key: "ok", label: "OK?", type: "checkbox" },
    ],
  };

  it("renders a labeled input per column for every row", () => {
    const { getByTestId, getAllByText } = render(
      <TemplateTableField field={field} value={[{ ph: 7.4 }, { note: "x" }]} onChange={jest.fn()} />,
    );
    expect(getByTestId("template-table-readings-row-0")).toBeTruthy();
    expect(getByTestId("template-table-readings-row-1")).toBeTruthy();
    expect(getAllByText("pH")).toHaveLength(2);
    expect(getAllByText("Note")).toHaveLength(2);
    expect(getByTestId("template-table-readings-cell-0-ph").props.value).toBe("7.4");
    expect(getByTestId("template-table-readings-cell-0-day").props.placeholder).toBe("YYYY-MM-DD");
  });

  it("adds a row, edits a numeric cell, deletes a row", () => {
    const onChange = jest.fn();
    const { getByTestId } = render(<TemplateTableField field={field} value={[{ ph: 7 }, { ph: 8 }]} onChange={onChange} />);
    fireEvent.press(getByTestId("template-table-readings-add"));
    expect(onChange).toHaveBeenLastCalledWith([{ ph: 7 }, { ph: 8 }, {}]);
    fireEvent.changeText(getByTestId("template-table-readings-cell-1-ph"), "7.");
    expect(onChange).toHaveBeenLastCalledWith([{ ph: 7 }, { ph: "7." }]);
    fireEvent.press(getByTestId("template-table-readings-del-0"));
    expect(onChange).toHaveBeenLastCalledWith([{ ph: 8 }]);
  });

  it("long-press asks for confirmation then deletes", () => {
    const onChange = jest.fn();
    const { getByTestId } = render(<TemplateTableField field={field} value={[{ ph: 7 }, { ph: 8 }]} onChange={onChange} />);
    fireEvent(getByTestId("template-table-readings-row-1"), "longPress");
    expect(mockShowConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: "Delete row 2?" }));
    mockShowConfirm.mock.calls[0][0].onConfirm();
    expect(onChange).toHaveBeenLastCalledWith([{ ph: 7 }]);
  });

  it("disabled: hides add/delete and ignores long-press", () => {
    const { queryByTestId, getByTestId } = render(<TemplateTableField field={field} value={[{ ph: 7 }]} onChange={jest.fn()} disabled />);
    expect(queryByTestId("template-table-readings-add")).toBeNull();
    expect(queryByTestId("template-table-readings-del-0")).toBeNull();
    fireEvent(getByTestId("template-table-readings-row-0"), "longPress");
    expect(mockShowConfirm).not.toHaveBeenCalled();
  });

  it("shows empty state with no rows", () => {
    const { getByTestId } = render(<TemplateTableField field={field} value={undefined} onChange={jest.fn()} />);
    expect(getByTestId("template-table-readings-empty")).toBeTruthy();
  });
});

describe("TemplateFieldRenderer", () => {
  it("signature Sign stamps current user name + ISO time", () => {
    const onChange = jest.fn();
    const { getByTestId } = render(
      <TemplateFieldRenderer field={{ type: "signature", key: "sig", label: "Tech signature" }} value={null} onChange={onChange} currentUserName="Mike Tech" />,
    );
    fireEvent.press(getByTestId("template-field-sig-sign"));
    const v = onChange.mock.calls[0][0];
    expect(v.signer_name).toBe("Mike Tech");
    expect(v.stamp).toBe(`Mike Tech • ${v.signed_at}`);
    expect(new Date(v.signed_at).toISOString()).toBe(v.signed_at);
  });

  it("renders an existing stamp as `name • ISO`", () => {
    const { getByTestId } = render(
      <TemplateFieldRenderer field={{ type: "signature", key: "sig", label: "S" }} value={{ signer_name: "Ann", signed_at: "2026-10-08T00:00:00.000Z" }} onChange={jest.fn()} />,
    );
    expect(getByTestId("template-field-sig-stamp").props.children).toBe("Ann • 2026-10-08T00:00:00.000Z");
  });

  it("number field shows min/max error when out of range", () => {
    const { getByTestId, queryByTestId, rerender } = render(
      <TemplateFieldRenderer field={{ type: "number", key: "ph", label: "pH", min: 6, max: 9 }} value={10} onChange={jest.fn()} />,
    );
    expect(getByTestId("template-field-ph-range-error").props.children).toBe("Must be ≤ 9");
    rerender(<TemplateFieldRenderer field={{ type: "number", key: "ph", label: "pH", min: 6, max: 9 }} value={7.2} onChange={jest.fn()} />);
    expect(queryByTestId("template-field-ph-range-error")).toBeNull();
  });

  it("date field Today button fills YYYY-MM-DD", () => {
    const onChange = jest.fn();
    const { getByTestId } = render(<TemplateFieldRenderer field={{ type: "date", key: "d", label: "Date" }} value="" onChange={onChange} />);
    fireEvent.press(getByTestId("template-field-d-today"));
    expect(onChange.mock.calls[0][0]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("select chips set value; disabled blocks inputs", () => {
    const onChange = jest.fn();
    const { getByTestId } = render(<TemplateFieldRenderer field={{ type: "select", key: "s", label: "S", options: ["A", "B"] }} value="" onChange={onChange} />);
    fireEvent.press(getByTestId("template-field-s-opt-B"));
    expect(onChange).toHaveBeenCalledWith("B");
    const r2 = render(<TemplateFieldRenderer field={{ type: "text", key: "t", label: "T" }} value="x" onChange={jest.fn()} disabled />);
    expect(r2.getByTestId("template-field-t-input").props.editable).toBe(false);
  });
});
