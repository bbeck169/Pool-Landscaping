/**
 * SCHEDULE-CUSTOMER-CLICKTHROUGH · Feb-2026 — admin + super_admin
 * see the customer name on schedule cards as a clickable
 * ``<CustomerLink>`` that navigates to ``/customers/<id>``.
 * Non-admin roles keep the pre-existing directions shortcut on
 * the name; directions remain accessible to admins via the
 * address button underneath.
 *
 * The two schedule surfaces (``TodaySchedule.jsx`` 1244 LOC +
 * ``CalendarSchedule.jsx`` 3471 LOC) have deep bootstraps that
 * are costly to mount in isolation.  We lock the wiring via
 * source-level contract regexes PLUS one behavioural test on the
 * shared ``<CustomerLink>`` primitive to prove the ``data-testid``
 * override surfaces correctly through its ``{...rest}`` spread.
 */
import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fs from "fs";
import path from "path";

import { CustomerLink }
  from "@/components/customer/CustomerLink";


const TODAY_SRC = fs.readFileSync(
  path.resolve(__dirname, "../TodaySchedule.jsx"),
  "utf8",
);
const CAL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../CalendarSchedule.jsx"),
  "utf8",
);


afterEach(() => cleanup());


describe("SCHEDULE-CUSTOMER-CLICKTHROUGH · source-level wiring "
         + "contract", () => {
  it("TodaySchedule.jsx: customer-name render guards on admin + "
     + "super_admin + j.customer_id", () => {
    // Phase CROSS-REF Feb-2026 — the admin/super_admin check moved
    // from an inline ``user?.role`` reference inside the helper
    // (which was a scope bug — see the inline comment at
    // ``TodaySchedule.jsx`` ~L1155-1162) to a prop-drilled
    // ``isAdminTier`` boolean computed at the parent via
    // ``["admin", "super_admin"].includes(user.role)``. Lock the
    // new shape: both the parent prop-pass + the gated child.
    expect(TODAY_SRC).toMatch(
      /isAdminTier=\{\s*\["admin",\s*"super_admin"\]\.includes\([\s\S]{0,80}?\)/,
    );
    expect(TODAY_SRC).toMatch(/isAdminTier\s*&&\s*j\.customer_id/);
  });

  it("TodaySchedule.jsx: renders ``<CustomerLink>`` with the "
     + "schedule-card-customer-link-{j.id} testid for admins", () => {
    expect(TODAY_SRC).toMatch(/<CustomerLink/);
    expect(TODAY_SRC).toMatch(
      /data-testid=\{`schedule-card-customer-link-\$\{j\.id\}`\}/,
    );
    // CustomerLink receives customerId + name from the job row.
    expect(TODAY_SRC).toMatch(
      /customerId=\{j\.customer_id\}/,
    );
  });

  it("TodaySchedule.jsx: non-admin + missing-customer_id fallback "
     + "span carries the -static-{j.id} testid", () => {
    expect(TODAY_SRC).toMatch(
      /data-testid=\{`schedule-card-customer-static-\$\{j\.id\}`\}/,
    );
  });

  it("TodaySchedule.jsx: pre-existing directions-button testid "
     + "preserved (non-admin UX unchanged)", () => {
    expect(TODAY_SRC).toMatch(
      /data-testid=\{`schedule-card-\$\{j\.id\}-customer-name-directions`\}/,
    );
  });

  it("CalendarSchedule.jsx: customer-name render guards on admin + "
     + "super_admin + j.customer_id", () => {
    // Phase SCHEDULE-CUSTOMER-CLICKTHROUGH · Feb-2026 — the gate
    // moved from an inline ``user?.role`` reference inside
    // ``GridPanel`` (bare-ref ReferenceError — see comment at
    // ``CalendarSchedule.jsx:1118-1125``) to a prop-drilled
    // ``canClickCustomerName`` boolean computed at the parent via
    // ``["admin", "super_admin"].includes(…)``. Lock the two
    // required anchors: the parent prop + the gated child.
    expect(CAL_SRC).toMatch(
      /const\s+canClickCustomerName\s*=\s*\["admin",\s*"super_admin"\]\.includes\(/,
    );
    expect(CAL_SRC).toMatch(/canClickCustomerName[\s\S]{0,40}&&\s*j\.customer_id/);
  });

  it("CalendarSchedule.jsx: renders ``<CustomerLink>`` with the "
     + "schedule-card-customer-link-{j.id} testid for admins", () => {
    expect(CAL_SRC).toMatch(/<CustomerLink/);
    expect(CAL_SRC).toMatch(
      /data-testid=\{`schedule-card-customer-link-\$\{j\.id\}`\}/,
    );
    expect(CAL_SRC).toMatch(
      /customerId=\{j\.customer_id\}/,
    );
  });

  it("CalendarSchedule.jsx: non-admin + missing-customer_id "
     + "fallback span carries the -static-{j.id} testid", () => {
    expect(CAL_SRC).toMatch(
      /data-testid=\{`schedule-card-customer-static-\$\{j\.id\}`\}/,
    );
  });

  it("CalendarSchedule.jsx: pre-existing directions-button testid "
     + "preserved (non-admin UX unchanged)", () => {
    expect(CAL_SRC).toMatch(
      /data-testid=\{`schedule-card-\$\{j\.id\}-customer-name-directions`\}/,
    );
  });
});


describe("SCHEDULE-CUSTOMER-CLICKTHROUGH · CustomerLink primitive "
         + "behaviour (the exact instance the schedule uses)", () => {
  it("renders an anchor to /customers/<id> when customerId present "
     + "AND surfaces the override data-testid via spread", () => {
    render(
      <MemoryRouter>
        <CustomerLink
          customerId="cust-123"
          name="Larry Lead"
          data-testid="schedule-card-customer-link-job-abc"
        />
      </MemoryRouter>,
    );
    const link = screen.getByTestId("schedule-card-customer-link-job-abc");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("/customers/cust-123");
    expect(link.textContent).toContain("Larry Lead");
  });

  it("renders a plain span (no anchor) when customerId is missing — "
     + "'orphan' customer rows stay un-navigable even for admins",
    () => {
    render(
      <MemoryRouter>
        <CustomerLink
          customerId=""
          name="Orphan Customer"
          data-testid="schedule-card-customer-link-job-abc"
        />
      </MemoryRouter>,
    );
    const el = screen.getByTestId("schedule-card-customer-link-job-abc");
    expect(el.tagName).toBe("SPAN");
    expect(el.getAttribute("href")).toBeNull();
    expect(el.getAttribute("data-invalid")).toBe("true");
  });

  it("click stopPropagation prevents card-level handlers from "
     + "firing — schedule card's own onClick never double-fires",
    () => {
    const cardClick = vi.fn();
    render(
      <MemoryRouter>
        <div onClick={cardClick} data-testid="outer-card">
          <CustomerLink
            customerId="cust-xyz"
            name="Carla"
            data-testid="schedule-card-customer-link-job-xyz"
          />
        </div>
      </MemoryRouter>,
    );
    const link = screen.getByTestId("schedule-card-customer-link-job-xyz");
    link.click();
    expect(cardClick).not.toHaveBeenCalled();
  });
});
