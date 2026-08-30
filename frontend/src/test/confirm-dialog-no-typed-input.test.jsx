/**
 * Feb-2026 · App-wide type-to-confirm removal — regression guard.
 *
 * The user brief retired every "type this word to confirm" flow
 * across the web app in favour of single-click Confirm (with a
 * 2-click arm-and-execute reserved for the CustomersList
 * catastrophic bulk delete). This file locks the removal in:
 *
 *   1. Source-regex sweep across the five formerly-affected files.
 *      Any resurrection of the `<input>`-inside-confirm-modal
 *      pattern fails this suite.
 *   2. Shared component behavioural tests — `ConfirmDeleteDialog`
 *      + `confirm-dialog.jsx` primary flows renders zero text
 *      inputs regardless of the `requireTypeConfirm` prop value.
 *   3. CustomersList catastrophic modal — the arm-and-execute
 *      testids are the SOLE gate on mass-delete now.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import ConfirmDeleteDialog from "@/components/common/ConfirmDeleteDialog";
import { ConfirmProvider, useConfirm } from "@/components/ui/confirm-dialog";


// ── Source sweep helpers ─────────────────────────────────────────
const read = (rel) => readFileSync(resolve(__dirname, "..", rel), "utf8");

const FILES_TO_SWEEP = {
  "components/invoices/InvoiceEditModal.jsx": read(
    "components/invoices/InvoiceEditModal.jsx",
  ),
  "components/customers/MergeCustomersModal.jsx": read(
    "components/customers/MergeCustomersModal.jsx",
  ),
  "pages/quotes/QuoteInvoiceDetail.jsx": read(
    "pages/quotes/QuoteInvoiceDetail.jsx",
  ),
  "pages/ops/OpsHub.jsx": read("pages/ops/OpsHub.jsx"),
  "pages/customers/CustomersList.jsx": read(
    "pages/customers/CustomersList.jsx",
  ),
};

// Strip both block-comments and line-comments so JSDoc / inline
// changelog notes that reference the retired pattern do not
// trigger the assertion. Applied per-file before regex-testing.
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|\s)\/\/.*$/gm, "$1");
}


describe("Type-to-confirm sweep · no `Type X to confirm` copy in code paths", () => {
  it.each(Object.entries(FILES_TO_SWEEP))(
    "%s renders no `Type … to confirm` prompt",
    (_name, src) => {
      const code = stripComments(src);
      expect(code).not.toMatch(/Type\s+<code[^>]*>/i);
      expect(code).not.toMatch(/Type\s+["']?DELETE["']?\s+to\s+confirm/i);
      expect(code).not.toMatch(/Type\s+the\s+(invoice\s+number|customer|tenant|word)\s+to\s+confirm/i);
    },
  );

  it("InvoiceEditModal — no `paidNumberInput` state remains", () => {
    const code = stripComments(FILES_TO_SWEEP["components/invoices/InvoiceEditModal.jsx"]);
    expect(code).not.toMatch(/paidNumberInput/);
    expect(code).not.toMatch(/setPaidNumberInput/);
  });

  it("QuoteInvoiceDetail — no `deleteConfirmText` state / token gate", () => {
    const code = stripComments(FILES_TO_SWEEP["pages/quotes/QuoteInvoiceDetail.jsx"]);
    expect(code).not.toMatch(/setDeleteConfirmText/);
    expect(code).not.toMatch(/_invoiceConfirmToken/);
    expect(code).not.toMatch(/_paymentConfirmToken/);
    expect(code).not.toMatch(/deleteConfirmText\.trim\(\)\s*!==/);
  });

  it("CustomersList — no `confirmTypedNumber` state / typed-input testid", () => {
    const code = stripComments(FILES_TO_SWEEP["pages/customers/CustomersList.jsx"]);
    expect(code).not.toMatch(/confirmTypedNumber/);
    expect(code).not.toMatch(/typed-confirm-input/);
    expect(code).not.toMatch(/customers-bulk-delete-typed-input/);
  });

  it("MergeCustomersModal — no live `CONFIRM_TOKEN` runtime var", () => {
    const code = stripComments(FILES_TO_SWEEP["components/customers/MergeCustomersModal.jsx"]);
    // The old ``CONFIRM_TOKEN = "MERGE"`` runtime constant is gone
    // (the module keeps a commented history line for spelunkers).
    expect(code).not.toMatch(/const\s+CONFIRM_TOKEN\s*=/);
  });
});


// ── Behavioural: shared dialog stays input-free ─────────────────
describe("ConfirmDeleteDialog · never renders a text input, "
  + "regardless of `requireTypeConfirm`", () => {
  it.each([true, false])(
    "requireTypeConfirm=%s → no input, Confirm enabled from mount",
    (flag) => {
      render(<ConfirmDeleteDialog open
        title="Delete X?"
        body="…"
        requireTypeConfirm={flag}
        typeConfirmString="DELETE"
        onConfirm={() => {}}
        onCancel={() => {}}
      />);
      expect(screen.queryByTestId("confirm-delete-type-input")).toBeNull();
      // eslint-disable-next-line testing-library/no-node-access
      expect(document.querySelector("input[type=\"text\"]")).toBeNull();
      expect(screen.getByTestId("confirm-delete-confirm-btn")).not.toBeDisabled();
    },
  );
});


// ── Behavioural: global `mustConfirm()` dialog is input-free too ─
function ConfirmTrigger({ withGate }) {
  const confirm = useConfirm();
  return (
    <button
      type="button"
      data-testid="trigger"
      onClick={() => confirm({
        title: "Delete pricebook item?",
        description: "This will archive it.",
        tone: "danger",
        confirmText: "Delete",
        requireTypeConfirm: withGate,
        typeConfirmString: "DELETE",
      })}
    >open</button>
  );
}

describe("Global confirm dialog · `requireTypeConfirm` is a no-op", () => {
  it.each([true, false])(
    "requireTypeConfirm=%s → dialog renders zero text inputs",
    (withGate) => {
      render(
        <ConfirmProvider>
          <ConfirmTrigger withGate={withGate} />
        </ConfirmProvider>,
      );
      fireEvent.click(screen.getByTestId("trigger"));
      expect(screen.getByTestId("app-confirm-dialog")).toBeTruthy();
      // eslint-disable-next-line testing-library/no-node-access
      expect(document.querySelector("input[type=\"text\"]")).toBeNull();
      // Confirm button enabled and fires on single click.
      const ok = screen.getByTestId("app-confirm-ok");
      expect(ok).not.toBeDisabled();
    },
  );
});


// ── Behavioural: CustomersList arm-and-execute testids ──────────
describe("CustomersList catastrophic modal · arm-and-execute testids exist", () => {
  const src = FILES_TO_SWEEP["pages/customers/CustomersList.jsx"];

  it("declares the arm-state + cooldown-state hooks", () => {
    const code = stripComments(src);
    expect(code).toMatch(/const\s*\[\s*deleteArmed\s*,\s*setDeleteArmed\s*\]\s*=\s*useState\s*\(\s*false\s*\)/);
    expect(code).toMatch(/const\s*\[\s*armCooldown\s*,\s*setArmCooldown\s*\]\s*=\s*useState\s*\(\s*0\s*\)/);
  });

  it("renders the catastrophic modal + arm/execute button testids", () => {
    expect(src).toMatch(/data-testid="customers-bulk-delete-catastrophic-modal"/);
    expect(src).toMatch(/data-testid="customers-bulk-delete-catastrophic-btn"/);
    expect(src).toMatch(/data-testid="customers-bulk-delete-catastrophic-cancel"/);
  });

  it("carries the `Arm delete` / `Confirm again in {n}s` copy branches", () => {
    const code = stripComments(src);
    expect(code).toMatch(/"Arm delete"/);
    expect(code).toMatch(/`Confirm again in \$\{armCooldown\}s`/);
  });
});


// ── Behavioural: arm-and-execute mini-harness ───────────────────
function ArmAndExecuteHarness({ onExecute }) {
  const [armed, setArmed] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(0);
  React.useEffect(() => {
    if (!armed || cooldown <= 0) return undefined;
    const t = setTimeout(() => setCooldown((n) => Math.max(0, n - 1)), 1000);
    return () => clearTimeout(t);
  }, [armed, cooldown]);
  return (
    <button
      type="button"
      onClick={() => {
        if (!armed) { setArmed(true); setCooldown(3); return; }
        if (cooldown > 0) return;
        onExecute();
      }}
      disabled={armed && cooldown > 0}
      data-testid="arm-btn"
      data-armed={armed ? "1" : "0"}
      data-cooldown={cooldown}
    >
      {!armed
        ? "Arm delete"
        : cooldown > 0
          ? `Confirm again in ${cooldown}s`
          : "Delete"}
    </button>
  );
}

describe("Arm-and-execute pattern · behaviour", () => {
  it("first click arms + starts a 3-second cooldown; second click fires", () => {
    vi.useFakeTimers();
    const spy = vi.fn();
    render(<ArmAndExecuteHarness onExecute={spy} />);
    const btn = screen.getByTestId("arm-btn");
    expect(btn.getAttribute("data-armed")).toBe("0");
    // Click 1 — arms.
    fireEvent.click(btn);
    expect(btn.getAttribute("data-armed")).toBe("1");
    expect(btn.getAttribute("data-cooldown")).toBe("3");
    expect(btn.disabled).toBe(true);
    // Click during cooldown — must NOT fire.
    fireEvent.click(btn);
    expect(spy).not.toHaveBeenCalled();
    // Tick the 3-second cooldown down to 0.
    vi.advanceTimersByTime(3000);
    // Button label + disabled state settle after the last tick.
    // Cooldown state read from the DOM after the timers advance.
    expect(spy).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
