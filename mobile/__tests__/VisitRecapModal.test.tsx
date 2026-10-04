/**
 * VisitRecapModal.test.tsx — APR-IV behavioural tests.
 *
 * Verifies SMS channel availability now depends solely on
 * customer.phone (the legacy after-hours fallback was dropped
 * in APR-II / APR-III).
 */
import React from "react";
import { render } from "@testing-library/react-native";
import VisitRecapModal from "@/src/components/checklist/VisitRecapModal";

/* ── Mocks ───────────────────────────────────────────────────── */
jest.mock("@/src/api", () => ({
  api: { post: jest.fn().mockResolvedValue({}) },
}));

jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#1B1F5C", surface: "#fff", border: "#ddd",
    success: "#16A34A", warning: "#F59E0B", error: "#EF4444",
    onSurface: "#111", onSurfaceSecondary: "#666", muted: "#999",
    surfaceSecondary: "#f5f5f5", brandTertiary: "#E8E8FF",
    surfaceTertiary: "#eee", divider: "#eee",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 18, xl: 22 },
}));

/* ── Tests ────────────────────────────────────────────────────── */
describe("VisitRecapModal — APR-IV SMS channel availability", () => {
  const baseProps = {
    visible: true,
    serviceReportId: "sr-1",
    onClose: jest.fn(),
  };

  it("SMS NOT available when customer has no primary phone (legacy fallback ignored)", () => {
    // A customer with only a legacy after-hours number and no primary
    // phone should NOT have SMS enabled after APR-II removal.
    const customer = { phone: "", email: "", alert_phone: "+16025559999" } as any;

    const { getByTestId } = render(
      <VisitRecapModal {...baseProps} customer={customer} />,
    );

    // The ChannelPill always renders but is disabled={true} when
    // hasPhone is false.  After APR-IV the legacy key is ignored,
    // so SMS pill must be disabled.
    const smsBtn = getByTestId("visit-recap-channel-sms");
    expect(smsBtn.props.accessibilityState?.disabled).toBe(true);

    const bothBtn = getByTestId("visit-recap-channel-both");
    expect(bothBtn.props.accessibilityState?.disabled).toBe(true);
  });

  it("SMS IS available when customer has a primary phone", () => {
    const customer = { phone: "+16025550102", email: "" };

    const { getByTestId } = render(
      <VisitRecapModal {...baseProps} customer={customer} />,
    );

    // With a valid primary phone, SMS pill should be enabled.
    const smsBtn = getByTestId("visit-recap-channel-sms");
    expect(smsBtn.props.accessibilityState?.disabled).not.toBe(true);
  });
});
