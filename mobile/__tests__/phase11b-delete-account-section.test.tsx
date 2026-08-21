/**
 * Feb-2026 · P11b — Mobile delete-account confirmation flow.
 *
 * Pins the two-step confirmation on the customer portal profile:
 * the destructive confirm button STAYS disabled until the phrase
 * ``DELETE`` is typed verbatim into the modal input; only then
 * does clicking it fire ``api.delete("/customer-portal/account")``.
 *
 * Also confirms that mounting alone does NOT fire the delete call.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ── Hoisted mocks ────────────────────────────────────────────── */

const mockApiDelete = jest.fn(async () => ({ deleted: true, anonymized_at: "x" }));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    del: jest.fn(),
    delete: (...a: any[]) => mockApiDelete(...a),
    patch: jest.fn(),
  },
}));

jest.mock("expo-router", () => ({
  router: { replace: jest.fn() },
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  clear: jest.fn(async () => {}),
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

// Silence RN's Alert during the test.
jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import DeleteAccountSection from "@/src/components/portal/DeleteAccountSection";


describe("DeleteAccountSection (P11b · App Store item 3)", () => {
  beforeEach(() => {
    mockApiDelete.mockClear();
  });

  test("mount alone does NOT fire the delete call", () => {
    render(<DeleteAccountSection />);
    expect(mockApiDelete).not.toHaveBeenCalled();
  });

  test("phrase gate: DELETE required before the destructive call fires", async () => {
    const { getByTestId, queryByTestId } = render(<DeleteAccountSection />);

    // Modal is closed initially.
    expect(queryByTestId("portal-profile-delete-account-modal")).toBeNull();

    // Open the modal.
    fireEvent.press(getByTestId("portal-profile-delete-account-open-btn"));
    expect(getByTestId("portal-profile-delete-account-modal")).toBeTruthy();

    // Wrong phrase (lowercase) → tapping confirm does NOT fire the call.
    fireEvent.changeText(
      getByTestId("portal-profile-delete-account-phrase-input"),
      "delete",
    );
    fireEvent.press(getByTestId("portal-profile-delete-account-confirm-btn"));
    // Give the microtask queue a beat — mock should NOT have fired.
    await new Promise((r) => setTimeout(r, 0));
    expect(mockApiDelete).not.toHaveBeenCalled();

    // Correct phrase → firing the confirm hits the DELETE endpoint.
    fireEvent.changeText(
      getByTestId("portal-profile-delete-account-phrase-input"),
      "DELETE",
    );
    fireEvent.press(getByTestId("portal-profile-delete-account-confirm-btn"));

    await waitFor(() => expect(mockApiDelete).toHaveBeenCalledTimes(1));
    expect(mockApiDelete).toHaveBeenCalledWith("/customer-portal/account");
  });
});
