/**
 * MP2 UI — Master Billing card (Feb-2026 ship).
 *
 * Mode selector (Off / Consolidated / Forward to Master Contact) +
 * conditional master_billing_contact_email / _phone fields, a Preview
 * button that calls POST /api/invoices/preview-recipient, and a
 * Consolidate action (visible when mode=='consolidated' AND pending
 * invoices exist) that opens a dialog showing
 * GET /api/customers/{cid}/pending-invoices grouped view + a Commit
 * button that runs POST /api/invoices/consolidate.
 */
import React from "react";
import { Wallet, Eye, Layers } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, TextInput, Modal, Chip } from "@/components/ui-kit";

const MODES = [
  { k: "off", label: "Off (per-property)", hint: "Each property invoices independently to its on-site contact." },
  { k: "consolidated", label: "Consolidated", hint: "Aggregate line items across properties into one customer invoice." },
  { k: "forward_to_master_contact", label: "Forward to master contact", hint: "Per-property invoices go to a single billing contact." },
];

export default function MasterBillingCard({ customer, onToast, onRefreshCustomer }) {
  const [mode, setMode] = React.useState(customer.master_billing_mode || "off");
  const [email, setEmail] = React.useState(customer.master_billing_contact_email || "");
  const [phone, setPhone] = React.useState(customer.master_billing_contact_phone || "");
  const [saving, setSaving] = React.useState(false);
  const [preview, setPreview] = React.useState(null);
  const [previewing, setPreviewing] = React.useState(false);
  const [consolidateOpen, setConsolidateOpen] = React.useState(false);
  const [pending, setPending] = React.useState(null);

  React.useEffect(() => {
    setMode(customer.master_billing_mode || "off");
    setEmail(customer.master_billing_contact_email || "");
    setPhone(customer.master_billing_contact_phone || "");
  }, [customer.id, customer.master_billing_mode, customer.master_billing_contact_email, customer.master_billing_contact_phone]);

  React.useEffect(() => {
    // Load pending invoice summary so we can decide whether to show
    // the Consolidate button.
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(`/customers/${customer.id}/pending-invoices`);
        if (!cancelled) setPending(r);
      } catch {
        /* non-fatal — card still renders */
      }
    })();
    return () => { cancelled = true; };
  }, [customer.id]);

  const persist = async (newMode) => {
    setSaving(true);
    try {
      await api.patch(`/customers/${customer.id}/master-billing`, {
        mode: newMode,
        master_billing_contact_email: email || null,
        master_billing_contact_phone: phone || null,
      });
      setMode(newMode);
      onToast?.({ tone: "success", message: `Billing mode: ${newMode}` });
      onRefreshCustomer?.();
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    setPreviewing(true);
    try {
      const r = await api.post("/invoices/preview-recipient", {
        customer_id: customer.id,
        mode,
      });
      setPreview(r.recipient);
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    } finally {
      setPreviewing(false);
    }
  };

  const hasPending = (pending?.pending_count || 0) > 0;

  return (
    <section
      className="rounded-2xl p-5 mb-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="master-billing-card"
    >
      <header className="flex items-center gap-2 mb-3">
        <Wallet size={18} style={{ color: colors.brand }} />
        <div className="text-base font-bold" style={{ color: colors.onSurface }}>Master Billing</div>
        <Chip label={mode} tone="brandTertiary" testid="mb-current-mode" />
      </header>

      <div className="space-y-2 mb-4">
        {MODES.map((m) => (
          <label key={m.k} className="flex items-start gap-2 p-2 rounded-lg cursor-pointer" style={{ backgroundColor: mode === m.k ? colors.surfaceMuted : "transparent" }}>
            <input
              type="radio"
              name="mb-mode"
              checked={mode === m.k}
              onChange={() => persist(m.k)}
              disabled={saving}
              data-testid={`mb-mode-${m.k}`}
            />
            <div>
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{m.label}</div>
              <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{m.hint}</div>
            </div>
          </label>
        ))}
      </div>

      {mode !== "off" ? (
        <div className="grid grid-cols-2 gap-2 mb-3">
          <TextInput
            label="MASTER BILLING EMAIL"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => persist(mode)}
            testid="mb-email"
          />
          <TextInput
            label="MASTER BILLING PHONE"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            onBlur={() => persist(mode)}
            placeholder="+15551234567"
            testid="mb-phone"
          />
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 items-center">
        <Button
          variant="ghost"
          onClick={runPreview}
          disabled={previewing}
          testid="mb-preview-btn"
        >
          <Eye size={14} /> {previewing ? "Previewing…" : "Preview recipient"}
        </Button>
        {mode === "consolidated" && hasPending ? (
          <Button
            onClick={() => setConsolidateOpen(true)}
            testid="mb-consolidate-btn"
          >
            <Layers size={14} /> Consolidate ({pending.pending_count})
          </Button>
        ) : null}
        {pending ? (
          <span className="text-xs" style={{ color: colors.onSurfaceSecondary }} data-testid="mb-pending-total">
            Pending balance: ${pending.grand_balance?.toFixed(2) || "0.00"}
          </span>
        ) : null}
      </div>

      {preview ? (
        <div
          className="mt-3 rounded-lg p-3 text-sm"
          style={{ backgroundColor: colors.surfaceMuted, color: colors.onSurface }}
          data-testid="mb-preview-result"
        >
          <div className="font-semibold">Next invoice would go to:</div>
          <div>Email: <code>{preview.email || "—"}</code></div>
          <div>Phone: <code>{preview.phone || "—"}</code></div>
          <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
            Delivery: {preview.delivery_kind} · {preview.send_status_hint}
          </div>
        </div>
      ) : null}

      <ConsolidateDialog
        open={consolidateOpen}
        onClose={() => setConsolidateOpen(false)}
        customer={customer}
        pending={pending}
        onDone={async () => {
          setConsolidateOpen(false);
          onToast?.({ tone: "success", message: "Invoices consolidated" });
          try {
            const r = await api.get(`/customers/${customer.id}/pending-invoices`);
            setPending(r);
          } catch { /* ignore */ }
        }}
        onError={(m) => onToast?.({ tone: "error", message: m })}
      />
    </section>
  );
}

function ConsolidateDialog({ open, onClose, customer, pending, onDone, onError }) {
  const [busy, setBusy] = React.useState(false);
  const [period, setPeriod] = React.useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });

  const commit = async () => {
    setBusy(true);
    try {
      await api.post("/invoices/consolidate", {
        customer_id: customer.id,
        period,
      });
      onDone();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Consolidate pending invoices — ${customer.name || ""}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={commit} disabled={busy || !(pending?.pending_count > 0)} testid="mb-consolidate-confirm">
            {busy ? "Consolidating…" : "Consolidate"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <TextInput
          label="BILLING PERIOD"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          placeholder="YYYY-MM"
          testid="mb-period"
        />
        {!pending ? (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading pending invoices…</div>
        ) : (pending.pending_count || 0) === 0 ? (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>No pending invoices to consolidate.</div>
        ) : (
          <div className="space-y-3">
            {(pending.groups || []).map((g) => (
              <div key={g.property_id} className="rounded-lg p-2" style={{ backgroundColor: colors.surfaceMuted }}>
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {g.property_label} — ${g.balance_total.toFixed(2)}
                </div>
                <ul className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
                  {g.invoices.map((inv) => (
                    <li key={inv.id}>
                      · {inv.title} — ${inv.balance.toFixed(2)} {inv.due_date ? `(due ${inv.due_date})` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {(pending.unassigned?.invoices || []).length > 0 ? (
              <div className="rounded-lg p-2" style={{ backgroundColor: colors.surfaceMuted }}>
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  Unassigned — ${pending.unassigned.balance_total.toFixed(2)}
                </div>
                <ul className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
                  {pending.unassigned.invoices.map((inv) => (
                    <li key={inv.id}>
                      · {inv.title} — ${inv.balance.toFixed(2)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }} data-testid="mb-grand-total">
              Grand balance: ${pending.grand_balance.toFixed(2)}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
