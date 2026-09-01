/**
 * Phase I5 · Feb-2026 — Payment Method Tiles (shared).
 *
 * Polished card + ACH on-file tiles for two mount points:
 *   * Admin customer detail Overview tab (this wave)
 *   * Customer portal Billing Method tab (Wave B, next session)
 *
 * On-file state renders a soft-green (``colors.landscape[50/300/700]``)
 * tile with masked digits and padlock glyphs; the empty state is a
 * saturated dark-red container (``colors.error`` + ``onError``) with
 * bold copy indicating no payment method is on file, per the human's
 * mockup.
 *
 * Add / Edit / Delete flows:
 *   * **Add** — toggles the existing ``StripeAddCardForm`` /
 *     ``StripeAddBankForm`` inline underneath the subsection.
 *   * **Edit** — Stripe PMs are immutable post-attach, so "Edit" is
 *     also mapped to the inline Add form; the operator's expected to
 *     add a fresh PM and then delete the outdated one.  A one-line
 *     helper explains the workflow so operators don't hunt for a
 *     non-existent edit modal.
 *   * **Delete** — TypedConfirmModal (H2 pattern) with the last-4
 *     as the keyword.  On arm-and-confirm the tile posts to the
 *     new ``POST /payment-methods/{id}/delete-typed`` endpoint,
 *     which re-validates the typed keyword server-side so a
 *     scripted client can't skip the confirm.
 *
 * Props:
 *   * ``customerId`` — required. The customer whose PMs to show.
 *   * ``variant`` — ``"admin"`` (default) | ``"portal"``.  Governs
 *     the small copy differences between the two surfaces; visual
 *     chrome is otherwise identical.
 *   * ``onChange`` — optional callback fired after any add/delete
 *     so the parent can refresh its own summaries (e.g. the
 *     customer's ``has_card_on_file`` badge in the admin header).
 */
import React, { useCallback, useEffect, useState } from "react";
import { CreditCard, Landmark, Lock, Plus, Pencil, Trash2 }
  from "lucide-react";
import { toast } from "sonner";

import StripeAddCardForm from "../payments/StripeAddCardForm";
import StripeAddBankForm from "../payments/StripeAddBankForm";
import TypedConfirmModal from "../ui/TypedConfirmModal";
import { api } from "@/api";
import { colors } from "@/theme";


// ═══════════════════════════════════════════════════════════════════
// Small primitives — colocated so the file can be dropped anywhere
// without importing internal styling that a future refactor might
// reshape. Each primitive is <15 LOC and doesn't leak state.
// ═══════════════════════════════════════════════════════════════════
function LockedField({ label, value, testid }) {
  return (
    <div className="flex-1 min-w-0"
             data-testid={testid}>
      <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
                style={{ color: colors.landscape[700] }}>
        {label}
      </div>
      <div className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-mono truncate"
                style={{
                  background: colors.surface,
                  border: `1px solid ${colors.landscape[300]}`,
                  color: colors.onSurface,
                }}>
        <Lock size={12} style={{ color: colors.landscape[700] }} />
        <span className="truncate">{value}</span>
      </div>
    </div>
  );
}


function ActionButton({ label, tone = "neutral", onClick, testid, disabled }) {
  const styles = tone === "danger"
    ? { bg: "#FEE2E2", fg: "#991B1B", border: "#FCA5A5" }
    : { bg: colors.surface, fg: colors.onSurface,
             border: colors.borderStrong };
  return (
    <button
      type="button"
      className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
      style={{
        background: styles.bg, color: styles.fg,
        border: `1px solid ${styles.border}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
      onClick={disabled ? undefined : onClick}
      data-testid={testid}
    >
      {label}
    </button>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Filled tile (on-file) + empty-state container
// ═══════════════════════════════════════════════════════════════════
function CardTile({ row, onEdit, onDelete }) {
  const brand = (row.brand || "card").toUpperCase();
  const last4 = row.last4 || "••••";
  const exp = (row.exp_month && row.exp_year)
    ? `${String(row.exp_month).padStart(2, "0")} / ${row.exp_year}`
    : "—";
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: colors.landscape[50],
        border: `2px solid ${colors.landscape[300]}`,
      }}
      data-testid={`payment-tile-card-${row.id}`}
    >
      <div className="flex items-center gap-2 mb-3">
        <CreditCard size={16} style={{ color: colors.landscape[700] }} />
        <span className="text-xs font-bold uppercase tracking-wider"
                  style={{ color: colors.landscape[700] }}>
          {brand} on file{row.is_default ? " · default" : ""}
        </span>
      </div>
      <div className="flex flex-wrap gap-3">
        <LockedField
          label="Card number"
          value={`•••• •••• •••• ${last4}`}
          testid={`payment-tile-card-number-${row.id}`}
        />
        <LockedField
          label="Expires"
          value={exp}
          testid={`payment-tile-card-exp-${row.id}`}
        />
      </div>
      <div className="mt-3 flex gap-2">
        <ActionButton
          label={<><Pencil size={12} /> Edit Card Info</>}
          onClick={() => onEdit(row)}
          testid={`payment-tile-card-edit-${row.id}`}
        />
        <ActionButton
          label={<><Trash2 size={12} /> Delete Credit Card</>}
          tone="danger"
          onClick={() => onDelete(row)}
          testid={`payment-tile-card-delete-${row.id}`}
        />
      </div>
    </div>
  );
}


function BankTile({ row, onEdit, onDelete }) {
  const last4 = row.last4 || "••••";
  const bank = row.bank_name || "Bank";
  const acct = row.account_holder_type
    ? row.account_holder_type[0].toUpperCase() + row.account_holder_type.slice(1)
    : "Account";
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: colors.landscape[50],
        border: `2px solid ${colors.landscape[300]}`,
      }}
      data-testid={`payment-tile-bank-${row.id}`}
    >
      <div className="flex items-center gap-2 mb-3">
        <Landmark size={16} style={{ color: colors.landscape[700] }} />
        <span className="text-xs font-bold uppercase tracking-wider"
                  style={{ color: colors.landscape[700] }}>
          Bank account on file{row.is_default ? " · default" : ""}
        </span>
      </div>
      <div className="flex flex-wrap gap-3">
        <LockedField
          label="Account"
          value={`•••• ${last4}`}
          testid={`payment-tile-bank-number-${row.id}`}
        />
        <LockedField
          label="Bank"
          value={bank}
          testid={`payment-tile-bank-name-${row.id}`}
        />
        <LockedField
          label="Type"
          value={acct}
          testid={`payment-tile-bank-type-${row.id}`}
        />
      </div>
      <div className="mt-3 flex gap-2">
        <ActionButton
          label={<><Pencil size={12} /> Edit Account Info</>}
          onClick={() => onEdit(row)}
          testid={`payment-tile-bank-edit-${row.id}`}
        />
        <ActionButton
          label={<><Trash2 size={12} /> Delete Bank Account</>}
          tone="danger"
          onClick={() => onDelete(row)}
          testid={`payment-tile-bank-delete-${row.id}`}
        />
      </div>
    </div>
  );
}


function EmptyState({ kind, onAdd, testid }) {
  const copy = kind === "card"
    ? {
        title: "No Credit/Debit Card Information Found for This Customer",
        cta: "Add a Credit/Debit Card",
      }
    : {
        title: "No Bank Account Information Found for This Customer",
        cta: "Add Bank Account",
      };
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: colors.error,
        color: colors.onError,
      }}
      data-testid={testid}
    >
      <div className="flex items-center gap-2 mb-3">
        {kind === "card"
          ? <CreditCard size={16} style={{ color: colors.onError }} />
          : <Landmark size={16} style={{ color: colors.onError }} />}
        <span className="text-sm font-bold">{copy.title}</span>
      </div>
      <button
        type="button"
        className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
        style={{
          background: colors.surface, color: colors.onSurface,
        }}
        onClick={onAdd}
        data-testid={`${testid}-add`}
      >
        <Plus size={12} /> {copy.cta}
      </button>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Main component
// ═══════════════════════════════════════════════════════════════════
export default function PaymentMethodTiles({
  customerId,
  variant = "admin",
  onChange,
}) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [methods, setMethods] = useState([]);
  const [addOpen, setAddOpen] = useState(null);   // null | "card" | "bank"
  const [pending, setPending] = useState(null);   // row targeted for delete
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!customerId) return;
    setLoading(true);
    try {
      const r = await api.get(
        `/payments/stripe/payment-methods/${customerId}`,
      );
      setMethods(r?.payment_methods || []);
      setErr("");
    } catch (e) {
      setErr(e?.message || "Couldn't load payment methods");
    } finally {
      setLoading(false);
    }
  }, [customerId]);
  useEffect(() => { load(); }, [load]);

  const cards = methods.filter((m) => (m.type || "card") === "card");
  const banks = methods.filter((m) => m.type === "us_bank_account");

  const openAdd = (kind) => setAddOpen(kind);
  const closeAdd = () => setAddOpen(null);

  const onAddSuccess = async () => {
    setAddOpen(null);
    toast.success("Payment method added.");
    await load();
    onChange?.();
  };

  const openEdit = (row) => {
    // Stripe PMs are immutable post-attach; "Edit" opens the Add
    // form of the same type so the operator can add a fresh PM
    // and then delete the outdated one.  Surfaced hint keeps the
    // workflow obvious.
    const kind = (row.type === "us_bank_account") ? "bank" : "card";
    setAddOpen(kind);
    toast.info?.(
      "Card/bank details are immutable — add a new one, then delete the old.",
    );
  };

  const openDelete = (row) => {
    setPending(row);
  };
  const closeDelete = () => {
    if (busy) return;
    setPending(null);
  };

  const confirmDelete = async () => {
    if (!pending) return;
    const typedLast4 = pending.last4 || "";
    setBusy(true);
    try {
      await api.post(
        `/payments/stripe/payment-methods/${pending.provider_payment_method_id}/delete-typed`,
        { typed_last4: typedLast4 },
      );
      const kind = pending.type === "us_bank_account"
        ? "Bank account" : "Card";
      toast.success(`${kind} ending in ${pending.last4} removed.`);
      setPending(null);
      await load();
      onChange?.();
    } catch (e) {
      toast.error(e?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div
        className="rounded-2xl p-4"
        style={{ background: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}` }}
        data-testid="payment-method-tiles-loading"
      >
        <div className="text-sm" style={{ color: colors.muted }}>
          Loading payment methods…
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4"
             data-testid={`payment-method-tiles-${variant}`}>
      {err ? (
        <div
          className="text-xs rounded-lg px-3 py-2"
          style={{ background: "#FEE2E2", color: "#991B1B" }}
          data-testid="payment-method-tiles-error"
        >
          {err}
        </div>
      ) : null}

      {/* ── Credit / Debit Cards subsection ─────────────────── */}
      <section data-testid="payment-method-tiles-cards-section">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-bold flex items-center gap-1.5"
                    style={{ color: colors.onSurface }}>
            <CreditCard size={14} /> Credit / Debit Cards
          </h3>
          {cards.length ? (
            <ActionButton
              label={<><Plus size={12} /> Add another card</>}
              onClick={() => openAdd("card")}
              testid="payment-method-tiles-add-card"
            />
          ) : null}
        </div>
        {cards.length === 0 ? (
          <EmptyState
            kind="card"
            onAdd={() => openAdd("card")}
            testid="payment-method-tiles-card-empty"
          />
        ) : (
          <div className="space-y-3">
            {cards.map((row) => (
              <CardTile
                key={row.id}
                row={row}
                onEdit={openEdit}
                onDelete={openDelete}
              />
            ))}
          </div>
        )}
        {addOpen === "card" ? (
          <div className="mt-3 rounded-2xl p-3"
                    style={{ background: colors.surfaceSecondary,
                                border: `1px dashed ${colors.borderStrong}` }}
                    data-testid="payment-method-tiles-add-card-form">
            <StripeAddCardForm
              customerId={customerId}
              onSuccess={onAddSuccess}
              onCancel={closeAdd}
            />
          </div>
        ) : null}
      </section>

      {/* ── Bank Accounts subsection ────────────────────────── */}
      <section data-testid="payment-method-tiles-banks-section">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-bold flex items-center gap-1.5"
                    style={{ color: colors.onSurface }}>
            <Landmark size={14} /> Bank Accounts
          </h3>
          {banks.length ? (
            <ActionButton
              label={<><Plus size={12} /> Add another bank</>}
              onClick={() => openAdd("bank")}
              testid="payment-method-tiles-add-bank"
            />
          ) : null}
        </div>
        {banks.length === 0 ? (
          <EmptyState
            kind="bank"
            onAdd={() => openAdd("bank")}
            testid="payment-method-tiles-bank-empty"
          />
        ) : (
          <div className="space-y-3">
            {banks.map((row) => (
              <BankTile
                key={row.id}
                row={row}
                onEdit={openEdit}
                onDelete={openDelete}
              />
            ))}
          </div>
        )}
        {addOpen === "bank" ? (
          <div className="mt-3 rounded-2xl p-3"
                    style={{ background: colors.surfaceSecondary,
                                border: `1px dashed ${colors.borderStrong}` }}
                    data-testid="payment-method-tiles-add-bank-form">
            <StripeAddBankForm
              customerId={customerId}
              onSuccess={onAddSuccess}
              onCancel={closeAdd}
            />
          </div>
        ) : null}
      </section>

      {/* ── Typed-confirm delete gate ─────────────────────────── */}
      {pending ? (
        <TypedConfirmModal
          open
          title={pending.type === "us_bank_account"
                     ? "Delete bank account"
                     : "Delete credit / debit card"}
          description={
            <span>
              Type the last 4 (<strong>{pending.last4}</strong>) to permanently
              remove this{" "}
              {pending.type === "us_bank_account" ? "bank account" : "card"}.
              This may cause future recurring charges to fail.
            </span>
          }
          keyword={pending.last4 || ""}
          confirmLabel={busy ? "Removing…" : "Remove"}
          onConfirm={confirmDelete}
          onCancel={closeDelete}
          busy={busy}
          testIdPrefix="payment-tile-delete-confirm"
        />
      ) : null}
    </div>
  );
}
