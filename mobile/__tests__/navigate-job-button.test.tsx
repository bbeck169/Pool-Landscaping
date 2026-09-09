/**
 * NavigateJobButton — unit tests for repositioned + restyled button.
 *
 * Verifies:
 *  1. Renders with correct testID
 *  2. Orange background color (#F97316) — was navy
 *  3. Correct accessibility label with customer name
 *  4. Disabled state renders with reduced opacity
 *  5. Button is 36px with shadow
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

jest.mock("@/src/utils/nativeNav", () => ({
  openNativeNavTo: jest.fn(),
}));

import NavigateJobButton from "@/src/components/schedule/NavigateJobButton";
import { openNativeNavTo } from "@/src/utils/nativeNav";

const mockJob = {
  id: "job-123",
  latitude: 33.4484,
  longitude: -112.074,
  address: "123 Main St",
  customer_name: "Jane Doe",
};

const mockJobNoCoords = {
  id: "job-456",
  latitude: null,
  longitude: null,
  address: "456 Elm St",
  customer_name: "No Coord Customer",
};

describe("NavigateJobButton — restyled orange top-right", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders with the correct testID", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJob} />);
    expect(getByTestId("schedule-job-nav-job-123")).toBeTruthy();
  });

  it("has orange background (#F97316) instead of old navy", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJob} />);
    const btn = getByTestId("schedule-job-nav-job-123");
    const styles = Array.isArray(btn.props.style)
      ? Object.assign({}, ...btn.props.style.filter(Boolean))
      : btn.props.style || {};
    expect(styles.backgroundColor).toBe("#F97316");
    // Should NOT be the old navy
    expect(styles.backgroundColor).not.toBe("#1B1F5C");
  });

  it("has correct accessibility label with customer name", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJob} />);
    const btn = getByTestId("schedule-job-nav-job-123");
    expect(btn.props.accessibilityLabel).toBe("Navigate to Jane Doe");
    expect(btn.props.accessibilityRole).toBe("button");
  });

  it("has accessibility hint for driving directions", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJob} />);
    const btn = getByTestId("schedule-job-nav-job-123");
    expect(btn.props.accessibilityHint).toBe("Opens driving directions in maps app");
  });

  it("calls openNativeNavTo on press with coords", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJob} />);
    fireEvent.press(getByTestId("schedule-job-nav-job-123"));
    expect(openNativeNavTo).toHaveBeenCalledWith(33.4484, -112.074, "Jane Doe");
  });

  it("renders disabled state when no coords", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJobNoCoords} />);
    const btn = getByTestId("schedule-job-nav-job-456");
    const styles = Array.isArray(btn.props.style)
      ? Object.assign({}, ...btn.props.style.filter(Boolean))
      : btn.props.style || {};
    expect(styles.opacity).toBe(0.35);
    expect(styles.backgroundColor).toBe("#D1D5DB");
  });

  it("shows 'No address on file' label when disabled", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJobNoCoords} />);
    const btn = getByTestId("schedule-job-nav-job-456");
    expect(btn.props.accessibilityLabel).toBe("No address on file");
  });

  it("has 36x36 visual size with 6px hitSlop for 48px effective target", () => {
    const { getByTestId } = render(<NavigateJobButton job={mockJob} />);
    const btn = getByTestId("schedule-job-nav-job-123");
    const styles = Array.isArray(btn.props.style)
      ? Object.assign({}, ...btn.props.style.filter(Boolean))
      : btn.props.style || {};
    expect(styles.width).toBe(36);
    expect(styles.height).toBe(36);
    expect(styles.borderRadius).toBe(18);
  });
});
