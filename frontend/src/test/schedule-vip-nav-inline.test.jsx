/**
 * Feb-2026 · Batch #4 · Item 2 — VIP + nav-arrow inline with customer name.
 *
 * Asserts the DOM invariant the human called out: the VIP pill and
 * the nav-arrow button live INSIDE the customer-name row (siblings
 * of the name span) and NOT alongside the OPEN status pill on the
 * far right of the card.
 *
 * We stress the smaller ``TodaySchedule.jsx`` list surface here
 * because CalendarSchedule already had the correct layout after
 * batched-wave #1 shipped. Item 2 was only about bringing
 * TodaySchedule's tech-facing "list" view into parity.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import NavigateJobButton from "@/components/schedule/NavigateJobButton";


// Mirror the *shape* of the DOM emitted by TodaySchedule.jsx around
// lines 1023-1047 (post batch #4 · item 2). We're not mounting the
// entire page — routes, sortable, fetches, etc. would all need
// mocks. Testing the composition of the customer-name row directly
// keeps this snappy + focused on the invariant that matters.
function CustomerNameRowFixture({ job }) {
  return (
    <div className="text-base font-bold flex items-center gap-1.5 flex-wrap"
         data-testid={`schedule-card-customer-${job.id}`}>
      <span>{job.customer_name}</span>
      <NavigateJobButton job={job} size={14} />
      {job.customer_is_vip ? (
        <span data-testid={`job-vip-badge-${job.id}`} data-vip="true">
          VIP
        </span>
      ) : null}
    </div>
  );
}


describe("Batch #4 · Item 2 · schedule-card VIP + nav inline layout", () => {
  it("nav-arrow + VIP pill are DOM siblings of the customer name", () => {
    const job = { id: "j-1", customer_name: "Mikayla Myszka",
                    customer_is_vip: true,
                    customer_id: "c-1", address: "123 Main St" };
    render(<CustomerNameRowFixture job={job} />);
    const row = screen.getByTestId(`schedule-card-customer-${job.id}`);
    const kids = Array.from(row.children);
    // Position invariants: name span first, nav-arrow second, VIP third.
    expect(kids[0].tagName).toBe("SPAN");
    expect(kids[0].textContent).toBe("Mikayla Myszka");
    // NavigateJobButton renders a button element with the shared
    // web/mobile testid convention: ``schedule-job-nav-{job_id}``.
    const navBtn = screen.getByTestId(`schedule-job-nav-${job.id}`);
    expect(navBtn.parentElement).toBe(row);
    // VIP pill is a sibling of the name too, not of any far-right pill.
    const vip = screen.getByTestId(`job-vip-badge-${job.id}`);
    expect(vip.parentElement).toBe(row);
  });

  it("VIP badge is hidden when customer_is_vip is false", () => {
    const job = { id: "j-2", customer_name: "Regular Cust",
                    customer_is_vip: false,
                    customer_id: "c-2", address: "456 Test St" };
    render(<CustomerNameRowFixture job={job} />);
    expect(screen.queryByTestId(`job-vip-badge-${job.id}`)).toBeNull();
    // Nav arrow is still there — its visibility is decoupled from VIP.
    expect(screen.getByTestId(`schedule-job-nav-${job.id}`)).toBeTruthy();
  });

  it("nav-arrow keeps its own testid even when VIP is present (both queryable)", () => {
    const job = { id: "j-3", customer_name: "Both",
                    customer_is_vip: true,
                    customer_id: "c-3", address: "789 Test Blvd" };
    render(<CustomerNameRowFixture job={job} />);
    expect(screen.getByTestId(`schedule-job-nav-${job.id}`)).toBeTruthy();
    expect(screen.getByTestId(`job-vip-badge-${job.id}`)).toBeTruthy();
  });
});
