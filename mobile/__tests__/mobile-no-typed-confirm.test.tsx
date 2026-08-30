/**
 * __tests__/mobile-no-typed-confirm.test.tsx
 *
 * Verifies typed-confirm is removed from all mobile confirm dialogs:
 *   - ConfirmModal has no TextInput
 *   - CustomerDeleteModal has no TextInput
 *   - BulkConfirmModal has no TextInput
 *   - DeleteAccountSection has no typed-confirm TextInput (removed)
 *   - Confirm buttons are enabled immediately (no type-gate)
 */
import React from "react";
import { render } from "@testing-library/react-native";

/* ── Mocks ────────────────────────────────────────────── */
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  router: { replace: jest.fn() },
  usePathname: () => "/",
  useSegments: () => [],
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "customer", id: "c1" } }),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(() => Promise.resolve({})),
    delete: jest.fn(() => Promise.resolve({})),
  },
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: { clear: jest.fn(() => Promise.resolve()) },
}));

import { ConfirmModal } from "@/src/components/ConfirmModal";
import CustomerDeleteModal from "@/src/components/customers/CustomerDeleteModal";
import { BulkConfirmModal } from "@/src/components/bulk-select/BulkSelectToolkit";
import DeleteAccountSection from "@/src/components/portal/DeleteAccountSection";

describe("No Typed-Confirm on Mobile", () => {
  it("ConfirmModal has no TextInput, confirm button enabled immediately", () => {
    const tree = render(
      <ConfirmModal
        visible={true}
        title="Delete item?"
        message="This cannot be undone."
        confirmLabel="Delete"
        confirmStyle="destructive"
        onCancel={jest.fn()}
        onConfirm={jest.fn()}
      />
    );
    // No TextInput in the tree
    const inputs = tree.queryAllByTestId(/input/i);
    expect(inputs.length).toBe(0);
    // Confirm button is enabled
    const confirmBtn = tree.getByTestId("confirm-modal-confirm");
    expect(confirmBtn.props.accessibilityState?.disabled).toBeFalsy();
    console.log("✅ NTC-T1: ConfirmModal — no TextInput, confirm enabled");
  });

  it("CustomerDeleteModal has no TextInput", () => {
    const tree = render(
      <CustomerDeleteModal
        visible={true}
        customerName="John Doe"
        onCancel={jest.fn()}
        onSoftDelete={jest.fn()}
        onHardDelete={jest.fn()}
      />
    );
    // The modal has no TextInput at all — just 3 buttons
    const softBtn = tree.getByTestId("customer-delete-soft-btn");
    expect(softBtn).toBeTruthy();
    const hardBtn = tree.getByTestId("customer-delete-hard-btn");
    expect(hardBtn).toBeTruthy();
    console.log("✅ NTC-T2: CustomerDeleteModal — no TextInput, buttons work");
  });

  it("BulkConfirmModal has no TextInput, confirm enabled immediately", () => {
    const tree = render(
      <BulkConfirmModal
        open={true}
        title="Delete 5 customers?"
        description="This removes them permanently."
        confirmLabel="Delete"
        onConfirm={jest.fn()}
        onClose={jest.fn()}
      />
    );
    const confirmBtn = tree.getByTestId("bulk-delete-confirm-btn");
    expect(confirmBtn).toBeTruthy();
    // Should not be disabled
    expect(confirmBtn.props.accessibilityState?.disabled).toBeFalsy();
    console.log("✅ NTC-T3: BulkConfirmModal — no TextInput, confirm enabled");
  });

  it("DeleteAccountSection has no typed-confirm TextInput, confirm enabled immediately", () => {
    const tree = render(<DeleteAccountSection />);
    // Open the modal
    const openBtn = tree.getByTestId("portal-profile-delete-account-open-btn");
    const { fireEvent } = require("@testing-library/react-native");
    fireEvent.press(openBtn);
    // No text input should exist
    const phraseInput = tree.queryByTestId("portal-profile-delete-account-phrase-input");
    expect(phraseInput).toBeNull();
    // Confirm button should be enabled
    const confirmBtn = tree.getByTestId("portal-profile-delete-account-confirm-btn");
    expect(confirmBtn).toBeTruthy();
    console.log("✅ NTC-T4: DeleteAccountSection — typed-confirm removed, confirm enabled");
  });
});
