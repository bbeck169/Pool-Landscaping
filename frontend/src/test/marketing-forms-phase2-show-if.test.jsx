/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53) ·
 * ``show_if`` conditional-logic FE coverage.
 *
 * Three layers under test (matches the BE pytest layer breakdown):
 *
 *   §1 · Shared evaluator (``src/lib/formShowIf.js``) — pure helpers
 *        exercised directly.  Mirror of the BE's
 *        ``_is_field_visible`` so admin preview, widget, and server
 *        agree on every visibility decision.
 *   §2 · Admin builder UI (``ShowIfEditor`` named-export from
 *        MarketingFormsPage) — collapsible panel round-trip:
 *        toggle open → set parent/op/value → upstream onChange
 *        emits the correct ``show_if`` dict.
 *   §3 · Payload-strip helper (``stripHiddenAnswers``) — regression
 *        guard that hidden-field values do NOT ride the submission
 *        payload (parity with the BE's strip-before-persist).
 */
import React from "react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import {
  coerceForCompare,
  isFieldVisible,
  stripHiddenAnswers,
} from "@/lib/formShowIf";
import { ShowIfEditor } from "@/pages/marketing/MarketingFormsPage";


beforeEach(() => {
  cleanup();
});


// ═══════════════════════════════════════════════════════════════
// §1 · Shared evaluator (pure helpers)
// ═══════════════════════════════════════════════════════════════
describe("formShowIf · pure evaluator · TD-53", () => {
  it("coerceForCompare strips strings + collapses empty to null", () => {
    expect(coerceForCompare("  pool  ")).toBe("pool");
    expect(coerceForCompare("")).toBe(null);
    expect(coerceForCompare("   ")).toBe(null);
    expect(coerceForCompare(null)).toBe(null);
    expect(coerceForCompare(undefined)).toBe(null);
    // Non-strings pass through.
    expect(coerceForCompare(42)).toBe(42);
    expect(coerceForCompare(false)).toBe(false);
    expect(coerceForCompare(["a"])).toEqual(["a"]);
  });

  it("isFieldVisible · null show_if → always visible", () => {
    const field = { id: "x", name: "x", show_if: null };
    expect(isFieldVisible(field, {}, {})).toBe(true);
    expect(isFieldVisible(field, { x: "anything" }, { x: field })).toBe(true);
  });

  it("isFieldVisible · eq / neq operators", () => {
    const parent = { id: "svc", name: "svc" };
    const child = {
      id: "pool_size", name: "pool_size",
      show_if: { field_id: "svc", operator: "eq", value: "pool" },
    };
    const byId = { svc: parent, pool_size: child };
    expect(isFieldVisible(child, { svc: "pool" }, byId)).toBe(true);
    expect(isFieldVisible(child, { svc: "landscape" }, byId)).toBe(false);

    const child2 = {
      ...child,
      show_if: { field_id: "svc", operator: "neq", value: "pool" },
    };
    expect(isFieldVisible(child2, { svc: "pool" }, byId)).toBe(false);
    expect(isFieldVisible(child2, { svc: "landscape" }, byId)).toBe(true);
  });

  it("isFieldVisible · contains operator (list parents + string parents)", () => {
    const parent = { id: "svc", name: "svc" };
    const child = {
      id: "pool_size", name: "pool_size",
      show_if: { field_id: "svc", operator: "contains", value: "pool" },
    };
    const byId = { svc: parent, pool_size: child };
    // List parent — value must be a member.
    expect(isFieldVisible(child, { svc: ["pool", "spa"] }, byId)).toBe(true);
    expect(isFieldVisible(child, { svc: ["spa", "patio"] }, byId)).toBe(false);
    // String parent — substring match.
    expect(isFieldVisible(child, { svc: "swimming-pool-ONLY" }, byId)).toBe(true);
    expect(isFieldVisible(child, { svc: "landscape-work" }, byId)).toBe(false);
    // Numeric parent + string target → defensive false.
    expect(isFieldVisible(child, { svc: 42 }, byId)).toBe(false);
  });

  it("isFieldVisible · empty-string parent coerces to null for eq", () => {
    const parent = { id: "svc", name: "svc" };
    const child = {
      id: "pool_size", name: "pool_size",
      show_if: { field_id: "svc", operator: "eq", value: null },
    };
    const byId = { svc: parent, pool_size: child };
    expect(isFieldVisible(child, { svc: "" }, byId)).toBe(true);
    expect(isFieldVisible(child, { svc: "  " }, byId)).toBe(true);
    expect(isFieldVisible(child, {}, byId)).toBe(true);
    expect(isFieldVisible(child, { svc: "pool" }, byId)).toBe(false);
  });

  it("isFieldVisible · dangling parent ref → fails OPEN (visible)", () => {
    // Save-time validator rejects this shape, but defend pre-TD-53
    // forms + manual DB edits.
    const child = {
      id: "pool_size", name: "pool_size",
      show_if: { field_id: "missing", operator: "eq", value: "pool" },
    };
    expect(isFieldVisible(child, {}, {})).toBe(true);
  });
});


// ═══════════════════════════════════════════════════════════════
// §2 · Admin builder UI (ShowIfEditor collapsible)
// ═══════════════════════════════════════════════════════════════
describe("ShowIfEditor · builder round-trip · TD-53", () => {
  const COLORS = { muted: "#64748B", border: "#E2E8F0" };
  const SIBLINGS = [
    { id: "svc", name: "svc", label: "Service", type: "select" },
    { id: "contact_pref", name: "contact_pref",
      label: "Contact Preference", type: "radio" },
  ];

  it("starts collapsed when field has no show_if", () => {
    const onChange = vi.fn();
    render(<ShowIfEditor
      field={{ id: "pool_size", name: "pool_size" }}
      idx={2} siblings={SIBLINGS} onChange={onChange} colors={COLORS}
    />);
    // Toggle visible, panel hidden.
    expect(screen.getByTestId("form-field-show-if-toggle-2")).toBeTruthy();
    expect(screen.queryByTestId("form-field-show-if-panel-2")).toBeNull();
    // No "conditional" badge.
    expect(screen.queryByTestId("form-field-show-if-badge-2")).toBeNull();
  });

  it("starts OPEN when field already has show_if (loading existing form)", () => {
    render(<ShowIfEditor
      field={{
        id: "pool_size", name: "pool_size",
        show_if: { field_id: "svc", operator: "eq", value: "pool" },
      }}
      idx={2} siblings={SIBLINGS} onChange={vi.fn()} colors={COLORS}
    />);
    expect(screen.getByTestId("form-field-show-if-panel-2")).toBeTruthy();
    expect(screen.getByTestId("form-field-show-if-badge-2")).toBeTruthy();
    expect(screen.getByTestId("form-field-show-if-parent-2").value).toBe("svc");
    expect(screen.getByTestId("form-field-show-if-operator-2").value).toBe("eq");
    expect(screen.getByTestId("form-field-show-if-value-2").value).toBe("pool");
  });

  it("emits a show_if dict when the parent + value are set", () => {
    const onChange = vi.fn();
    const Harness = ({ initial }) => {
      // Mimic the parent's updateField flow — forward partial
      // updates into local state so ShowIfEditor sees the latest
      // field prop between user actions.
      const [f, setF] = React.useState(initial);
      return (
        <ShowIfEditor
          field={f}
          idx={2}
          siblings={SIBLINGS}
          onChange={(partial) => {
            onChange(partial);
            setF((prev) => ({ ...prev, ...partial }));
          }}
          colors={COLORS}
        />
      );
    };
    render(<Harness initial={{ id: "pool_size", name: "pool_size" }} />);
    // Open the panel.
    fireEvent.click(screen.getByTestId("form-field-show-if-toggle-2"));
    // Pick a parent field — first onChange carries the full rule.
    fireEvent.change(screen.getByTestId("form-field-show-if-parent-2"), {
      target: { value: "svc" },
    });
    expect(onChange).toHaveBeenCalledWith({
      show_if: { field_id: "svc", operator: "eq", value: "" },
    });
    // Set a value — second onChange carries the updated value AND
    // the previously-set field_id (parent re-rendered with the
    // merged ``show_if`` so the editor's local state is correct).
    fireEvent.change(screen.getByTestId("form-field-show-if-value-2"), {
      target: { value: "pool" },
    });
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall.show_if).toEqual({
      field_id: "svc", operator: "eq", value: "pool",
    });
  });

  it("clearing the parent dropdown nullifies the rule (remove show_if)", () => {
    const onChange = vi.fn();
    render(<ShowIfEditor
      field={{
        id: "pool_size", name: "pool_size",
        show_if: { field_id: "svc", operator: "eq", value: "pool" },
      }}
      idx={2} siblings={SIBLINGS} onChange={onChange} colors={COLORS}
    />);
    fireEvent.change(screen.getByTestId("form-field-show-if-parent-2"), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenCalledWith({ show_if: null });
  });
});


// ═══════════════════════════════════════════════════════════════
// §3 · Payload-strip helper (submit-time hidden-value removal)
// ═══════════════════════════════════════════════════════════════
describe("stripHiddenAnswers · submit-time hidden-field removal · TD-53", () => {
  it("removes hidden-field values from the submission payload", () => {
    const fields = [
      { id: "svc", name: "svc" },
      { id: "pool_size", name: "pool_size",
        show_if: { field_id: "svc", operator: "eq", value: "pool" } },
    ];
    const answers = {
      svc: "landscape",
      pool_size: "20x40 (stale from before user switched)",
    };
    const stripped = stripHiddenAnswers(fields, answers);
    expect(stripped.svc).toBe("landscape");
    expect("pool_size" in stripped).toBe(false);
  });

  it("preserves visible fields when the rule evaluates true", () => {
    const fields = [
      { id: "svc", name: "svc" },
      { id: "pool_size", name: "pool_size",
        show_if: { field_id: "svc", operator: "eq", value: "pool" } },
    ];
    const stripped = stripHiddenAnswers(fields, {
      svc: "pool", pool_size: "20x40",
    });
    expect(stripped).toEqual({ svc: "pool", pool_size: "20x40" });
  });

  it("legacy forms (no show_if on any field) round-trip byte-identical", () => {
    const fields = [
      { id: "name", name: "name" },
      { id: "email", name: "email" },
    ];
    const answers = { name: "Jane", email: "j@x.com" };
    const stripped = stripHiddenAnswers(fields, answers);
    expect(stripped).toEqual(answers);
  });

  it("doesn't crash on empty / null inputs", () => {
    expect(stripHiddenAnswers([], { a: 1 })).toEqual({ a: 1 });
    expect(stripHiddenAnswers(null, { a: 1 })).toEqual({ a: 1 });
    expect(stripHiddenAnswers([{ id: "x", name: "x" }], null)).toEqual({});
  });
});
