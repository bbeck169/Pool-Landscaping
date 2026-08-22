/**
 * Feb-2026 · P29b — Mobile MuteControlSheet parity tests.
 *
 * Mirrors the web ``mute-control`` interaction contract for mobile:
 *   1. Renders "Mark Muted" pill on a non-muted customer for admin.
 *   2. Renders nothing when gated (canMute=false && customer not muted).
 *   3. Opens the bottom sheet on press and lazily fetches
 *      ``GET /settings/muted-reasons``.
 *   4. Selecting a seeded reason + confirming issues
 *      ``PATCH /customers/{id}/mute`` with the label snapshot.
 *   5. Confirming without a reason PATCHes with an empty body.
 *   6. On a muted customer, the pill renders "Unmute" and confirming
 *      PATCHes ``/customers/{id}/unmute`` (no reason fetch).
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPatch = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    patch: (...a: any[]) => mockPatch(...a),
  },
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", brand: "#0284C7", muted: "#999", error: "#DC2626",
    border: "#E5E7EB", onSurface: "#111", onSurfaceSecondary: "#555",
    surfaceSecondary: "#F9FAFB", brandTertiary: "#EFF6FF",
    success: "#16A34A",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 18, "2xl": 24 },
}));

jest.mock("@/src/components/ui", () => {
  const RN = require("react-native");
  return {
    Sheet: ({ visible, children, testID }: any) =>
      visible ? <RN.View testID={testID}>{children}</RN.View> : null,
  };
});

jest.mock("@expo/vector-icons", () => {
  const { View } = require("react-native");
  return { Ionicons: (props: any) => <View {...props} /> };
});

import MuteControlSheet from "../src/components/customers/MuteControlSheet";


afterEach(() => {
  jest.clearAllMocks();
});


const _activeCustomer = { id: "c-1", is_muted: false };
const _mutedCustomer  = { id: "c-2", is_muted: true, muted_at: "2026-02-01T00:00:00Z" };

const _reasons = [
  { id: "r-1", label: "Billing dispute",       is_active: true },
  { id: "r-2", label: "Requested no contact",  is_active: true },
];


describe("MuteControlSheet · P29b mobile parity", () => {
  it("renders the 'Mark Muted' pill for an active customer when canMute", () => {
    const { getByTestId } = render(
      <MuteControlSheet customer={_activeCustomer} canMute canUnmute />,
    );
    expect(getByTestId("mute-control-btn-c-1")).toBeTruthy();
  });

  it("renders nothing when gated (canMute=false, not muted)", () => {
    const { queryByTestId } = render(
      <MuteControlSheet customer={_activeCustomer} canMute={false} canUnmute />,
    );
    expect(queryByTestId("mute-control-btn-c-1")).toBeNull();
  });

  it("opens the sheet and lazily fetches muted reasons", async () => {
    mockGet.mockResolvedValue({ items: _reasons });
    const { getByTestId } = render(
      <MuteControlSheet customer={_activeCustomer} canMute canUnmute />,
    );
    fireEvent.press(getByTestId("mute-control-btn-c-1"));
    await waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith("/settings/muted-reasons"));
    // Reason list rendered with the seeded rows.
    await waitFor(() => expect(getByTestId("mute-control-reason-r-1")).toBeTruthy());
    expect(getByTestId("mute-control-reason-r-2")).toBeTruthy();
    // Warning banner visible.
    expect(getByTestId("mute-control-warning-c-1")).toBeTruthy();
  });

  it("selecting a seeded reason PATCHes /mute with the label snapshot", async () => {
    mockGet.mockResolvedValue({ items: _reasons });
    mockPatch.mockResolvedValue({ muted: true, customer_id: "c-1",
        muted_reason: "Billing dispute", muted_at: "2026-02-02T00:00:00Z" });
    const onChange = jest.fn();
    const { getByTestId } = render(
      <MuteControlSheet customer={_activeCustomer} canMute canUnmute
                          onChange={onChange} />,
    );
    fireEvent.press(getByTestId("mute-control-btn-c-1"));
    await waitFor(() => expect(getByTestId("mute-control-reason-r-1")).toBeTruthy());
    fireEvent.press(getByTestId("mute-control-reason-r-1"));
    await act(async () => {
      fireEvent.press(getByTestId("mute-control-confirm-c-1"));
    });
    expect(mockPatch).toHaveBeenCalledWith(
      "/customers/c-1/mute",
      { muted_reason: "Billing dispute" },
    );
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ muted: true, muted_reason: "Billing dispute" }),
    ));
  });

  it("confirming with no reason PATCHes /mute with empty body", async () => {
    mockGet.mockResolvedValue({ items: _reasons });
    mockPatch.mockResolvedValue({ muted: true, customer_id: "c-1" });
    const { getByTestId } = render(
      <MuteControlSheet customer={_activeCustomer} canMute canUnmute />,
    );
    fireEvent.press(getByTestId("mute-control-btn-c-1"));
    // Wait for the sheet render.
    await waitFor(() => expect(getByTestId("mute-control-confirm-c-1")).toBeTruthy());
    await act(async () => {
      fireEvent.press(getByTestId("mute-control-confirm-c-1"));
    });
    expect(mockPatch).toHaveBeenCalledWith("/customers/c-1/mute", {});
  });

  it("on a muted customer the pill triggers /unmute (no reason fetch)", async () => {
    mockPatch.mockResolvedValue({ unmuted: true, customer_id: "c-2" });
    const onChange = jest.fn();
    const { getByTestId } = render(
      <MuteControlSheet customer={_mutedCustomer} canMute canUnmute
                          onChange={onChange} />,
    );
    fireEvent.press(getByTestId("mute-control-btn-c-2"));
    await waitFor(() => expect(getByTestId("mute-control-confirm-c-2")).toBeTruthy());
    // Confirms the fetch was NOT made — unmute doesn't need reasons.
    expect(mockGet).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.press(getByTestId("mute-control-confirm-c-2"));
    });
    expect(mockPatch).toHaveBeenCalledWith("/customers/c-2/unmute", {});
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ unmuted: true }),
    ));
  });
});
