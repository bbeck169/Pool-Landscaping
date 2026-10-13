/**
 * Feb-2026 · PDF-import customer-match ladder — vitest coverage
 * for the preview-surface chips + reject-fuzzy affordance.
 *
 * Companion to the backend ladder in
 * ``backend/services/imports/customer_match_ladder.py`` and the
 * dry-run classifier at ``backend/services/imports/pdf_commit.py
 * ::classify_pending_for_preview``.  7 cases per dispatch spec:
 *
 *   1. Active-match chip renders green with "(Active)" label.
 *   2. Inactive-match chip renders amber with "(Inactive)" label +
 *      explanatory tooltip-adjacent copy.
 *   3. Muted-match chip renders amber with "(Muted)" label.
 *   4. Fuzzy-match chip renders amber with distance in label +
 *      "Reject match" link.
 *   5. Clicking "Reject match" flips row to override state locally
 *      (toggles the chip's visual rejection + flips the button
 *      copy to "Undo reject").
 *   6. Banner count reads "N auto-create, M matched to existing"
 *      correctly.
 *   7. Admin's rejection reaches the commit payload via the
 *      ``customerMatchOverrides`` prop forwarded by
 *      ``WillAutoCreateCustomersBanner``.
 */
import React, { useState, useCallback } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { WillAutoCreateCustomersBanner }
  from "@/pages/admin/imports/PdfInvoiceImportPage";


// ═══════════════════════════════════════════════════════════════════
// Fixtures
// ═══════════════════════════════════════════════════════════════════
const _activeRow = {
  source_doc_index: 0,
  pending_customer_id: "p-active",
  extracted_name: "Joe Kail",
  match_status: "active",
  matched_customer_id: "cust-1",
  matched_customer_name: "Joe Kail",
  matched_customer_status: "active",
  match_method: "exact",
  match_confidence: 1.0,
  fuzzy_distance: null,
};
const _inactiveRow = {
  source_doc_index: 1,
  pending_customer_id: "p-inactive",
  extracted_name: "Jane Smith",
  match_status: "inactive",
  matched_customer_id: "cust-2",
  matched_customer_name: "Jane Smith",
  matched_customer_status: "inactive",
  match_method: "exact",
  match_confidence: 1.0,
  fuzzy_distance: null,
};
const _mutedRow = {
  source_doc_index: 2,
  pending_customer_id: "p-muted",
  extracted_name: "Carl Wu",
  match_status: "muted",
  matched_customer_id: "cust-3",
  matched_customer_name: "Carl Wu",
  matched_customer_status: "muted",
  match_method: "exact",
  match_confidence: 1.0,
  fuzzy_distance: null,
};
const _fuzzyRow = {
  source_doc_index: 3,
  pending_customer_id: "p-fuzzy",
  extracted_name: "Joe Kayl",
  match_status: "fuzzy_match",
  matched_customer_id: "cust-4",
  matched_customer_name: "Joe Kail",
  matched_customer_status: "active",
  match_method: "fuzzy",
  match_confidence: 0.67,
  fuzzy_distance: 1,
};


function _classificationFromRows(rows, {
  willAutoCount = 0,
} = {}) {
  return {
    will_auto_create: [],
    will_require_manual_review: [],
    will_match_existing: rows,
    summary: {
      will_auto_create_count: willAutoCount,
      manual_review_count: 0,
      will_match_existing_count: rows.length,
      match_breakdown: {
        active: rows.filter((r) => r.match_status === "active").length,
        inactive: rows.filter(
          (r) => r.match_status === "inactive",
        ).length,
        muted: rows.filter((r) => r.match_status === "muted").length,
        fuzzy: rows.filter((r) => r.match_method === "fuzzy").length,
      },
    },
  };
}


describe("Feb-2026 · PDF-import match-ladder preview chips", () => {
  it("1 · active match renders a green chip with (Active)", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f1"
        classification={_classificationFromRows([_activeRow])}
      />,
    );
    const chip = screen.getByTestId("pdf-import-match-chip-f1-0");
    expect(chip).toBeTruthy();
    expect(chip.getAttribute("data-match-status")).toBe("active");
    expect(chip.textContent).toContain("Matched: Joe Kail");
    expect(chip.textContent).toContain("(Active)");
    // Green palette on the active chip.
    const bg = chip.style.backgroundColor;
    expect(bg).toMatch(/220, 252, 231|#DCFCE7/i);
  });

  it("2 · inactive match renders amber with explanatory copy", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f2"
        classification={_classificationFromRows([_inactiveRow])}
      />,
    );
    const chip = screen.getByTestId("pdf-import-match-chip-f2-1");
    expect(chip.getAttribute("data-match-status")).toBe("inactive");
    expect(chip.textContent).toContain("Matched: Jane Smith");
    // Explanatory copy — operator sees exactly which customer
    // will receive the invoice.
    expect(chip.textContent).toContain(
      "(Inactive — will attach to this customer)",
    );
    const bg = chip.style.backgroundColor;
    expect(bg).toMatch(/254, 243, 199|#FEF3C7/i);
    // No "Reject match" affordance on exact-tier matches.
    expect(screen.queryByTestId(
      "pdf-import-reject-fuzzy-btn-f2-1",
    )).toBeNull();
  });

  it("3 · muted match renders amber with (Muted) label", () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f3"
        classification={_classificationFromRows([_mutedRow])}
      />,
    );
    const chip = screen.getByTestId("pdf-import-match-chip-f3-2");
    expect(chip.getAttribute("data-match-status")).toBe("muted");
    expect(chip.textContent).toContain(
      "(Muted — will attach to this customer)",
    );
  });

  it("4 · fuzzy match renders amber with distance + Reject link",
      () => {
    render(
      <WillAutoCreateCustomersBanner
        fileId="f4"
        classification={_classificationFromRows([_fuzzyRow])}
        onToggleRejectFuzzy={vi.fn()}
      />,
    );
    const chip = screen.getByTestId("pdf-import-match-chip-f4-3");
    expect(chip.getAttribute("data-match-status")).toBe("fuzzy_match");
    expect(chip.textContent).toContain("Matched: Joe Kail");
    expect(chip.textContent).toContain("(Fuzzy, distance 1)");
    // Reject-match affordance exists only on fuzzy chips.
    const btn = screen.getByTestId("pdf-import-reject-fuzzy-btn-f4-3");
    expect(btn.textContent).toBe("Reject match");
    // Distance tooltip hint lives on the chip.
    expect(chip.getAttribute("title")).toContain(
      "Levenshtein distance",
    );
  });

  it("5 · clicking Reject match flips chip to override state", () => {
    // Controlled wrapper that owns the override map so the chip
    // flips visually in response to the button click, mirroring
    // the parent ``PreviewSurface`` component wiring.
    function Harness() {
      const [overrides, setOverrides] = useState({});
      const onToggle = useCallback((pid) => {
        setOverrides((prev) => {
          const next = { ...(prev || {}) };
          if (next[pid] === "reject_fuzzy") delete next[pid];
          else next[pid] = "reject_fuzzy";
          return next;
        });
      }, []);
      return (
        <WillAutoCreateCustomersBanner
          fileId="f5"
          classification={_classificationFromRows([_fuzzyRow])}
          customerMatchOverrides={overrides}
          onToggleRejectFuzzy={onToggle}
        />
      );
    }
    render(<Harness />);
    const btn = screen.getByTestId("pdf-import-reject-fuzzy-btn-f5-3");
    expect(btn.textContent).toBe("Reject match");
    fireEvent.click(btn);
    const chip = screen.getByTestId("pdf-import-match-chip-f5-3");
    // Visual rejection: strike-through + opacity.
    expect(chip.style.textDecoration).toContain("line-through");
    // Button copy flips to the undo affordance.
    const btn2 = screen.getByTestId(
      "pdf-import-reject-fuzzy-btn-f5-3",
    );
    expect(btn2.textContent).toBe("Undo reject");
    // Clicking again clears the override.
    fireEvent.click(btn2);
    const chip3 = screen.getByTestId("pdf-import-match-chip-f5-3");
    // ``none`` or empty — jsdom normalises either way.
    expect(chip3.style.textDecoration === ""
            || chip3.style.textDecoration === "none").toBe(true);
  });

  it("6 · banner headline reads 'N auto-create, M matched to existing'",
      () => {
    const rows = [_activeRow, _inactiveRow, _mutedRow];
    render(
      <WillAutoCreateCustomersBanner
        fileId="f6"
        classification={_classificationFromRows(rows, {
          willAutoCount: 1,
        })}
      />,
    );
    const count = screen.getByTestId(
      "pdf-import-will-auto-create-count-f6",
    );
    expect(count.textContent).toContain("Will auto-create 1 customer");
    const matched = screen.getByTestId(
      "pdf-import-will-match-existing-count-f6",
    );
    expect(matched.textContent).toContain("3 matched to existing");
  });

  it("7 · reject override reaches the commit payload", () => {
    // Simulates the parent flow: PreviewSurface owns the override
    // state + passes it as ``customerMatchOverrides`` to
    // ``commitBatch``.  Here we assert that the toggled override
    // ends up in the parent's state container with the correct
    // key shape so the real commit call receives the right
    // ``customer_match_overrides`` payload.
    let latestOverrides = null;
    function Harness() {
      const [overrides, setOverrides] = useState({});
      latestOverrides = overrides;
      const onToggle = useCallback((pid) => {
        setOverrides((prev) => {
          const next = { ...(prev || {}) };
          if (next[pid] === "reject_fuzzy") delete next[pid];
          else next[pid] = "reject_fuzzy";
          return next;
        });
      }, []);
      return (
        <WillAutoCreateCustomersBanner
          fileId="f7"
          classification={_classificationFromRows([_fuzzyRow])}
          customerMatchOverrides={overrides}
          onToggleRejectFuzzy={onToggle}
        />
      );
    }
    render(<Harness />);
    expect(latestOverrides).toEqual({});
    fireEvent.click(
      screen.getByTestId("pdf-import-reject-fuzzy-btn-f7-3"),
    );
    // After the click, the override map has the pending id keyed
    // to "reject_fuzzy" — the exact shape ``commitBatch`` sends
    // as ``customer_match_overrides`` in the POST body.
    expect(latestOverrides).toEqual({"p-fuzzy": "reject_fuzzy"});
  });
});
