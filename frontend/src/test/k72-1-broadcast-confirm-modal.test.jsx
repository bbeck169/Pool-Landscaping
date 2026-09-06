/**
 * Phase K72.1 · Feb-2026 — Broadcast confirm modal contract tests.
 *
 * The modal fires on:
 *   * ``audience === "all_active_customers"`` for any recipient count.
 *   * Non-broadcast audiences whose recipient count exceeds 50.
 *
 * Small (<=50) targeted sends bypass the type-to-confirm gate and
 * fall back to a one-click confirmation (parity with pre-K72 UX).
 *
 * The type-to-confirm input requires the operator to type the
 * tenant name exactly (case-sensitive). Send button stays disabled
 * until the input matches. Cancel button is always enabled and is
 * the default action.
 *
 * Source-shape checks — the runtime mount graph for the compose
 * dialog is very heavy (audiences, filters, templates, live
 * preview, previews-then-send) so we assert against the component
 * source text rather than mounting the full tree. This is the
 * durable + fast surface consistent with K68 + K49 conventions.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(
    process.cwd(),
    "src/components/mass-messaging/MassMessagingComposeDialog.jsx",
  ),
  "utf-8",
);

describe("Phase K72.1 · Broadcast confirm modal", () => {
  it("K72BroadcastConfirmBody component exists", () => {
    expect(SRC).toMatch(/function K72BroadcastConfirmBody\(/);
  });

  it("fires on all_active_customers OR total > 50", () => {
    const body = SRC.split("function K72BroadcastConfirmBody(")[1] || "";
    expect(body).toMatch(/audience === "all_active_customers"/);
    expect(body).toMatch(/total > 50/);
  });

  it("reads tenant name from localStorage.tenant_name", () => {
    const body = SRC.split("function K72BroadcastConfirmBody(")[1] || "";
    expect(body).toMatch(/localStorage[^"]*"tenant_name"/);
  });

  it("requires the tenant-name type-to-confirm input for broadcasts", () => {
    const body = SRC.split("function K72BroadcastConfirmBody(")[1] || "";
    expect(body).toMatch(
      /data-testid="k72-typed-confirm-input"/,
    );
    // typedOk gate: broadcast requires the input to match; non-
    // broadcast bypasses the check.
    expect(body).toMatch(/requiresTypeConfirm\s*\?\s*[\s\S]{0,80}?===\s*tenantName/);
  });

  it("disables the send button until typedOk is true", () => {
    const body = SRC.split("function K72BroadcastConfirmBody(")[1] || "";
    expect(body).toMatch(/disabled=\{!typedOk \|\| sending\}/);
  });

  it("shows recipient count + subject + template preview", () => {
    const body = SRC.split("function K72BroadcastConfirmBody(")[1] || "";
    expect(body).toMatch(/data-testid="k72-broadcast-total"/);
    expect(body).toMatch(/data-testid="k72-broadcast-subject"/);
    expect(body).toMatch(/data-testid="k72-broadcast-template"/);
    expect(body).toMatch(/data-testid="k72-broadcast-body"/);
  });

  it("compose dialog delegates the confirm body to K72BroadcastConfirmBody", () => {
    // The AlertDialogContent for the mass-messaging confirm modal
    // now renders the K72 body instead of an inline title/desc.
    expect(SRC).toMatch(
      /<K72BroadcastConfirmBody[\s\S]{0,1000}?audience="all_active_customers"/,
    );
  });

  it("cancel button preserved with the same data-testid for backwards compat", () => {
    expect(SRC).toMatch(/data-testid="mass-messaging-confirm-cancel"/);
  });

  it("send button preserved with the same data-testid for backwards compat", () => {
    expect(SRC).toMatch(/data-testid="mass-messaging-confirm-send"/);
  });
});
