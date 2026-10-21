/**
 * TD-82 b1 · bulk job picker sheets (status + absolute reschedule).
 */
import React from "react";
import { Platform } from "react-native";
import { render, fireEvent } from "@testing-library/react-native";

import JobStatusPickerSheet, { JOB_BULK_STATUS_OPTIONS } from "@/src/components/jobs/JobStatusPickerSheet";
import JobRescheduleSheet, { friendlyDate } from "@/src/components/jobs/JobRescheduleSheet";

jest.mock("@react-native-community/datetimepicker", () => () => null);

const disabled = (q: any, id: string) => q.getByTestId(id).props.accessibilityState?.disabled;

it("P1 · status sheet lists web STATUS_OPTIONS 1:1 and fires onSelect with the value", () => {
  expect(JOB_BULK_STATUS_OPTIONS.map((o) => o.value)).toEqual(["active", "pending", "scheduled", "in_progress", "completed", "canceled"]);
  const onSelect = jest.fn();
  const q = render(<JobStatusPickerSheet visible count={3} onSelect={onSelect} onClose={jest.fn()} />);
  expect(q.getByText("Change status · 3 jobs")).toBeTruthy();
  fireEvent.press(q.getByTestId("bulk-status-option-in_progress"));
  expect(onSelect).toHaveBeenCalledWith("in_progress");
});

describe("reschedule sheet (web text-date branch)", () => {
  const orig = Platform.OS;
  beforeAll(() => { (Platform as any).OS = "web"; });
  afterAll(() => { (Platform as any).OS = orig; });

  it("P2 · Apply disabled until a valid YYYY-MM-DD; invalid shows inline error", () => {
    const onApply = jest.fn();
    const q = render(<JobRescheduleSheet visible count={2} onApply={onApply} onClose={jest.fn()} />);
    expect(disabled(q, "bulk-reschedule-apply")).toBe(true);
    expect(q.getByTestId("bulk-reschedule-summary").props.children).toBe("Pick a date to move 2 jobs.");
    fireEvent.changeText(q.getByTestId("bulk-reschedule-datepicker"), "2026-13-40");
    expect(q.getByTestId("bulk-reschedule-invalid")).toBeTruthy();
    expect(disabled(q, "bulk-reschedule-apply")).toBe(true);
    fireEvent.press(q.getByTestId("bulk-reschedule-apply"));
    expect(onApply).not.toHaveBeenCalled();
  });

  it("P3 · valid date → summary line is the confirmation; Apply passes the ISO date", () => {
    const onApply = jest.fn();
    const q = render(<JobRescheduleSheet visible count={1} onApply={onApply} onClose={jest.fn()} />);
    fireEvent.changeText(q.getByTestId("bulk-reschedule-datepicker"), "2026-11-04");
    expect(q.getByTestId("bulk-reschedule-summary").props.children).toBe("Move 1 job to Wed, Nov 4, 2026");
    expect(disabled(q, "bulk-reschedule-apply")).toBe(false);
    fireEvent.press(q.getByTestId("bulk-reschedule-apply"));
    expect(onApply).toHaveBeenCalledWith("2026-11-04");
  });

  it("P4 · busy disables Apply; Cancel → onClose; reopen resets the date", () => {
    const onClose = jest.fn();
    const q = render(<JobRescheduleSheet visible count={2} busy onApply={jest.fn()} onClose={onClose} />);
    fireEvent.changeText(q.getByTestId("bulk-reschedule-datepicker"), "2026-11-04");
    expect(disabled(q, "bulk-reschedule-apply")).toBe(true);
    fireEvent.press(q.getByTestId("bulk-reschedule-cancel"));
    expect(onClose).toHaveBeenCalled();
    q.rerender(<JobRescheduleSheet visible={false} count={2} onApply={jest.fn()} onClose={onClose} />);
    q.rerender(<JobRescheduleSheet visible count={2} onApply={jest.fn()} onClose={onClose} />);
    expect(q.getByTestId("bulk-reschedule-datepicker").props.value).toBe("");
  });
});

it("P5 · friendlyDate is TZ-stable (noon anchor) and passes through invalid input", () => {
  expect(friendlyDate("2026-01-01")).toBe("Thu, Jan 1, 2026");
  expect(friendlyDate("nope")).toBe("nope");
});
