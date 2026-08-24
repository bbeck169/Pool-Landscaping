/**
 * Feb-2026 · Multi-category tech assignment — mobile /team inline
 * department picker.
 *
 * Ships alongside ``frontend/src/test/admin-users-inline-department.test.jsx``
 * for parity.  Verifies:
 *   1. Non-admin viewers (technician role) don't see the "Set
 *      department" action even for tech-role rows.
 *   2. Admin sees the action + current-department subtitle.
 *   3. Picking "Both" fires PUT with the right payload and
 *      optimistically paints the new dept chip.
 *   4. Picking "Unassigned" PUTs ``department: null``.
 *   5. API failure reverts the chip.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
}));

const mockGet = jest.fn();
const mockPut = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    put: (...a: any[]) => mockPut(...a),
    post: (...a: any[]) => mockPost(...a),
    patch: jest.fn(),
    del: jest.fn(),
  },
}));

// Auth — flipped per test.
let mockRole: string = "admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "current-admin", role: mockRole, name: "Ada Admin" },
  }),
}));

// Trim theme + widgets to keep the test focused.
jest.mock("@/src/components/ui", () => {
  const React = require("react");
  const RN = require("react-native");
  return {
    Loading: (p: any) => React.createElement(RN.Text, p, "loading"),
    EmptyState: (p: any) => React.createElement(RN.Text, p, "empty"),
    PrimaryButton: (p: any) => React.createElement(
      RN.Pressable, { onPress: p.onPress, testID: p.testID },
      React.createElement(RN.Text, {}, p.title),
    ),
  };
});
jest.mock("@/src/components/widgets", () => ({
  Header: () => null,
}));
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({}),
  BulkCheckbox: () => null,
  BulkActionBar: () => null,
}));

// Silence RN Alerts so a failing test surfaces the raw expect() error.
jest.spyOn(Alert, "alert").mockImplementation(() => {});

import Team from "@/app/team";

const ROWS = [
  { id: "u-pool",  name: "Mike Pool",   email: "mike@a.com",
    role: "pool_tech",      department: "pool_tech" },
  { id: "u-both",  name: "Alex Cross",  email: "alex@a.com",
    role: "technician",     department: null },
  { id: "u-admin", name: "Ada Admin",   email: "ada@a.com",
    role: "admin",          department: "both" },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "admin";
  mockGet.mockResolvedValue(ROWS);
});

describe("mobile /team · inline department picker", () => {
  it("admin sees 'Set department' entry for tech rows", async () => {
    const { getByTestId, findByTestId, queryByText } = render(<Team />);
    // Open the action sheet for the pool tech row.
    const kebab = await findByTestId("team-row-kebab-u-pool");
    fireEvent.press(kebab);
    await waitFor(() =>
      expect(getByTestId("team-row-edit-dept-btn-u-pool")).toBeTruthy(),
    );
    // The action sheet also surfaces the current department text.
    expect(queryByText("Current: Pool tech")).toBeTruthy();
  });

  it("technician viewer sees no 'Set department' entry at all", async () => {
    mockRole = "technician";
    const { queryByTestId } = render(<Team />);
    // Techs don't even see the kebab (existing behavior) — assert
    // the dept action is unreachable.
    await waitFor(() =>
      expect(queryByTestId("team-row-kebab-u-pool")).toBeNull(),
    );
  });

  it("picking 'Both' PUTs /admin/users/{id}/department with 'both'", async () => {
    mockPut.mockResolvedValueOnce({ ok: true });
    const { getByTestId, findByTestId } = render(<Team />);
    fireEvent.press(await findByTestId("team-row-kebab-u-pool"));
    fireEvent.press(getByTestId("team-row-edit-dept-btn-u-pool"));
    // Picker sheet is open.  Choose "Both".
    fireEvent.press(getByTestId("team-dept-picker-option-both-u-pool"));

    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/admin/users/u-pool/department",
        { department: "both" },
      ),
    );
    // Chip on the row now reads "Both" (optimistic).
    await waitFor(() =>
      expect(getByTestId("team-row-dept-chip-u-pool").props.children[1].props.children)
        .toBe("Both"),
    );
  });

  it("picking 'Unassigned' PUTs department: null", async () => {
    mockPut.mockResolvedValueOnce({ ok: true });
    const { getByTestId, findByTestId } = render(<Team />);
    fireEvent.press(await findByTestId("team-row-kebab-u-pool"));
    fireEvent.press(getByTestId("team-row-edit-dept-btn-u-pool"));
    fireEvent.press(getByTestId("team-dept-picker-option-unassigned-u-pool"));

    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/admin/users/u-pool/department",
        { department: null },
      ),
    );
  });

  it("reverts the chip when PUT fails", async () => {
    mockPut.mockRejectedValueOnce(new Error("boom"));
    const { getByTestId, findByTestId } = render(<Team />);
    fireEvent.press(await findByTestId("team-row-kebab-u-pool"));
    fireEvent.press(getByTestId("team-row-edit-dept-btn-u-pool"));
    fireEvent.press(getByTestId("team-dept-picker-option-both-u-pool"));

    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    // Chip reverts to the original "Pool tech" label.
    await waitFor(() =>
      expect(getByTestId("team-row-dept-chip-u-pool").props.children[1].props.children)
        .toBe("Pool tech"),
    );
    expect(Alert.alert).toHaveBeenCalledWith(
      "Department update failed",
      expect.stringMatching(/boom/),
    );
  });
});
