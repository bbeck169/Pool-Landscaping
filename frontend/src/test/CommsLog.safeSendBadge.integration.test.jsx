/**
 * SAFE-SEND-B · Feb-2026 — SafeSendBadge integration test.
 *
 * Since no live FE surface currently renders ``comms_send_log``
 * rows (recon confirmed — the only admin comms page today is
 * ``AdminCommsSuppressionLog``, which reads the ``/comms/
 * suppression-log`` collection, a DIFFERENT collection than
 * the SAFE-SEND audit table), this test mounts a MOCK admin
 * page that renders 3 rows through the ``SafeSendBadge``
 * component.  That gives us end-to-end coverage of the badge's
 * inline behaviour without shipping a new page ahead of the
 * intelligence-hub track (AIHUB-C).
 *
 * When AIHUB-C ships the real admin surface, its test suite
 * can replace this mock with a real page render + same
 * assertions.  Badge contract stays stable.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import SafeSendBadge from "@/components/SafeSendBadge";


// ═══════════════════════════════════════════════════════════════
// Mock admin surface — mirrors the shape AIHUB-C will emit.
// ═══════════════════════════════════════════════════════════════
function MockCommsLogTable({ rows }) {
  return (
    <table data-testid="mock-comms-log-table">
      <thead>
        <tr>
          <th>Channel</th>
          <th>Recipient</th>
          <th>Status</th>
          <th>Safe-Send</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} data-testid={`mock-row-${r.id}`}>
            <td data-testid={`mock-cell-channel-${r.id}`}>{r.channel}</td>
            <td data-testid={`mock-cell-recipient-${r.id}`}>
              {r.recipient_redacted}
            </td>
            <td data-testid={`mock-cell-status-${r.id}`}>
              {r.provider_status}
            </td>
            <td data-testid={`mock-cell-badge-${r.id}`}>
              <SafeSendBadge row={r} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}


// ═══════════════════════════════════════════════════════════════
// Fixture — 3 rows: one redirected, one live, one legacy null.
// ═══════════════════════════════════════════════════════════════
const _FIXTURE = [
  // Redirected — the SAFE-SEND-A gate fired for an AGENT / TEST send.
  {
    id: "row-redirected",
    at: "2026-02-25T10:00:00Z",
    channel: "email",
    context: "agent",
    redirected: true,
    intended_recipient_redacted: "cu******@example.com",
    recipient_redacted: "ad***@admin.test",
    provider_status: "sent",
    ok: true,
  },
  // Live — real customer got the send (SYSTEM passthrough).
  {
    id: "row-live",
    at: "2026-02-25T10:05:00Z",
    channel: "email",
    context: "system",
    redirected: false,
    intended_recipient_redacted: "cu******@example.com",
    recipient_redacted: "cu******@example.com",
    provider_status: "sent",
    ok: true,
  },
  // Legacy — pre-SAFE-SEND-A row, no context or redirected fields.
  {
    id: "row-legacy",
    at: "2026-01-10T09:00:00Z",
    channel: "email",
    recipient_redacted: "cu******@example.com",
    provider_status: "sent",
    ok: true,
    // No ``context``, no ``redirected``, no intended pair.
  },
];


// ═══════════════════════════════════════════════════════════════
// Assertions
// ═══════════════════════════════════════════════════════════════
describe("SAFE-SEND-B · CommsLog badge integration", () => {
  it("renders redirected + live + legacy rows with correct badge states", () => {
    render(<MockCommsLogTable rows={_FIXTURE} />);

    // Row 1 — Redirected pill inside its cell.
    const redirectedRow = screen.getByTestId("mock-row-row-redirected");
    expect(
      within(redirectedRow).getByTestId("safe-send-badge-redirected"),
    ).toHaveTextContent("Redirected");
    // Tooltip trigger present because both recipients are known.
    expect(
      within(redirectedRow).getByTestId("safe-send-badge-tooltip-trigger"),
    ).toBeInTheDocument();

    // Row 2 — Live pill.
    const liveRow = screen.getByTestId("mock-row-row-live");
    expect(
      within(liveRow).getByTestId("safe-send-badge-live"),
    ).toHaveTextContent("Live");

    // Row 3 — legacy row → cell empty, no badge markup at all.
    const legacyRow = screen.getByTestId("mock-row-row-legacy");
    const legacyBadgeCell = within(legacyRow)
      .getByTestId("mock-cell-badge-row-legacy");
    expect(
      legacyBadgeCell.querySelector("[data-testid^='safe-send-badge']"),
    ).toBeNull();
  });

  it("badges only render in the badge column (inline placement)", () => {
    render(<MockCommsLogTable rows={_FIXTURE} />);
    // The redirected pill must be INSIDE the badge cell, not the
    // recipient cell (regression guard against a stray wrapper).
    const redirectedRow = screen.getByTestId("mock-row-row-redirected");
    const recipientCell = within(redirectedRow)
      .getByTestId("mock-cell-recipient-row-redirected");
    expect(
      recipientCell.querySelector("[data-testid^='safe-send-badge']"),
    ).toBeNull();
  });

  it("total badge count matches rows with a defined context", () => {
    render(<MockCommsLogTable rows={_FIXTURE} />);
    // 3 rows, 2 have context ⇒ exactly 2 badges rendered.
    const allBadges = screen.getAllByTestId(
      /^safe-send-badge-(redirected|live)$/,
    );
    expect(allBadges).toHaveLength(2);
  });
});
