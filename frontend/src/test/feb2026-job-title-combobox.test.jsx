/**
 * Feb 2026 · JobTitleCombobox — behavioural contract.
 *
 * Coverage:
 *   1. Renders suggestions returned by ``api.get('/job-titles?q=…')``.
 *   2. Debounces the fetch (~250ms) — typing a full word fires one
 *      request, not one per keystroke.
 *   3. Clicking a suggestion fills the input via ``onChange`` and
 *      closes the panel.
 *   4. Free typing preserved when the user ignores suggestions.
 *   5. ArrowDown + Enter picks the top suggestion.
 *   6. Silent-degrade — API failure produces no console error and
 *      leaves the input as a plain text control.
 *   7. Empty-state hint renders when the query returns no rows
 *      (auto-add-on-save reassurance).
 */
import React, { useState } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
  },
}));


import JobTitleCombobox from "@/components/JobTitleCombobox";


function ControlledHost({ initial = "" }) {
  const [v, setV] = useState(initial);
  return (
    <div>
      <JobTitleCombobox value={v} onChange={setV} testid="jtc" />
      <span data-testid="host-value">{v}</span>
    </div>
  );
}


beforeEach(() => {
  mockGet.mockClear();
  // Default: return 3 suggestions.
  mockGet.mockResolvedValue([
    { id: "t1", title: "Weekly Pool Service",  usage_count: 12 },
    { id: "t2", title: "Weekly Pool Cleaning", usage_count: 8  },
    { id: "t3", title: "Monthly Landscaping",  usage_count: 3  },
  ]);
});


afterEach(() => vi.useRealTimers());


describe("JobTitleCombobox", () => {
  it("renders suggestions on focus", async () => {
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    await waitFor(() =>
      expect(screen.getByTestId("jtc-option-0")).toBeTruthy());
    expect(screen.getByTestId("jtc-option-0").textContent)
      .toMatch(/Weekly Pool Service/);
    expect(screen.getByTestId("jtc-option-2").textContent)
      .toMatch(/Monthly Landscaping/);
  });

  it("debounces the fetch when typing quickly", async () => {
    vi.useFakeTimers();
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    // Flush initial focus fetch.
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });
    mockGet.mockClear();
    // Type 5 characters in rapid succession — only ONE debounced
    // fetch should fire after the trailing delay.
    for (const ch of "Weekl") {
      fireEvent.change(screen.getByTestId("jtc-input"),
        { target: { value: ch } });
    }
    // Halfway through the debounce window — no fetch yet.
    await act(async () => {
      vi.advanceTimersByTime(100);
      await Promise.resolve();
    });
    expect(mockGet).not.toHaveBeenCalled();
    // Cross the debounce threshold — exactly one fetch.
    await act(async () => {
      vi.advanceTimersByTime(300);
      await Promise.resolve();
    });
    expect(mockGet.mock.calls.length).toBe(1);
    // Path shape: contains /job-titles?q=
    expect(mockGet.mock.calls[0][0]).toMatch(/^\/job-titles\?q=/);
  });

  it("clicking a suggestion fills the input and closes the panel", async () => {
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    await waitFor(() =>
      expect(screen.getByTestId("jtc-option-1")).toBeTruthy());
    // Use mousedown — the component intentionally binds mousedown
    // (not click) to sidestep the click-outside handler.
    fireEvent.mouseDown(screen.getByTestId("jtc-option-1"));
    // Host state must reflect the picked title.
    expect(screen.getByTestId("host-value").textContent)
      .toBe("Weekly Pool Cleaning");
    // Panel is closed (option-1 no longer in the DOM).
    expect(screen.queryByTestId("jtc-option-1")).toBeNull();
  });

  it("preserves free-typed text when Enter is pressed with no suggestion highlighted", async () => {
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    await waitFor(() =>
      expect(screen.getByTestId("jtc-option-0")).toBeTruthy());
    // Type a brand-new title.
    fireEvent.change(screen.getByTestId("jtc-input"),
      { target: { value: "Emergency Fill-in Visit" } });
    // Press Enter without arrow-navigation → panel closes, host
    // value stays exactly what the user typed.
    fireEvent.keyDown(screen.getByTestId("jtc-input"),
      { key: "Enter", code: "Enter" });
    expect(screen.getByTestId("host-value").textContent)
      .toBe("Emergency Fill-in Visit");
  });

  it("ArrowDown + Enter picks the top suggestion", async () => {
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    await waitFor(() =>
      expect(screen.getByTestId("jtc-option-0")).toBeTruthy());
    fireEvent.keyDown(screen.getByTestId("jtc-input"),
      { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByTestId("jtc-input"),
      { key: "Enter" });
    expect(screen.getByTestId("host-value").textContent)
      .toBe("Weekly Pool Service");
  });

  it("silently degrades when /job-titles fetch fails", async () => {
    mockGet.mockRejectedValue(new Error("offline"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ControlledHost initial="" />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    // No option renders + no console error blast.
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(screen.queryByTestId("jtc-option-0")).toBeNull();
    // Input still writes back to host state.
    fireEvent.change(screen.getByTestId("jtc-input"),
      { target: { value: "New Title" } });
    expect(screen.getByTestId("host-value").textContent).toBe("New Title");
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });

  it("shows the empty-state hint when the query returns no rows", async () => {
    mockGet.mockResolvedValue([]);
    render(<ControlledHost initial="Xylo" />);
    fireEvent.focus(screen.getByTestId("jtc-input"));
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    // Empty-state hint carries the "will be added when you save"
    // reassurance copy — matches the auto-learn spec.
    await waitFor(() =>
      expect(screen.getByTestId("jtc-empty")).toBeTruthy());
    expect(screen.getByTestId("jtc-empty").textContent)
      .toMatch(/added when you save/i);
  });
});
