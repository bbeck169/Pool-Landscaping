/**
 * Feb-2026 · PDF Import Hub — auto-create customer from PDF
 * extraction vitests.
 *
 * Covers the four FE deliverables for the auto-create UX ticket:
 *
 *   1. Banner count reads from ``summary.will_auto_create_count``
 *      when present (falls back to raw array length for
 *      pre-upgrade response shapes).
 *   2. "Show details" expands to the candidate table with
 *      Name / Email / Phone / Address columns and a fields chip
 *      ("3 of 4 extracted"); missing fields render "—".
 *   3. Low-confidence rows get an amber "Resolve customer"
 *      button that is clickable (scroll-into-view affordance).
 *   4. Low-confidence rows are counted in the "need manual
 *      review" sub-badge.
 *
 * Component is a pure render — no network, no router.  Imported
 * directly from PdfInvoiceImportPage so the tests exercise the
 * production markup exactly.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import {
  WillAutoCreateCustomersBanner,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


function _row({
  source_doc_index = 0,
  pending_customer_id = "pid-" + source_doc_index,
  extracted_name = "Joe Kail",
  extracted_address = "123 Pine Dr",
  extracted_phone = "555-1234",
  email = "joe@example.com",
  dedup_group_id = "grp-a",
  fields_extracted = ["name", "email", "phone", "mailing_address"],
  fields_missing = [],
  ...rest
} = {}) {
  return {
    source_doc_index,
    pending_customer_id,
    extracted_name,
    extracted_address,
    extracted_phone,
    dedup_group_id,
    fields_extracted,
    fields_missing,
    auto_create_candidate: {
      name: extracted_name,
      email,
      phone: extracted_phone,
      mailing_address: extracted_address
        ? { street: extracted_address, city: null, state: null, zip: null }
        : null,
      service_category: "both",
    },
    ...rest,
  };
}


describe("PdfImport · AutoCreate banner · summary-driven count", () => {
  it("reads the count from summary.will_auto_create_count when present", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f1"
        classification={{
          will_auto_create: [_row({ source_doc_index: 0 }),
                              _row({ source_doc_index: 1 })],
          will_require_manual_review: [],
          summary: {
            will_auto_create_count: 1,  // 2 rows, 1 dedup group
            manual_review_count: 0,
          },
        }}
      />,
    );
    expect(
      screen.getByTestId("pdf-import-will-auto-create-count-f1").textContent,
    ).toMatch(/Will auto-create 1 customer on commit/);
  });

  it("falls back to array length when summary absent (BC)", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f2"
        classification={{
          will_auto_create: [_row({ source_doc_index: 0 }),
                              _row({ source_doc_index: 1,
                                      dedup_group_id: "grp-b" })],
          will_require_manual_review: [],
          // no summary -> array length should drive
        }}
      />,
    );
    expect(
      screen.getByTestId("pdf-import-will-auto-create-count-f2").textContent,
    ).toMatch(/Will auto-create 2 customers on commit/);
  });
});


describe("PdfImport · AutoCreate banner · Show details table", () => {
  it("renders Name / Email / Phone / Address columns + fields chip", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f3"
        classification={{
          will_auto_create: [_row({
            source_doc_index: 7,
            extracted_name: "Joe Kail",
            email: "joe@example.com",
            extracted_phone: "555-1234",
            extracted_address: "123 Pine Dr",
            fields_extracted: ["name", "email", "phone", "mailing_address"],
            fields_missing: [],
          })],
          will_require_manual_review: [],
          summary: {
            will_auto_create_count: 1, manual_review_count: 0,
          },
        }}
      />,
    );
    const tbl = screen.getByTestId("pdf-import-auto-create-table-f3");
    expect(tbl.textContent).toContain("Name");
    expect(tbl.textContent).toContain("Email");
    expect(tbl.textContent).toContain("Phone");
    expect(tbl.textContent).toContain("Address");
    expect(tbl.textContent).toContain("Joe Kail");
    expect(tbl.textContent).toContain("joe@example.com");
    expect(tbl.textContent).toContain("555-1234");
    expect(tbl.textContent).toContain("123 Pine Dr");
    const chip = screen.getByTestId(
      "pdf-import-will-auto-create-fields-chip-f3-7",
    );
    expect(chip.textContent).toMatch(/4 of 4 extracted/);
  });

  it("renders missing fields as — and chip shows partial coverage", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f4"
        classification={{
          will_auto_create: [_row({
            source_doc_index: 2,
            email: null,
            extracted_address: null,
            fields_extracted: ["name", "phone"],
            fields_missing: ["email", "mailing_address"],
          })],
          will_require_manual_review: [],
          summary: {
            will_auto_create_count: 1, manual_review_count: 0,
          },
        }}
      />,
    );
    const tbl = screen.getByTestId("pdf-import-auto-create-table-f4");
    // Two em-dashes — one for Email, one for Address.
    const dashes = tbl.querySelectorAll("[title='Not extracted from PDF']");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    const chip = screen.getByTestId(
      "pdf-import-will-auto-create-fields-chip-f4-2",
    );
    expect(chip.textContent).toMatch(/2 of 4 extracted/);
    expect(chip.getAttribute("title")).toMatch(/Missing: email, mailing_address/);
  });

  it("collapses two rows with same dedup_group_id into one table row", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f5"
        classification={{
          will_auto_create: [
            _row({ source_doc_index: 0, dedup_group_id: "grp-shared" }),
            _row({ source_doc_index: 1, dedup_group_id: "grp-shared",
                    pending_customer_id: "pid-dupe" }),
          ],
          will_require_manual_review: [],
          summary: {
            will_auto_create_count: 1, manual_review_count: 0,
          },
        }}
      />,
    );
    const items = screen.getAllByTestId(
      "pdf-import-will-auto-create-item-f5",
    );
    expect(items).toHaveLength(1);
  });
});


describe("PdfImport · AutoCreate banner · low-confidence resolution", () => {
  it("renders amber Resolve customer button for low-confidence rows", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f6"
        classification={{
          will_auto_create: [],
          will_require_manual_review: [{
            source_doc_index: 3,
            pending_customer_id: "pid-lowconf",
            extracted_name: "346",
            reason: "customer_extraction_confidence_low",
          }],
          summary: {
            will_auto_create_count: 0, manual_review_count: 1,
          },
        }}
      />,
    );
    const btn = screen.getByTestId(
      "pdf-import-low-confidence-resolve-btn-f6-3",
    );
    expect(btn).toBeInTheDocument();
    expect(btn.textContent).toMatch(/Resolve customer/);
    expect(
      screen.getByTestId("pdf-import-low-confidence-row-f6-3").textContent,
    ).toContain("looks like a doc number");
    // Clicking should NOT throw even without a matching tile in the DOM.
    fireEvent.click(btn);
  });

  it("counts manual_review rows in the need-manual-review chip", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f7"
        classification={{
          will_auto_create: [_row({ source_doc_index: 0 })],
          will_require_manual_review: [
            {
              source_doc_index: 5,
              pending_customer_id: "pid-lowconf",
              reason: "customer_extraction_confidence_low",
            },
            {
              source_doc_index: 6,
              pending_customer_id: "pid-blank",
              reason: "no_identifying_info",
            },
          ],
          summary: {
            will_auto_create_count: 1, manual_review_count: 2,
          },
        }}
      />,
    );
    const chip = screen.getByTestId("pdf-import-manual-review-count-f7");
    expect(chip.textContent).toMatch(/2 need manual review/);
  });

  it("hides low-confidence section when no low-conf rows exist", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f8"
        classification={{
          will_auto_create: [_row({ source_doc_index: 0 })],
          will_require_manual_review: [{
            source_doc_index: 9,
            pending_customer_id: "pid-blank",
            reason: "no_identifying_info",
          }],
          summary: {
            will_auto_create_count: 1, manual_review_count: 1,
          },
        }}
      />,
    );
    expect(
      screen.queryByTestId("pdf-import-low-confidence-section-f8"),
    ).not.toBeInTheDocument();
  });
});


describe("PdfImport · AutoCreate banner · empty state", () => {
  it("renders nothing when classification is missing", () => {
    const { container } = render(
      <WillAutoCreateCustomersBanner fileId="f9" classification={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when both buckets are empty", () => {
    const { container } = render(
      <WillAutoCreateCustomersBanner
        fileId="f10"
        classification={{
          will_auto_create: [],
          will_require_manual_review: [],
          summary: { will_auto_create_count: 0, manual_review_count: 0 },
        }}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
