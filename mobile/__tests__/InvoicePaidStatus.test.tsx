/**
 * InvoicePaidStatus.test.tsx — PDFI-PAID-D mobile parity tests.
 *
 * Verifies the paid badge + sub-row render logic in isolation:
 *   a. ``is_paid=true`` + ``paid_at`` present → paid chip + sub-row render.
 *   b. ``is_paid=false`` / absent → paid chip + sub-row do NOT render.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import { View, Text } from "react-native";

// ── Inline mirror of the detail screen's conditional render logic ──
// Testing in isolation avoids heavy mocking of auth / webview / stripe.

function PaidChip({ isPaid }: { isPaid: boolean }) {
  if (!isPaid) return null;
  return (
    <View testID="invoice-paid-chip">
      <Text>PAID</Text>
    </View>
  );
}

function PaidSubRow({
  isPaid,
  paidAt,
  paidMethod,
}: {
  isPaid: boolean;
  paidAt?: string | null;
  paidMethod?: string | null;
}) {
  if (!isPaid || (!paidAt && !paidMethod)) return null;
  return (
    <View testID="invoice-paid-sub-row">
      <Text>Payment Received</Text>
      {paidAt ? (
        <Text testID="invoice-paid-at">
          Paid on {paidAt.length >= 10 ? paidAt.slice(0, 10) : paidAt}
        </Text>
      ) : null}
      {paidMethod ? (
        <Text testID="invoice-paid-method">
          Method: {paidMethod.replace(/_/g, " ")}
        </Text>
      ) : null}
    </View>
  );
}

// ── Tests ─────────────────────────────────────────────────────────

describe("PDFI-PAID-D — Invoice paid status rendering", () => {
  describe("PaidChip", () => {
    it("renders PAID chip when isPaid=true", () => {
      const { getByTestId, getByText } = render(<PaidChip isPaid={true} />);
      expect(getByTestId("invoice-paid-chip")).toBeTruthy();
      expect(getByText("PAID")).toBeTruthy();
    });

    it("does NOT render when isPaid=false", () => {
      const { queryByTestId } = render(<PaidChip isPaid={false} />);
      expect(queryByTestId("invoice-paid-chip")).toBeNull();
    });
  });

  describe("PaidSubRow", () => {
    it("renders with paid_at + paid_method when isPaid=true", () => {
      const { getByTestId, getByText } = render(
        <PaidSubRow
          isPaid={true}
          paidAt="2026-08-28T18:36:10.481750+00:00"
          paidMethod="manual_cash"
        />,
      );
      expect(getByTestId("invoice-paid-sub-row")).toBeTruthy();
      expect(getByTestId("invoice-paid-at")).toBeTruthy();
      expect(getByText("Paid on 2026-08-28")).toBeTruthy();
      expect(getByTestId("invoice-paid-method")).toBeTruthy();
      expect(getByText("Method: manual cash")).toBeTruthy();
    });

    it("renders with only paidMethod when paidAt is absent", () => {
      const { getByTestId, queryByTestId } = render(
        <PaidSubRow isPaid={true} paidAt={null} paidMethod="stripe" />,
      );
      expect(getByTestId("invoice-paid-sub-row")).toBeTruthy();
      expect(queryByTestId("invoice-paid-at")).toBeNull();
      expect(getByTestId("invoice-paid-method")).toBeTruthy();
    });

    it("renders with only paidAt when paidMethod is absent", () => {
      const { getByTestId, queryByTestId } = render(
        <PaidSubRow isPaid={true} paidAt="2026-01-15" paidMethod={null} />,
      );
      expect(getByTestId("invoice-paid-sub-row")).toBeTruthy();
      expect(getByTestId("invoice-paid-at")).toBeTruthy();
      expect(queryByTestId("invoice-paid-method")).toBeNull();
    });

    it("does NOT render when isPaid=false", () => {
      const { queryByTestId } = render(
        <PaidSubRow
          isPaid={false}
          paidAt="2026-08-28T18:36:10Z"
          paidMethod="manual_cash"
        />,
      );
      expect(queryByTestId("invoice-paid-sub-row")).toBeNull();
    });

    it("does NOT render when isPaid=true but no date or method", () => {
      const { queryByTestId } = render(
        <PaidSubRow isPaid={true} paidAt={null} paidMethod={null} />,
      );
      expect(queryByTestId("invoice-paid-sub-row")).toBeNull();
    });
  });
});
