/**
 * Phase 12 · Feb 2026 — "Require card on file" tri-state control.
 *
 * Renders a shadcn-style Switch labelled "Card on file required?" with
 * a "Using tenant default: <Required|Not required>" muted subtext when
 * the override is null. Tapping the switch sets an explicit override
 * (opposite of tenant default). A small "Reset to tenant default"
 * ghost button appears once an override is set.
 *
 * Below the toggle, a status pill:
 *   - Green   "Card on file"                 (has_card_on_file)
 *   - Yellow  "No card — required"           (effective && !has_card)
 *   - Muted   "No card — not required"       (!effective && !has_card)
 *
 * Visible to admin/manager/super_admin only. Techs + customers do not
 * see it at all — the parent gates on ``role``.
 *
 * All persistence goes through ``PATCH /api/customers/:id`` with the
 * ``require_card_on_file_override`` field (Phase 12 endpoint).
 */
import React, { useState } from "react";
import { CreditCard, RotateCcw } from "lucide-react";
import { api } from "@/api";

const PILL_STYLES = {
  ok: { bg: "#DCFCE7", fg: "#065F46", label: "Card on file" },
  requiredMissing: { bg: "#FEF3C7", fg: "#92400E",
                      label: "No card — required" },
  optional: { bg: "#F1F5F9", fg: "#475569",
              label: "No card — not required" },
};


export default function CardOnFileControl({ customer, tenantDefault,
                                              onSaved, onError }) {
  const override = customer.require_card_on_file_override;   // true | false | null
  const effective = !!customer.effective_require_card_on_file;
  const hasCard = !!customer.has_card_on_file;
  const [busy, setBusy] = useState(false);

  const pill = hasCard
    ? PILL_STYLES.ok
    : (effective ? PILL_STYLES.requiredMissing : PILL_STYLES.optional);

  const persist = async (nextOverride) => {
    setBusy(true);
    try {
      const doc = await api.patch(`/customers/${customer.id}`, {
        require_card_on_file_override: nextOverride,
      });
      onSaved && onSaved(doc);
    } catch (e) {
      onError && onError(e.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  // When override is null, tapping the switch flips to the OPPOSITE of
  // tenant default (that's the whole point of setting an explicit
  // override). When override is set, tapping flips its value.
  const onToggle = () => {
    if (busy) return;
    if (override === null) {
      persist(!tenantDefault);
    } else {
      persist(!override);
    }
  };

  // The "checked" position of the switch reflects the *effective*
  // state — matches user intuition ("is the requirement on?").
  const switchOn = effective;

  return (
    <div
      data-testid="card-on-file-control"
      className="rounded-2xl p-5 mb-3"
      style={{ backgroundColor: "#fff", border: "1px solid #E5E7EB" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: "#F8FAFC" }}>
            <CreditCard size={18} color="#0F172A" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-zinc-900">
              Card on file required?
            </div>
            {override === null ? (
              <div className="text-xs text-zinc-500 mt-0.5"
                    data-testid="card-on-file-tenant-default-hint">
                Using tenant default:{" "}
                <span className="font-medium">
                  {tenantDefault ? "Required" : "Not required"}
                </span>
              </div>
            ) : (
              <div className="text-xs text-zinc-500 mt-0.5"
                    data-testid="card-on-file-override-hint">
                Override:{" "}
                <span className="font-medium">
                  {override ? "Required" : "Not required"}
                </span>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {override !== null && (
            <button
              onClick={() => persist(null)}
              disabled={busy}
              data-testid="card-on-file-reset-default-btn"
              className="text-xs font-medium text-zinc-600 hover:text-zinc-900 inline-flex items-center gap-1 px-2 py-1 rounded-md"
            >
              <RotateCcw size={12} />
              Reset to tenant default
            </button>
          )}
          <button
            role="switch"
            aria-checked={switchOn}
            onClick={onToggle}
            disabled={busy}
            data-testid="card-on-file-toggle"
            className="relative inline-flex h-6 w-11 items-center rounded-full transition"
            style={{
              backgroundColor: switchOn ? "#0F172A" : "#CBD5E1",
              opacity: busy ? 0.6 : 1,
            }}
          >
            <span
              className="inline-block h-5 w-5 transform rounded-full bg-white transition"
              style={{
                transform: `translateX(${switchOn ? "22px" : "2px"})`,
                boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
              }}
            />
          </button>
        </div>
      </div>

      <div className="mt-3 flex items-center">
        <span
          data-testid="card-on-file-status-pill"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
          style={{ backgroundColor: pill.bg, color: pill.fg }}
        >
          <CreditCard size={12} />
          {pill.label}
          {hasCard && customer.card_brand && customer.card_last4 ? (
            <span className="ml-1 opacity-80">
              · {customer.card_brand} ····{customer.card_last4}
              {customer.card_exp_month && customer.card_exp_year
                ? ` (exp ${String(customer.card_exp_month).padStart(2, "0")}/${String(customer.card_exp_year).slice(-2)})`
                : ""}
            </span>
          ) : null}
        </span>
      </div>
    </div>
  );
}
