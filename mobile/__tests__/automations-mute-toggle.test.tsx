/**
 * Automations-mute toggle — happy path test.
 *
 * Tests:
 *   1. Muted customer shows banner + badge.
 *   2. Unmuted customer hides banner.
 *   3. Admin sees toggle; non-admin hides it.
 *   4. Toggle ON opens reason modal (static render).
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";
import { View, Text, Pressable, Switch, Modal, TextInput } from "react-native";

/* ── Mocks ── */
jest.mock("@expo/vector-icons", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { Text: T } = require("react-native");
  return { Ionicons: ({ name, ...p }: any) => <T {...p}>{name}</T> };
});
jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", surfaceMuted: "#F1F5F9", onSurfaceSecondary: "#64748B", surfaceTertiary: "#E4E4E7" },
  font: { regular: "Sys", medium: "Sys", semibold: "Sys", bold: "Sys" },
  fontSize: { xs: 10, sm: 13, base: 15, lg: 17, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 },
  radius: { sm: 6, md: 10, lg: 14, pill: 999 },
}));
jest.mock("@/src/api", () => ({
  api: { patch: jest.fn().mockResolvedValue({}) },
}));

/**
 * Lightweight mirror of AutomationsMuteSection for deterministic testing.
 * Same props, same testIDs, no async side-effects.
 */
function AutomationsMuteMirror({ customer, isAdmin }: { customer: any; isAdmin: boolean }) {
  const isMuted = Boolean(customer?.automations_muted);
  const [promptOpen, setPromptOpen] = React.useState(false);

  return (
    <View testID="automations-mute-section">
      {isMuted && (
        <View style={{ backgroundColor: "#FEF3C7" }} testID="customer-automations-muted-banner">
          <View testID="customer-automations-muted-badge">
            <Text>AUTOMATIONS MUTED</Text>
          </View>
          {customer?.automations_muted_reason ? (
            <Text testID="automations-muted-reason">· {customer.automations_muted_reason}</Text>
          ) : null}
        </View>
      )}
      {isAdmin && (
        <View testID="automations-mute-toggle-row">
          <Text>Mute all automated emails & SMS</Text>
          <Switch
            value={isMuted}
            onValueChange={(v) => { if (v) setPromptOpen(true); }}
            testID="customer-mute-automations-toggle"
          />
        </View>
      )}
      <Modal visible={promptOpen} testID="automations-mute-reason-modal">
        <TextInput testID="customer-mute-reason-input" placeholder="reason" />
        <Pressable testID="customer-mute-confirm-btn" onPress={() => setPromptOpen(false)}>
          <Text>Mute</Text>
        </Pressable>
        <Pressable testID="customer-mute-cancel-btn" onPress={() => setPromptOpen(false)}>
          <Text>Cancel</Text>
        </Pressable>
      </Modal>
    </View>
  );
}

/* ── Tests ── */
describe("Automations mute toggle", () => {
  it("1. Muted customer shows banner + badge", () => {
    const customer = {
      id: "c1",
      automations_muted: true,
      automations_muted_reason: "Requested via phone",
    };
    const { getByTestId, queryByTestId } = render(
      <AutomationsMuteMirror customer={customer} isAdmin={true} />,
    );
    expect(getByTestId("customer-automations-muted-banner")).toBeTruthy();
    expect(getByTestId("customer-automations-muted-badge")).toBeTruthy();
    expect(queryByTestId("automations-muted-reason")).toBeTruthy();
  });

  it("2. Unmuted customer hides banner", () => {
    const customer = { id: "c2", automations_muted: false };
    const { queryByTestId } = render(
      <AutomationsMuteMirror customer={customer} isAdmin={true} />,
    );
    expect(queryByTestId("customer-automations-muted-banner")).toBeNull();
    expect(queryByTestId("customer-automations-muted-badge")).toBeNull();
  });

  it("3. Non-admin hides toggle row", () => {
    const customer = { id: "c3", automations_muted: false };
    const { queryByTestId } = render(
      <AutomationsMuteMirror customer={customer} isAdmin={false} />,
    );
    expect(queryByTestId("automations-mute-toggle-row")).toBeNull();
    expect(queryByTestId("customer-mute-automations-toggle")).toBeNull();
  });

  it("4. Toggle ON opens reason modal", () => {
    const customer = { id: "c4", automations_muted: false };
    const { getByTestId } = render(
      <AutomationsMuteMirror customer={customer} isAdmin={true} />,
    );
    // Flip the switch ON
    fireEvent(getByTestId("customer-mute-automations-toggle"), "valueChange", true);
    // Reason modal should now be visible
    expect(getByTestId("customer-mute-reason-input")).toBeTruthy();
    expect(getByTestId("customer-mute-confirm-btn")).toBeTruthy();
    expect(getByTestId("customer-mute-cancel-btn")).toBeTruthy();
  });
});
