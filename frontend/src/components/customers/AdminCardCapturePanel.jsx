/**
 * Phase 14a · Feb-2026 — Admin payment-methods panel for the customer
 * detail page. B1 · Feb-2026 update — surfaces BOTH card and ACH
 * capture flows in a single unified list.  The saved-methods list
 * carries a ``type`` discriminator per row (``card`` |
 * ``us_bank_account``) so the UI renders card or bank-account
 * chrome inline without a second Stripe roundtrip.
 *
 * Add flow: two side-by-side "Add card" / "Add bank (ACH)" toggles
 * open the respective inline form; opening one closes the other
 * (accordion behaviour).  Both forms use the shared admin
 * endpoints (``POST /payments/stripe/setup-intent`` +
 * ``POST /payments/stripe/attach``) — the ACH flow passes
 * ``payment_method_types=["us_bank_account"]``.
 *
 * Remove flow: cards get the old ``window.confirm`` prompt; ACH
 * accounts show a proper confirm modal (banks are more sensitive).
 *
 * Props:
 *   customerId  (string, required)
 *   onChange    (fn(), optional) — invoked after add/remove so parent
 *                                    can refetch customer summary.
 */
import React, { useCallback, useEffect, useState } from "react";

import StripeAddCardForm from "../payments/StripeAddCardForm";
import StripeAddBankForm from "../payments/StripeAddBankForm";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from "../ui/dialog";
import { toast } from "sonner";
// Phase 20 · Feb-2026 · Sub-item C — publishable key comes from the
// backend at request time via ``GET /api/payments/stripe/config``.
import { getStripeConfig } from "@/lib/stripeConfig";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;


// ─── Helpers ─────────────────────────────────────────────────────────

function isBankRow(r) {
  return (r?.type === "us_bank_account")
    || (!!r?.bank_name && !r?.brand);
}


function VerificationChip({ status }) {
  const clean = String(status || "").toLowerCase();
  const style =
    clean === "verified"
      ? "bg-emerald-100 text-emerald-800"
      : clean === "failed"
        ? "bg-red-100 text-red-800"
        : "bg-amber-100 text-amber-800";
  const label =
    clean === "verified"
      ? "Verified"
      : clean === "failed"
        ? "Verification failed"
        : "Pending micro-deposits";
  return (
    <span
      className={`ml-2 rounded ${style} px-1.5 py-0.5 text-[10px] font-semibold uppercase`}
      title={
        clean === "failed"
          ? "Micro-deposit verification failed — reconnect the bank to re-verify."
          : "Micro-deposits typically verify in 2–3 business days. Customer will receive an email from Stripe."
      }
      data-testid={`admin-ach-verification-chip-${clean || "unverified"}`}
    >
      {label}
    </span>
  );
}


function CardRow({ r, onRemove }) {
  return (
    <li
      className="flex items-center justify-between p-3"
      data-testid={`admin-card-row-${r.provider_payment_method_id}`}
    >
      <div className="text-sm">
        <div className="font-medium capitalize inline-flex items-center gap-1">
          <span aria-hidden>💳</span>
          {r.brand || "Card"} •••• {r.last4 || "----"}
          {r.is_default ? (
            <span
              className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800"
              data-testid="admin-card-default-badge"
            >
              Default
            </span>
          ) : null}
        </div>
        <div className="text-xs text-slate-500">
          exp {String(r.exp_month || "").padStart(2, "0")}/
          {r.exp_year || "----"}
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="text-red-600 hover:bg-red-50"
        onClick={() => onRemove(r, "card")}
        data-testid={`admin-remove-card-${r.provider_payment_method_id}`}
      >
        Remove
      </Button>
    </li>
  );
}


function BankRow({ r, onRemove, onReverify, onVerifyMicrodeposits }) {
  /* K43 · Feb-2026 — surface a verify action on ANY unverified bank,
   * not just the K37 ``failed`` state.  The reason we show two
   * different buttons:
   *
   *   * ``pending_microdeposit`` — Stripe already sent the two cent
   *     amounts; the admin can enter them right now via the
   *     "Verify (micro-deposits)" modal.
   *   * everything else non-verified — no live SetupIntent; the
   *     admin needs to kick off a fresh Financial Connections /
   *     magic-link flow via "Re-verify bank" (was: the K37 "Re-verify"
   *     link on ``failed`` only).
   */
  const status = String(r.verification_status || "").toLowerCase();
  const failed = status === "failed";
  const pendingMicrodeposit = status === "pending_microdeposit"
                                || status === "pending"
                                || status === "new";
  const needsReverify = !!status && status !== "verified"
                          && !pendingMicrodeposit;
  const pmId = r.provider_payment_method_id;
  return (
    <li
      className="flex items-center justify-between p-3"
      data-testid={`admin-bank-row-${pmId}`}
    >
      <div className="text-sm">
        <div className="font-medium inline-flex items-center gap-1">
          <span aria-hidden>🏦</span>
          {r.bank_name || "Bank"} • •••• {r.last4 || "----"}
          <VerificationChip status={r.verification_status} />
        </div>
        <div className="text-xs text-slate-500 inline-flex items-center gap-2">
          <span className="capitalize">
            {r.account_holder_type || "ACH"}
          </span>
          {pendingMicrodeposit ? (
            <button
              type="button"
              onClick={() => onVerifyMicrodeposits(r)}
              className="text-emerald-700 underline"
              data-testid={`admin-bank-verify-microdeposits-${pmId}`}
            >
              Verify (micro-deposits)
            </button>
          ) : null}
          {(failed || needsReverify) ? (
            <button
              type="button"
              onClick={() => onReverify(r)}
              className="text-red-600 underline"
              data-testid={`admin-bank-reverify-${pmId}`}
            >
              Re-verify bank
            </button>
          ) : null}
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="text-red-600 hover:bg-red-50"
        onClick={() => onRemove(r, "bank")}
        data-testid={`admin-remove-bank-${pmId}`}
      >
        Remove
      </Button>
    </li>
  );
}


// ─── Panel ───────────────────────────────────────────────────────────

export default function AdminCardCapturePanel({ customerId, onChange }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(null);   // null | "card" | "bank"
  const [pubKey, setPubKey] = useState("");
  const [confirmBank, setConfirmBank] = useState(null);
  /* K43 · Feb-2026 — micro-deposits verify modal state. */
  const [verifyPm, setVerifyPm] = useState(null);   // pm row or null
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyMode, setVerifyMode] = useState("amounts"); // amounts | descriptor
  const [amtA, setAmtA] = useState("");
  const [amtB, setAmtB] = useState("");
  const [descriptor, setDescriptor] = useState("");
  const [verifyError, setVerifyError] = useState("");
  const token = typeof window !== "undefined"
    ? window.localStorage.getItem("token") : "";

  useEffect(() => {
    getStripeConfig().then((c) => setPubKey(c.publishable_key || ""));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `${API}/payments/stripe/payment-methods/${customerId}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const json = await res.json().catch(() => ({}));
      if (res.ok) setRows(json.payment_methods || []);
      else setRows([]);
    } finally {
      setLoading(false);
    }
  }, [customerId, token]);

  useEffect(() => {
    if (customerId) load();
  }, [customerId, load]);

  const removeById = async (pmId, kind) => {
    const res = await fetch(
      `${API}/payments/stripe/payment-methods/${pmId}`,
      { method: "DELETE",
         headers: { Authorization: `Bearer ${token}` } },
    );
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast.error(json.detail
        || `Failed to remove ${kind === "bank" ? "bank" : "card"}.`);
      return;
    }
    toast.success(kind === "bank" ? "Bank removed." : "Card removed.");
    await load();
    onChange?.();
  };

  const requestRemove = (row, kind) => {
    if (kind === "bank") {
      // ACH removals go through a proper confirm modal (banks are
      // more sensitive than cards).
      setConfirmBank(row);
      return;
    }
    // Cards keep the historical native confirm.
    if (!window.confirm("Remove this card from file?")) return;
    removeById(row.provider_payment_method_id, "card");
  };

  const startReverify = async (row) => {
    /* K43 · Feb-2026 — for banks that are unverified with NO live
     * SetupIntent (e.g. Hector's Wells Fargo backlog case) we can't
     * reuse the local Elements form; the admin needs a fresh
     * SetupIntent + magic-link email so the customer can finish
     * the flow from either the portal or their inbox.
     */
    try {
      const res = await fetch(
        `${API}/customers/${customerId}/bank-accounts/${row.provider_payment_method_id}/re-verify`,
        { method: "POST",
           headers: { Authorization: `Bearer ${token}`,
                      "Content-Type": "application/json" }},
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast.error(json.detail || "Re-verify failed.");
        return;
      }
      toast.success(
        json.email_sent
          ? "Re-verify link emailed to the customer."
          : "Re-verify session opened.",
      );
      await load();
      onChange?.();
    } catch (_e) {
      toast.error("Re-verify failed.");
    }
  };

  const startVerifyMicrodeposits = (row) => {
    setVerifyPm(row);
    setVerifyMode("amounts");
    setAmtA("");
    setAmtB("");
    setDescriptor("");
    setVerifyError("");
  };

  const submitVerifyMicrodeposits = async () => {
    if (!verifyPm) return;
    setVerifyError("");
    let body;
    if (verifyMode === "amounts") {
      const a = parseInt(amtA, 10);
      const b = parseInt(amtB, 10);
      if (!Number.isFinite(a) || !Number.isFinite(b)
          || a < 1 || a > 99 || b < 1 || b > 99) {
        setVerifyError(
          "Enter both deposits as cent amounts between 1 and 99.",
        );
        return;
      }
      body = { amounts_cents: [a, b] };
    } else {
      const code = String(descriptor || "").trim();
      if (!code) {
        setVerifyError("Enter the 6-digit descriptor code from the deposit.");
        return;
      }
      body = { descriptor_code: code };
    }
    setVerifyBusy(true);
    try {
      const res = await fetch(
        `${API}/customers/${customerId}/bank-accounts/${verifyPm.provider_payment_method_id}/verify-microdeposits`,
        { method: "POST",
           headers: { Authorization: `Bearer ${token}`,
                      "Content-Type": "application/json" },
           body: JSON.stringify(body) },
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setVerifyError(json.detail || "Verification failed.");
        setVerifyBusy(false);
        return;
      }
      toast.success("Bank verified — ACH charges enabled.");
      setVerifyPm(null);
      setVerifyBusy(false);
      await load();
      onChange?.();
    } catch (_e) {
      setVerifyError("Verification failed.");
      setVerifyBusy(false);
    }
  };

  const cards = rows.filter((r) => !isBankRow(r));
  const banks = rows.filter(isBankRow);
  const empty = rows.length === 0;

  const setAdd = (which) => {
    // Accordion: opening one closes the other; clicking the same one
    // toggles it off.
    setAddOpen((cur) => (cur === which ? null : which));
  };

  return (
    <Card data-testid="admin-card-capture-panel">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base"
                       data-testid="admin-pm-panel-title">
          Payment methods on file
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <p className="text-sm text-slate-500"
              data-testid="admin-pm-loading">Loading…</p>
        ) : empty ? (
          <p className="text-sm text-slate-500"
              data-testid="admin-no-cards-msg">
            No payment methods on file. Add card or ACH bank to
            enable one-off charges and auto-billing.
          </p>
        ) : (
          <ul className="divide-y divide-slate-200 rounded-md border border-slate-200"
                data-testid="admin-pm-list">
            {cards.map((r) => (
              <CardRow key={r.provider_payment_method_id}
                          r={r}
                          onRemove={requestRemove} />
            ))}
            {banks.map((r) => (
              <BankRow key={r.provider_payment_method_id}
                          r={r}
                          onRemove={requestRemove}
                          onReverify={startReverify}
                          onVerifyMicrodeposits={startVerifyMicrodeposits} />
            ))}
          </ul>
        )}

        {/* Add buttons — two side-by-side, accordion open/close */}
        <div className="flex flex-wrap gap-2"
                data-testid="admin-add-pm-controls">
          <Button
            size="sm"
            variant={addOpen === "card" ? "ghost" : "default"}
            onClick={() => setAdd("card")}
            data-testid="admin-toggle-add-card"
          >
            {addOpen === "card" ? "Close card form" : "+ Add card"}
          </Button>
          <Button
            size="sm"
            variant={addOpen === "bank" ? "ghost" : "outline"}
            onClick={() => setAdd("bank")}
            data-testid="admin-toggle-add-bank"
          >
            {addOpen === "bank" ? "Close bank form" : "+ Add bank (ACH)"}
          </Button>
        </div>

        {addOpen === "card" ? (
          <StripeAddCardForm
            apiBase={API}
            authToken={token}
            customerId={customerId}
            publishableKey={pubKey}
            title="Capture card on behalf of customer"
            onSuccess={async () => {
              setAddOpen(null);
              await load();
              onChange?.();
            }}
            onCancel={() => setAddOpen(null)}
          />
        ) : null}

        {addOpen === "bank" ? (
          <StripeAddBankForm
            apiBase={API}
            authToken={token}
            customerId={customerId}
            publishableKey={pubKey}
            title="Connect bank account on behalf of customer"
            onSuccess={async () => {
              setAddOpen(null);
              await load();
              onChange?.();
            }}
            onCancel={() => setAddOpen(null)}
          />
        ) : null}
      </CardContent>

      {/* ACH remove confirm modal */}
      <Dialog
        open={!!confirmBank}
        onOpenChange={(open) => { if (!open) setConfirmBank(null); }}
      >
        <DialogContent data-testid="admin-confirm-remove-bank">
          <DialogHeader>
            <DialogTitle>Remove bank account?</DialogTitle>
            <DialogDescription>
              This detaches{" "}
              <strong>
                {confirmBank?.bank_name || "the bank"} ••••{" "}
                {confirmBank?.last4 || "----"}
              </strong>{" "}
              from this customer.  Auto-billing that relies on this
              account will pause until a new payment method is added.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setConfirmBank(null)}
              data-testid="admin-confirm-remove-bank-cancel"
            >
              Cancel
            </Button>
            <Button
              className="bg-red-600 text-white hover:bg-red-700"
              onClick={async () => {
                const pmId = confirmBank?.provider_payment_method_id;
                setConfirmBank(null);
                if (pmId) await removeById(pmId, "bank");
              }}
              data-testid="admin-confirm-remove-bank-submit"
            >
              Remove bank
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* K43 · Feb-2026 — Micro-deposits verify modal.  Admin can
          either enter the two cent-amount deposits Stripe sent OR the
          6-digit descriptor code from the single-descriptor deposit
          path.  Success flips the mirror row's verification_status
          to "verified" and unblocks K38 bulk / autobilling. */}
      <Dialog
        open={!!verifyPm}
        onOpenChange={(open) => { if (!open) setVerifyPm(null); }}
      >
        <DialogContent data-testid="admin-bank-verify-modal">
          <DialogHeader>
            <DialogTitle>
              Verify bank via micro-deposits
            </DialogTitle>
            <DialogDescription>
              Enter the two cent-amount deposits Stripe sent to{" "}
              <strong>
                {verifyPm?.bank_name || "the bank"} ••••{" "}
                {verifyPm?.last4 || "----"}
              </strong>
              , or the 6-digit descriptor code if the customer received a
              single verification deposit.
            </DialogDescription>
          </DialogHeader>

          <div className="mb-3 flex gap-2">
            <button
              type="button"
              onClick={() => setVerifyMode("amounts")}
              className={`rounded border px-2 py-1 text-xs ${verifyMode === "amounts" ? "bg-slate-900 text-white" : "bg-white"}`}
              data-testid="admin-bank-verify-mode-amounts"
            >
              Two amounts
            </button>
            <button
              type="button"
              onClick={() => setVerifyMode("descriptor")}
              className={`rounded border px-2 py-1 text-xs ${verifyMode === "descriptor" ? "bg-slate-900 text-white" : "bg-white"}`}
              data-testid="admin-bank-verify-mode-descriptor"
            >
              Descriptor code
            </button>
          </div>

          {verifyMode === "amounts" ? (
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs">
                Deposit 1 (cents)
                <input
                  type="number" min="1" max="99"
                  className="mt-1 block w-full rounded border px-2 py-1 text-sm"
                  value={amtA}
                  onChange={(e) => setAmtA(e.target.value)}
                  data-testid="admin-bank-verify-amt-a"
                />
              </label>
              <label className="text-xs">
                Deposit 2 (cents)
                <input
                  type="number" min="1" max="99"
                  className="mt-1 block w-full rounded border px-2 py-1 text-sm"
                  value={amtB}
                  onChange={(e) => setAmtB(e.target.value)}
                  data-testid="admin-bank-verify-amt-b"
                />
              </label>
            </div>
          ) : (
            <label className="text-xs">
              Descriptor code (6 digits)
              <input
                type="text" maxLength="6"
                className="mt-1 block w-full rounded border px-2 py-1 text-sm font-mono uppercase"
                value={descriptor}
                onChange={(e) => setDescriptor(e.target.value)}
                data-testid="admin-bank-verify-descriptor"
              />
            </label>
          )}

          {verifyError ? (
            <div
              className="mt-2 text-sm text-red-600"
              data-testid="admin-bank-verify-error"
            >
              {verifyError}
            </div>
          ) : null}

          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setVerifyPm(null)}
              disabled={verifyBusy}
              data-testid="admin-bank-verify-cancel"
            >
              Cancel
            </Button>
            <Button
              onClick={submitVerifyMicrodeposits}
              disabled={verifyBusy}
              data-testid="admin-bank-verify-submit"
            >
              {verifyBusy ? "Verifying…" : "Verify bank"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
