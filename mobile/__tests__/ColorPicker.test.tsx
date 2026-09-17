/**
 * ColorPicker — unit tests.
 *
 * Tests: preset row renders, recents hydrate, freeform #FFFFFF blocks Apply,
 * valid dark hex enables Apply, save flow calls onChange + recent-colors POST.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

/* ── Mocks ──────────────────────────────────────────────────────────── */

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPatch = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
    patch: (...args: any[]) => mockPatch(...args),
  },
}));

jest.mock("@react-native-community/slider", () => {
  const { View } = require("react-native");
  return {
    __esModule: true,
    default: (props: any) => <View testID={props.testID} />,
  };
});

jest.spyOn(Alert, "alert").mockImplementation(() => {});

import ColorPicker from "@/src/components/ui/ColorPicker";

/* ── Helpers ────────────────────────────────────────────────────────── */
const MOCK_PALETTE = {
  palette: [
    { name: "Red", hex: "#EF4444" },
    { name: "Blue", hex: "#3B82F6" },
    { name: "Green", hex: "#22C55E" },
  ],
};

const MOCK_RECENTS = {
  recent_colors: ["#6366F1", "#EC4899"],
};

beforeEach(() => {
  jest.clearAllMocks();
  mockGet.mockImplementation((url: string) => {
    if (url === "/tech-colors/palette") return Promise.resolve(MOCK_PALETTE);
    if (url === "/users/me/recent-colors") return Promise.resolve(MOCK_RECENTS);
    return Promise.resolve(null);
  });
  mockPost.mockResolvedValue({ recent_colors: [] });
});

/* ── Tests ───────────────────────────────────────────────────────────── */

describe("ColorPicker", () => {
  it("renders preset row from mock palette fetch", async () => {
    const { getByTestId } = render(
      <ColorPicker testidPrefix="cp" />
    );

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith("/tech-colors/palette");
    });

    await waitFor(() => {
      expect(getByTestId("cp-preset-#EF4444")).toBeTruthy();
      expect(getByTestId("cp-preset-#3B82F6")).toBeTruthy();
      expect(getByTestId("cp-preset-#22C55E")).toBeTruthy();
    });
  });

  it("renders recently-used row from mock GET", async () => {
    const { getByTestId } = render(
      <ColorPicker testidPrefix="cp" />
    );

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith("/users/me/recent-colors");
    });
    await waitFor(() => {
      expect(getByTestId("cp-recent-row")).toBeTruthy();
      expect(getByTestId("cp-recent-#6366F1")).toBeTruthy();
      expect(getByTestId("cp-recent-#EC4899")).toBeTruthy();
    });
  });

  it("freeform #FFFFFF disables Apply + shows warning", async () => {
    const { getByTestId } = render(
      <ColorPicker testidPrefix="cp" />
    );

    await act(async () => {
      fireEvent.changeText(getByTestId("cp-hex-input"), "#FFFFFF");
    });

    await waitFor(() => {
      expect(getByTestId("cp-contrast-warning")).toBeTruthy();
    });

    // Apply button should be disabled
    const applyBtn = getByTestId("cp-commit");
    expect(applyBtn.props.accessibilityState?.disabled ?? applyBtn.props.disabled).toBeTruthy();
  });

  it("valid dark hex enables Apply and clears warning", async () => {
    const { getByTestId, queryByTestId } = render(
      <ColorPicker testidPrefix="cp" />
    );

    await act(async () => {
      fireEvent.changeText(getByTestId("cp-hex-input"), "#0F172A");
    });

    await waitFor(() => {
      expect(queryByTestId("cp-contrast-warning")).toBeNull();
    });

    const applyBtn = getByTestId("cp-commit");
    // Should not be disabled (commitDisabled = false when draft differs from value)
    // Note: applyBtn may be enabled since draft (#0F172A) != value ("")
    expect(
      applyBtn.props.accessibilityState?.disabled ?? applyBtn.props.disabled
    ).toBeFalsy();
  });

  it("save flow calls onChange + posts to recent-colors", async () => {
    const handleChange = jest.fn().mockResolvedValue(undefined);
    mockPost.mockResolvedValue({ recent_colors: ["#0F172A"] });

    const { getByTestId } = render(
      <ColorPicker testidPrefix="cp" onChange={handleChange} />
    );

    // Type a valid dark hex
    await act(async () => {
      fireEvent.changeText(getByTestId("cp-hex-input"), "#0F172A");
    });

    // Press Apply
    await act(async () => {
      fireEvent.press(getByTestId("cp-commit"));
    });

    await waitFor(() => {
      expect(handleChange).toHaveBeenCalledWith("#0F172A");
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/users/me/recent-colors",
        { color: "#0F172A" },
      );
    });
  });

  it("preset tap fires onChange with preset hex", async () => {
    const handleChange = jest.fn().mockResolvedValue(undefined);
    mockPost.mockResolvedValue({ recent_colors: [] });

    const { getByTestId } = render(
      <ColorPicker testidPrefix="cp" onChange={handleChange} />
    );

    // Wait for palette to load
    await waitFor(() => {
      expect(getByTestId("cp-preset-#EF4444")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("cp-preset-#EF4444"));
    });

    await waitFor(() => {
      expect(handleChange).toHaveBeenCalledWith("#EF4444");
    });
  });

  it("hides recently-used row when empty", async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === "/tech-colors/palette") return Promise.resolve(MOCK_PALETTE);
      if (url === "/users/me/recent-colors") return Promise.resolve({ recent_colors: [] });
      return Promise.resolve(null);
    });

    const { queryByTestId } = render(
      <ColorPicker testidPrefix="cp" />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(queryByTestId("cp-recent-row")).toBeNull();
  });
});
