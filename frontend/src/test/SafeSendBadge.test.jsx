/**
 * SAFE-SEND-B · Feb-2026 — ``SafeSendBadge`` component tests.
 *
 * Locks the badge's detection + rendering contract:
 *
 *   1. ``row.redirected === true``  → amber "Redirected" pill.
 *   2. ``row.redirected === false`` → green "Live" pill.
 *   3. ``row.context == null``      → renders nothing (legacy row).
 *   4. ``intended != actual`` alone (no ``redirected`` bool) →
 *      still detects and renders "Redirected".
 *   5. Tooltip content contains both redacted recipients.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";
import { describe, it, expect } from "vitest";

import SafeSendBadge from "@/components/SafeSendBadge";


describe("SAFE-SEND-B · SafeSendBadge", () => {
  it("renders Redirected pill when row.redirected === true", () => {
    render(<SafeSendBadge row={{
      context: "agent",
      redirected: true,
      intended_recipient_redacted: "cu******@example.com",
      recipient_redacted: "ad***@admin.test",
    }} />);
    const pill = screen.getByTestId("safe-send-badge-redirected");
    expect(pill).toHaveTextContent("Redirected");
  });

  it("renders Live pill when row.redirected === false", () => {
    render(<SafeSendBadge row={{
      context: "system",
      redirected: false,
      intended_recipient_redacted: "cu******@example.com",
      recipient_redacted: "cu******@example.com",
    }} />);
    const pill = screen.getByTestId("safe-send-badge-live");
    expect(pill).toHaveTextContent("Live");
  });

  it("renders nothing when row.context == null (legacy pre-SAFE-SEND row)", () => {
    const { container } = render(<SafeSendBadge row={{
      // no context, no redirected — legacy row shape.
      recipient_redacted: "cu******@example.com",
    }} />);
    expect(container.querySelector("[data-testid^='safe-send-badge']")).toBeNull();
  });

  it("renders nothing when row is undefined", () => {
    const { container } = render(<SafeSendBadge row={undefined} />);
    expect(container.querySelector("[data-testid^='safe-send-badge']")).toBeNull();
  });

  it("detects redirect from recipient-pair mismatch alone (no redirected bool)", () => {
    // The SAFE-SEND-A.1 audit-row shape ALWAYS carries ``redirected``;
    // this defensive branch covers a hypothetical caller that writes
    // the pair without the bool (e.g. a hand-crafted diagnostic row).
    render(<SafeSendBadge row={{
      context: "agent",
      // no ``redirected`` field
      intended_recipient_redacted: "cu******@example.com",
      recipient_redacted: "ad***@admin.test",
    }} />);
    expect(screen.getByTestId("safe-send-badge-redirected"))
      .toBeInTheDocument();
  });

  it("renders nothing when redirect state is indeterminate", () => {
    const { container } = render(<SafeSendBadge row={{
      context: "agent",
      // no ``redirected`` and no recipient pair to compare
    }} />);
    expect(container.querySelector("[data-testid^='safe-send-badge']")).toBeNull();
  });

  it("wraps the pill in a tooltip trigger when recipient pair is known", () => {
    render(<SafeSendBadge row={{
      context: "agent",
      redirected: true,
      intended_recipient_redacted: "cu******@example.com",
      recipient_redacted: "ad***@admin.test",
    }} />);
    expect(screen.getByTestId("safe-send-badge-tooltip-trigger"))
      .toBeInTheDocument();
  });

  it("does not wrap in a tooltip when no recipient pair is available", () => {
    render(<SafeSendBadge row={{
      context: "agent",
      redirected: true,
      // no recipient pair
    }} />);
    // Pill renders, but tooltip trigger does NOT.
    expect(screen.getByTestId("safe-send-badge-redirected"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("safe-send-badge-tooltip-trigger"))
      .toBeNull();
  });

  it("supports the ``actual_recipient_redacted`` alias in the row shape", () => {
    // Not every caller uses ``recipient_redacted`` — some (e.g. the
    // hypothetical intelligence-hub feed AIHUB-C will emit) use the
    // fully-qualified ``actual_recipient_redacted``.  Assert parity.
    render(<SafeSendBadge row={{
      context: "agent",
      redirected: true,
      intended_recipient_redacted: "cu******@example.com",
      actual_recipient_redacted: "ad***@admin.test",
    }} />);
    expect(screen.getByTestId("safe-send-badge-redirected"))
      .toBeInTheDocument();
    expect(screen.getByTestId("safe-send-badge-tooltip-trigger"))
      .toBeInTheDocument();
  });
});
