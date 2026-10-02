/**
 * Jobs Overhaul · Phase 3a · JobDetail inline Customer swap.
 *
 * Isolated-harness pattern (mirrors ``test/JobDetail.delete.test.jsx``)
 * — mounts the Customer-swap widget in a tiny wrapper. The real
 * JobDetail wiring is pinned via source-inspection assertions at
 * the bottom of the file.
 *
 * Behaviour contract pinned here:
 *   1. Read mode renders ``<CustomerLink>`` + an "edit" button for
 *      non-tech non-customer roles.
 *   2. Click "edit" → ``<CustomerCombobox>`` renders in place with
 *      the current customer_id preselected.
 *   3. Selecting a NEW id fires ``onPatch({customer_id: newId})``
 *      exactly once + collapses the editor.
 *   4. Selecting the SAME id (or empty) collapses WITHOUT patching.
 *   5. Cancel button collapses WITHOUT patching.
 *   6. On a 4xx/5xx roundtrip (saveInline → false), the editor
 *      stays open AND the parent's customer_name denorm is NOT
 *      optimistically kept — mirrors the rollback contract.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../JobDetail.jsx"), "utf8",
);

// Mock the real CustomerCombobox so this test doesn't drag in the
// Popover + cmdk + Radix mount graph. Shape mirrors the real
// contract: calls ``onChange(id)`` when a row is picked.
vi.mock("@/components/customers/CustomerCombobox", () => ({
  CustomerCombobox: ({ customers = [], value, onChange, testid }) => (
    <select
      data-testid={testid}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">— pick —</option>
      {customers.map((c) => (
        <option key={c.id} value={c.id}>{c.name}</option>
      ))}
    </select>
  ),
  default: ({ customers = [], value, onChange, testid }) => (
    <select
      data-testid={testid}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">— pick —</option>
      {customers.map((c) => (
        <option key={c.id} value={c.id}>{c.name}</option>
      ))}
    </select>
  ),
}));

import { CustomerCombobox } from "@/components/customers/CustomerCombobox";


// Minimal harness mirroring the JobDetail swap block.
function CustomerFieldHarness({
  initialCustomerId = "cust-old",
  initialCustomerName = "Old Customer Co.",
  customerOptions = [
    { id: "cust-old", name: "Old Customer Co." },
    { id: "cust-new", name: "New Customer LLC" },
  ],
  role = "admin",
  saveInline = async () => true,
}) {
  const [editing, setEditing] = React.useState(false);
  const [customerId, setCustomerId] = React.useState(initialCustomerId);
  const [customerName, setCustomerName] = React.useState(initialCustomerName);
  const isCustomer = role === "customer";
  const isTech = role === "technician";

  return (
    <div>
      {editing ? (
        <span>
          <CustomerCombobox
            customers={customerOptions}
            value={customerId}
            onChange={async (newCid) => {
              if (!newCid || newCid === customerId) {
                setEditing(false);
                return;
              }
              const picked = customerOptions.find((c) => c.id === newCid);
              const ok = await saveInline(
                { customer_id: newCid },
                {
                  customer_id: newCid,
                  customer_name: picked ? picked.name : "",
                },
              );
              if (ok) {
                setCustomerId(newCid);
                setCustomerName(picked ? picked.name : "");
                setEditing(false);
              }
            }}
            testid="jd-customer-combobox"
          />
          <button
            type="button" onClick={() => setEditing(false)}
            data-testid="jd-customer-edit-cancel"
          >
            cancel
          </button>
        </span>
      ) : (
        <>
          <span data-testid="job-detail-customer-name">{customerName}</span>
          {!isCustomer && !isTech ? (
            <button
              type="button" onClick={() => setEditing(true)}
              data-testid="jd-customer-edit-btn"
            >
              edit
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}


beforeEach(() => { cleanup(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });


describe("JobDetail · Phase 3a · Customer inline edit", () => {
  it("read mode renders customer name + edit button for admin", () => {
    render(<CustomerFieldHarness role="admin" />);
    expect(screen.getByTestId("job-detail-customer-name"))
      .toHaveTextContent("Old Customer Co.");
    expect(screen.getByTestId("jd-customer-edit-btn")).toBeInTheDocument();
  });

  it("edit button is HIDDEN for technician role", () => {
    render(<CustomerFieldHarness role="technician" />);
    expect(screen.queryByTestId("jd-customer-edit-btn")).toBeNull();
  });

  it("edit button is HIDDEN for customer role", () => {
    render(<CustomerFieldHarness role="customer" />);
    expect(screen.queryByTestId("jd-customer-edit-btn")).toBeNull();
  });

  it("click edit → combobox mounts preselected with current id", () => {
    render(<CustomerFieldHarness role="admin" />);
    fireEvent.click(screen.getByTestId("jd-customer-edit-btn"));
    const combo = screen.getByTestId("jd-customer-combobox");
    expect(combo.value).toBe("cust-old");
  });

  it("selecting a NEW id patches customer_id + collapses editor", async () => {
    const saveInline = vi.fn(async () => true);
    render(<CustomerFieldHarness role="admin" saveInline={saveInline} />);
    fireEvent.click(screen.getByTestId("jd-customer-edit-btn"));
    fireEvent.change(screen.getByTestId("jd-customer-combobox"),
                      { target: { value: "cust-new" } });
    await waitFor(() => expect(saveInline).toHaveBeenCalledTimes(1));
    const [patch, optimistic] = saveInline.mock.calls[0];
    expect(patch).toEqual({ customer_id: "cust-new" });
    expect(optimistic).toMatchObject({
      customer_id: "cust-new",
      customer_name: "New Customer LLC",
    });
    await waitFor(() =>
      expect(screen.queryByTestId("jd-customer-combobox")).toBeNull(),
    );
    expect(screen.getByTestId("job-detail-customer-name"))
      .toHaveTextContent("New Customer LLC");
  });

  it("selecting the SAME id collapses WITHOUT patching", async () => {
    const saveInline = vi.fn(async () => true);
    render(<CustomerFieldHarness role="admin" saveInline={saveInline} />);
    fireEvent.click(screen.getByTestId("jd-customer-edit-btn"));
    fireEvent.change(screen.getByTestId("jd-customer-combobox"),
                      { target: { value: "cust-old" } });
    await waitFor(() =>
      expect(screen.queryByTestId("jd-customer-combobox")).toBeNull(),
    );
    expect(saveInline).not.toHaveBeenCalled();
  });

  it("cancel button collapses WITHOUT patching", () => {
    const saveInline = vi.fn(async () => true);
    render(<CustomerFieldHarness role="admin" saveInline={saveInline} />);
    fireEvent.click(screen.getByTestId("jd-customer-edit-btn"));
    fireEvent.click(screen.getByTestId("jd-customer-edit-cancel"));
    expect(saveInline).not.toHaveBeenCalled();
    expect(screen.queryByTestId("jd-customer-combobox")).toBeNull();
    // Original customer_name preserved.
    expect(screen.getByTestId("job-detail-customer-name"))
      .toHaveTextContent("Old Customer Co.");
  });

  it("failed save keeps the editor open AND does NOT mutate customer_name", async () => {
    const saveInline = vi.fn(async () => false);
    render(<CustomerFieldHarness role="admin" saveInline={saveInline} />);
    fireEvent.click(screen.getByTestId("jd-customer-edit-btn"));
    fireEvent.change(screen.getByTestId("jd-customer-combobox"),
                      { target: { value: "cust-new" } });
    await waitFor(() => expect(saveInline).toHaveBeenCalledTimes(1));
    // Editor stays open on failure.
    expect(screen.getByTestId("jd-customer-combobox")).toBeInTheDocument();
    // Cancelling now should reveal the ORIGINAL customer_name,
    // proving the harness did NOT optimistically persist the
    // picked customer's name (the rollback contract).
    fireEvent.click(screen.getByTestId("jd-customer-edit-cancel"));
    expect(screen.getByTestId("job-detail-customer-name"))
      .toHaveTextContent("Old Customer Co.");
  });
});


// ─────────── Source-inspection contract on JobDetail.jsx ─────────
describe("JobDetail · Phase 3a · Customer swap source contract", () => {
  it("CustomerCombobox is imported from the shared JobNew path", () => {
    expect(SRC).toMatch(
      /import\s*\{\s*CustomerCombobox\s*\}\s*from\s*["']@\/components\/customers\/CustomerCombobox["']/,
    );
  });

  it("customerEditing state + /customers?is_active=true fetch wiring", () => {
    expect(SRC).toMatch(
      /const\s*\[customerEditing,\s*setCustomerEditing\]\s*=\s*useState\(false\)/,
    );
    expect(SRC).toMatch(/api\.get\("\/customers\?is_active=true"\)/);
    expect(SRC).toMatch(/if\s*\(!customerEditing\)\s*return;/);
  });

  it("read mode preserves CustomerLink + edit button is gated on !isCustomer && !isTech", () => {
    expect(SRC).toMatch(
      /<CustomerLink[\s\S]{0,400}data-testid="job-detail-customer-name"/,
    );
    expect(SRC).toMatch(
      /!isCustomer\s*&&\s*!isTech[\s\S]{0,400}data-testid="jd-customer-edit-btn"/,
    );
  });

  it("edit mode wires onChange → saveInline with customer_id + optimistic denorm", () => {
    expect(SRC).toMatch(
      /saveInline\(\s*\{\s*customer_id:\s*newCid\s*\},[\s\S]{0,500}customer_name:\s*picked\s*\?\s*picked\.name/,
    );
    // On rollback (ok === false), the editor stays open.
    expect(SRC).toMatch(/if\s*\(ok\)\s*\{\s*setCustomerEditing\(false\)/);
  });

  it("optimistic payload clears stale property_id + address (matches backend $unset)", () => {
    expect(SRC).toMatch(/property_id:\s*undefined/);
    expect(SRC).toMatch(/address:\s*""/);
  });
});
