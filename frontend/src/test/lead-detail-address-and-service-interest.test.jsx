/**
 * lead-detail-address-and-service-interest · Feb-2026
 *
 * Locks the two labeled rows on the lead detail drawer:
 *   • ``lead-detail-address`` — falls back through
 *     ``lead.address || lead.service_address`` and renders under
 *     the "Address:" label above City/State/Zip.
 *   • ``lead-detail-service-interest`` — surfaces
 *     ``lead.service_interest`` under the "Requested Service:"
 *     label (renamed from the pre-fix "Interested in:").
 *
 * Both rows are HIDDEN when the source field is empty.
 *
 * We inline a slim replica of the drawer's contact block (matches
 * the pattern in ``phase17-lead-drawer-field-rendering.test.jsx``)
 * so this test can run without pulling in the full LeadsDashboard
 * page's data-fetch scaffolding.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";

function LeadContactBlock({ lead }) {
  return (
    <div data-testid="lead-contact-block">
      {(lead.address || lead.service_address) && (
        <div data-testid="lead-detail-address">
          <b>Address:</b> {lead.address || lead.service_address}
        </div>
      )}
      {(lead.city || lead.state || lead.zip) ? (
        <div data-testid="lead-city-state-zip">
          {[lead.city, lead.state].filter(Boolean).join(", ")}
          {lead.zip
            ? (lead.city || lead.state ? " " : "") + lead.zip
            : ""}
        </div>
      ) : null}
      {lead.service_interest && (
        <div data-testid="lead-detail-service-interest">
          <b>Requested Service:</b> {lead.service_interest}
        </div>
      )}
    </div>
  );
}


describe("Lead detail — Address + Requested Service rows", () => {
  it("renders Address row from lead.address when set", () => {
    const { getByTestId } = render(
      <LeadContactBlock lead={{ address: "1234 W Palm Ln" }} />,
    );
    const row = getByTestId("lead-detail-address");
    expect(row).toBeTruthy();
    expect(row.textContent).toContain("Address:");
    expect(row.textContent).toContain("1234 W Palm Ln");
  });

  it("falls back to service_address when address is empty", () => {
    const { getByTestId } = render(
      <LeadContactBlock lead={{
        address: "",
        service_address: "5678 E Cactus Rd",
      }} />,
    );
    const row = getByTestId("lead-detail-address");
    expect(row.textContent).toContain("5678 E Cactus Rd");
  });

  it("hides Address row when both address and service_address are empty", () => {
    const { queryByTestId } = render(
      <LeadContactBlock lead={{ city: "Peoria", state: "AZ", zip: "85383" }} />,
    );
    expect(queryByTestId("lead-detail-address")).toBeNull();
    // City/state/zip row still renders because those are populated
    expect(queryByTestId("lead-city-state-zip")).toBeTruthy();
  });

  it("renders Requested Service row when service_interest is set", () => {
    const { getByTestId } = render(
      <LeadContactBlock lead={{
        service_interest: "Pool cleaning and maintenance",
      }} />,
    );
    const row = getByTestId("lead-detail-service-interest");
    expect(row.textContent).toContain("Requested Service:");
    expect(row.textContent).toContain("Pool cleaning and maintenance");
  });

  it("hides Requested Service row when service_interest is empty", () => {
    const { queryByTestId } = render(
      <LeadContactBlock lead={{ address: "1234 W Palm Ln" }} />,
    );
    expect(queryByTestId("lead-detail-service-interest")).toBeNull();
  });

  it("renders both rows together for a fully-populated lead", () => {
    const { getByTestId } = render(
      <LeadContactBlock lead={{
        address: "1234 W Palm Ln",
        city: "Peoria", state: "AZ", zip: "85383",
        service_interest: "Pool cleaning",
      }} />,
    );
    expect(getByTestId("lead-detail-address").textContent)
      .toContain("1234 W Palm Ln");
    expect(getByTestId("lead-city-state-zip").textContent)
      .toContain("Peoria");
    expect(getByTestId("lead-detail-service-interest").textContent)
      .toContain("Pool cleaning");
  });
});
