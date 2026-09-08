/**
 * Feb-2026 · Notifications filter dropdown — UI + grouping tests.
 *
 * Covers:
 *   1. ``groupKinds`` places kinds into declared sections in
 *      ``SECTION_ORDER`` and buckets unknown keys into "Other".
 *   2. ``NotificationsFilterDropdown``:
 *      - Renders trigger with "Filter: All" when no selection.
 *      - Opening the popover renders section headers.
 *      - Toggling a checkbox emits the updated selection.
 *      - Multi-select shows "Filter: {first} +N" summary.
 *      - "All" and "Clear" both reset the selection to [].
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import { groupKinds, SECTION_ORDER } from "@/lib/notificationGroups";
import NotificationsFilterDropdown from "@/components/notifications/NotificationsFilterDropdown";

const KINDS = [
  { key: "rc_sms_inbound", label: "SMS · Inbound" },
  { key: "rc_call_inbound", label: "Call · Inbound" },
  { key: "job_assigned", label: "Job · Assigned" },
  { key: "invoice_paid", label: "Invoice · Paid" },
  { key: "chat_dm", label: "Chat · DM" },
  { key: "customer_message", label: "Customer message" },
  { key: "review_received", label: "Review received" },
  { key: "system_alert", label: "System alert" },
  { key: "unknown_new_kind_zzz", label: "Some new kind" },
];

// scrollIntoView shim — Radix Popover calls this on open.
beforeEach(() => {
  if (!HTMLElement.prototype.scrollIntoView) {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  }
});
afterEach(() => cleanup());


describe("groupKinds()", () => {
  it("groups mapped kinds into declared sections and unknown into 'Other'", () => {
    const groups = groupKinds(KINDS);
    const bySection = Object.fromEntries(groups.map((g) => [g.section, g.items.map((i) => i.key)]));
    expect(bySection["RingCentral"]).toEqual(["rc_sms_inbound", "rc_call_inbound"]);
    expect(bySection["Jobs"]).toEqual(["job_assigned"]);
    expect(bySection["Invoices & Payments"]).toEqual(["invoice_paid"]);
    expect(bySection["Team & Chat"]).toEqual(["chat_dm"]);
    expect(bySection["Customers & Portal"]).toEqual(["customer_message"]);
    expect(bySection["Sales & Marketing"]).toEqual(["review_received"]);
    expect(bySection["System & Inventory"]).toEqual(["system_alert"]);
    expect(bySection["Other"]).toEqual(["unknown_new_kind_zzz"]);
  });

  it("returns groups ordered by SECTION_ORDER", () => {
    const orderedSections = groupKinds(KINDS).map((g) => g.section);
    // Should follow declared order (sub-sequence of SECTION_ORDER).
    let prev = -1;
    for (const s of orderedSections) {
      const idx = SECTION_ORDER.indexOf(s);
      expect(idx).toBeGreaterThan(prev);
      prev = idx;
    }
  });

  it("returns [] for empty/undefined input", () => {
    expect(groupKinds([])).toEqual([]);
    expect(groupKinds(undefined)).toEqual([]);
  });
});


describe("<NotificationsFilterDropdown />", () => {
  it("shows 'Filter: All' when nothing is selected", () => {
    render(
      <NotificationsFilterDropdown kinds={KINDS} selected={[]} onChange={() => {}} />
    );
    expect(screen.getByTestId("notif-filter-dropdown-summary").textContent)
      .toBe("Filter: All");
  });

  it("shows the label when exactly one kind is selected", () => {
    render(
      <NotificationsFilterDropdown kinds={KINDS} selected={["invoice_paid"]}
                                    onChange={() => {}} />
    );
    expect(screen.getByTestId("notif-filter-dropdown-summary").textContent)
      .toBe("Filter: Invoice · Paid");
  });

  it("shows '+N' summary when multiple kinds are selected", () => {
    render(
      <NotificationsFilterDropdown
        kinds={KINDS}
        selected={["invoice_paid", "job_assigned", "rc_sms_inbound"]}
        onChange={() => {}}
      />
    );
    // First selected → its label + " +2".
    expect(screen.getByTestId("notif-filter-dropdown-summary").textContent)
      .toBe("Filter: Invoice · Paid +2");
  });

  it("emits the toggled selection on checkbox click", () => {
    const onChange = vi.fn();
    render(
      <NotificationsFilterDropdown kinds={KINDS} selected={[]} onChange={onChange} />
    );
    // Open popover.
    fireEvent.click(screen.getByTestId("notif-filter-dropdown"));
    // Click a specific option label — the checkbox inside toggles onCheckedChange.
    fireEvent.click(screen.getByTestId("notif-filter-dropdown-option-invoice_paid"));
    expect(onChange).toHaveBeenCalledWith(["invoice_paid"]);
  });

  it("emits deselect (removes from array) on second click", () => {
    const onChange = vi.fn();
    render(
      <NotificationsFilterDropdown
        kinds={KINDS} selected={["invoice_paid", "job_assigned"]}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByTestId("notif-filter-dropdown"));
    fireEvent.click(screen.getByTestId("notif-filter-dropdown-option-invoice_paid"));
    expect(onChange).toHaveBeenCalledWith(["job_assigned"]);
  });

  it("'All' and 'Clear' both reset the selection to []", () => {
    const onChange = vi.fn();
    render(
      <NotificationsFilterDropdown
        kinds={KINDS} selected={["invoice_paid"]} onChange={onChange}
      />
    );
    fireEvent.click(screen.getByTestId("notif-filter-dropdown"));
    fireEvent.click(screen.getByTestId("notif-filter-dropdown-all"));
    expect(onChange).toHaveBeenLastCalledWith([]);
    // Re-render open with a non-empty selection so 'Clear' is enabled.
    onChange.mockClear();
    fireEvent.click(screen.getByTestId("notif-filter-dropdown-clear"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("renders section headers for present sections only", () => {
    render(
      <NotificationsFilterDropdown kinds={KINDS} selected={[]} onChange={() => {}} />
    );
    fireEvent.click(screen.getByTestId("notif-filter-dropdown"));
    // Present sections in our KINDS fixture: RC, Jobs, I&P, T&C, C&P, S&M, S&I, Other.
    expect(screen.getByTestId("notif-filter-dropdown-section-ringcentral")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-jobs")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-invoices-and-payments")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-team-and-chat")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-customers-and-portal")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-sales-and-marketing")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-system-and-inventory")).toBeTruthy();
    expect(screen.getByTestId("notif-filter-dropdown-section-other")).toBeTruthy();
  });
});
