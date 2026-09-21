/**
 * Phase M1 · Feb-2026 — Customer Merge Wizard modal.
 *
 * 3-step wizard, admin+super_admin only:
 *   Step 1 — search for the duplicate (debounced 250ms).
 *   Step 2 — per-field conflict resolver (name, email, phone, address).
 *   Step 3 — MERGE-text confirm gate + destructive POST.
 *
 * On success: toast + parent-supplied refetch callback.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { toast } from "sonner";
import { X, Search, ArrowRight, ArrowLeft, AlertTriangle }
       from "lucide-react";


const _FIELDS = [
  { key: "name",    label: "Name" },
  { key: "email",   label: "Email" },
  { key: "phone",   label: "Phone" },
  { key: "address", label: "Address" },
];


function _address(customer) {
  if (!customer) return "";
  // Preferred: use ``address`` field directly. Fall back to
  // property-shaped ``line1``, ``city``, ``state``, ``postal``.
  if (customer.address) return customer.address;
  const props = customer.properties || [];
  const p = props.find((x) => x && (x.is_primary || x.primary)) || props[0];
  if (!p) return "";
  const bits = [p.line1, p.city, p.state, p.postal].filter(Boolean);
  return bits.join(", ");
}


export default function CustomerMergeWizard({
  open, onClose, primary, onMerged,
}) {
  const [step, setStep] = useState(1);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [duplicate, setDuplicate] = useState(null);
  const [choices, setChoices] = useState({
    name:    "primary",
    email:   "primary",
    phone:   "primary",
    address: "primary",
  });
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [searchBusy, setSearchBusy] = useState(false);
  const debounceRef = useRef(null);

  // Reset when the modal opens/closes.
  useEffect(() => {
    if (open) {
      setStep(1); setQuery(""); setResults([]);
      setDuplicate(null);
      setChoices({ name: "primary", email: "primary",
                   phone: "primary", address: "primary" });
      setConfirmText("");
    }
  }, [open]);

  // Debounced search — 250ms.
  useEffect(() => {
    if (!open || step !== 1) return;
    const q = query.trim();
    if (!q) { setResults([]); return; }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setSearchBusy(true);
      try {
        const resp = await api.get("/customers", {
          params: { search: q, limit: 10 },
        });
        const items = Array.isArray(resp?.data) ? resp.data
          : (resp?.data?.items || resp?.data?.customers || []);
        // Filter out primary + soft-deleted rows (server should
        // exclude soft-deleted by default, belt-and-braces here).
        setResults(items.filter((c) =>
          c && c.id !== primary?.id
            && !c.is_deleted && !c.deleted_at && !c.merged_into));
      } catch (e) {
        setResults([]);
      } finally {
        setSearchBusy(false);
      }
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [open, step, query, primary?.id]);


  async function _submit() {
    if (!primary?.id || !duplicate?.id) return;
    setBusy(true);
    try {
      const resp = await api.post("/customers/merge-wizard", {
        primary_customer_id:   primary.id,
        duplicate_customer_id: duplicate.id,
        field_choices:         choices,
      });
      const total = Object.values(resp?.data?.reparent_counts || {})
        .reduce((a, b) => a + (Number(b) || 0), 0);
      toast.success(
        `Merged ${duplicate.name || duplicate.id} into ${primary.name}. `
        + `${total} related record${total === 1 ? "" : "s"} re-parented.`,
      );
      // Phase M1.1 — surface any advisory warnings from the backend
      // (Stripe records not merged, portal-login conflict, etc.) as
      // separate info toasts so the operator sees each one clearly.
      const warnings = Array.isArray(resp?.data?.warnings)
        ? resp.data.warnings : [];
      warnings.forEach((w) => {
        // ``sonner``'s info-level toast surfaces the string without
        // the destructive-red styling of ``toast.error``.
        (toast.info || toast.message || toast)(w, {
          duration: 12000,
        });
      });
      onMerged?.();
      onClose?.();
    } catch (err) {
      const detail = err?.response?.data?.detail || "";
      if (err?.response?.status === 403
          && String(detail).includes("cross_tenant")) {
        toast.error("Cross-tenant merges are not permitted.");
      } else if (err?.response?.status === 403) {
        toast.error("You don't have permission to merge customers.");
      } else if (err?.response?.status === 409) {
        toast.error("One of these customers is already deleted.");
      } else if (err?.response?.status === 400
                  && String(detail).includes("same_customer")) {
        toast.error("Cannot merge a customer with itself.");
      } else {
        toast.error(`Merge failed: ${detail || err.message}`);
      }
    } finally {
      setBusy(false);
    }
  }


  if (!open) return null;

  return (
    <div
      data-testid="customer-merge-wizard"
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,.45)" }}
    >
      <div
        className="w-full max-w-2xl rounded-2xl shadow-2xl"
        style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
      >
        <_Header primary={primary} step={step} onClose={onClose} />

        <div className="p-6 min-h-[280px]">
          {step === 1 ? (
            <_StepSearch
              query={query} setQuery={setQuery}
              results={results} searchBusy={searchBusy}
              onPick={(c) => { setDuplicate(c); setStep(2); }}
            />
          ) : step === 2 ? (
            <_StepResolve
              primary={primary} duplicate={duplicate}
              choices={choices} setChoices={setChoices}
            />
          ) : (
            <_StepConfirm
              primary={primary} duplicate={duplicate}
              choices={choices}
              confirmText={confirmText}
              setConfirmText={setConfirmText}
            />
          )}
        </div>

        <div
          className="flex items-center justify-between gap-2 px-6 py-4"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            data-testid="cmw-cancel-btn"
            className="text-xs font-semibold px-3 py-2 rounded"
            style={{ color: colors.muted }}
            onClick={onClose}
          >
            Cancel
          </button>
          <div className="flex items-center gap-2">
            {step > 1 ? (
              <button
                data-testid="cmw-back-btn"
                className="text-xs font-semibold px-3 py-2 rounded inline-flex items-center gap-1"
                style={{
                  color: colors.onSurface,
                  background: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                }}
                onClick={() => setStep(step - 1)}
              >
                <ArrowLeft size={12} /> Back
              </button>
            ) : null}
            {step < 3 ? (
              <button
                data-testid="cmw-next-btn"
                disabled={
                  (step === 1 && !duplicate)
                  || (step === 2 && !duplicate)
                }
                className="text-xs font-semibold px-3 py-2 rounded inline-flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  color: colors.onBrandPrimary,
                  background: colors.brand,
                }}
                onClick={() => setStep(step + 1)}
              >
                Next <ArrowRight size={12} />
              </button>
            ) : (
              <button
                data-testid="cmw-merge-btn"
                disabled={confirmText.trim() !== "MERGE" || busy}
                className="text-xs font-bold px-4 py-2 rounded inline-flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  color: "#fff",
                  background: colors.error,
                }}
                onClick={_submit}
              >
                {busy ? "Merging…" :
                    "Merge — This Cannot Be Undone"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


function _Header({ primary, step, onClose }) {
  return (
    <div
      className="flex items-start justify-between px-6 py-4"
      style={{ borderBottom: `1px solid ${colors.border}` }}
    >
      <div>
        <div className="text-xs uppercase tracking-wide"
              style={{ color: colors.muted }}>
          Merge customer · step {step} of 3
        </div>
        <div className="font-bold text-base mt-0.5"
              style={{ color: colors.onSurface }}
              data-testid="cmw-primary-label">
          Primary: {primary?.name || primary?.id || "(unknown)"}
        </div>
      </div>
      <button
        onClick={onClose}
        data-testid="cmw-close-btn"
        className="p-1.5 rounded hover:bg-black/[.04]"
        style={{ color: colors.muted }}
      >
        <X size={16} />
      </button>
    </div>
  );
}


function _StepSearch({
  query, setQuery, results, searchBusy, onPick,
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Search size={14} style={{ color: colors.muted }} />
        <input
          type="text"
          autoFocus
          data-testid="cmw-search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, email, or phone…"
          className="flex-1 px-3 py-2 text-sm rounded focus:outline-none focus-visible:ring-1"
          style={{
            background: colors.surfaceSecondary,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
        />
      </div>
      <div
        className="max-h-72 overflow-y-auto rounded"
        style={{ border: `1px solid ${colors.border}` }}
      >
        {searchBusy ? (
          <div className="p-4 text-sm text-center"
                style={{ color: colors.muted }}
                data-testid="cmw-search-busy">
            Searching…
          </div>
        ) : results.length === 0 ? (
          <div className="p-4 text-sm text-center"
                style={{ color: colors.muted }}
                data-testid="cmw-search-empty">
            {query.trim()
              ? `No customers found for “${query}”.`
              : "Type at least a few characters to search."}
          </div>
        ) : (
          results.map((c) => (
            <div
              key={c.id}
              data-testid={`cmw-result-row-${c.id}`}
              className="flex items-start justify-between gap-3 px-3 py-2 border-b"
              style={{ borderColor: colors.border }}
            >
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate"
                      style={{ color: colors.onSurface }}>
                  {c.name || "(unnamed)"}
                </div>
                <div className="text-xs truncate"
                      style={{ color: colors.muted }}>
                  {[c.email, c.phone, _address(c)]
                    .filter(Boolean).join(" · ")}
                </div>
              </div>
              <button
                data-testid={`cmw-select-${c.id}`}
                className="text-xs font-semibold px-2.5 py-1 rounded"
                style={{
                  color: colors.onBrandPrimary,
                  background: colors.brand,
                }}
                onClick={() => onPick(c)}
              >
                Select
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}


function _StepResolve({ primary, duplicate, choices, setChoices }) {
  const rows = useMemo(() =>
    _FIELDS.map((f) => ({
      key:       f.key,
      label:     f.label,
      pVal:      f.key === "address"
                  ? _address(primary) : (primary?.[f.key] || ""),
      dVal:      f.key === "address"
                  ? _address(duplicate) : (duplicate?.[f.key] || ""),
    })),
  [primary, duplicate]);

  return (
    <div data-testid="cmw-resolver">
      <p className="text-xs mb-3"
          style={{ color: colors.muted }}>
        Pick which value survives on the primary customer.
      </p>
      <div className="rounded"
            style={{ border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-[80px_1fr_1fr_100px] px-3 py-2 text-[10px] uppercase font-bold"
              style={{ background: colors.surfaceSecondary,
                          color: colors.muted }}>
          <div>Field</div>
          <div>Primary</div>
          <div>Duplicate</div>
          <div>Keep</div>
        </div>
        {rows.map((r) => {
          const same = String(r.pVal).trim() === String(r.dVal).trim();
          return (
            <div
              key={r.key}
              data-testid={`cmw-row-${r.key}`}
              className="grid grid-cols-[80px_1fr_1fr_100px] px-3 py-2 items-center text-xs border-b"
              style={{ borderColor: colors.border,
                          color: colors.onSurface }}
            >
              <div className="font-semibold">{r.label}</div>
              <div className="truncate" title={r.pVal || ""}>
                {r.pVal || "—"}
              </div>
              <div className="truncate" title={r.dVal || ""}>
                {r.dVal || "—"}
              </div>
              <div className="flex items-center gap-2 text-[10px] font-semibold">
                <label className="inline-flex items-center gap-1">
                  <input
                    type="radio"
                    data-testid={`cmw-choice-${r.key}-primary`}
                    checked={choices[r.key] === "primary"}
                    onChange={() => setChoices((c) =>
                      ({ ...c, [r.key]: "primary" }))}
                    disabled={same}
                  />
                  P
                </label>
                <label className="inline-flex items-center gap-1">
                  <input
                    type="radio"
                    data-testid={`cmw-choice-${r.key}-duplicate`}
                    checked={choices[r.key] === "duplicate"}
                    onChange={() => setChoices((c) =>
                      ({ ...c, [r.key]: "duplicate" }))}
                    disabled={same}
                  />
                  D
                </label>
              </div>
              {same ? (
                <div className="col-span-4 -mt-1 pl-[80px] text-[10px] italic"
                      data-testid={`cmw-row-${r.key}-same`}
                      style={{ color: colors.muted }}>
                  Values match — no conflict.
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}


function _StepConfirm({
  primary, duplicate, choices, confirmText, setConfirmText,
}) {
  return (
    <div data-testid="cmw-confirm">
      <div
        className="flex items-start gap-2 rounded p-3 mb-3"
        style={{
          background: "rgba(220, 38, 38, .08)",
          border: `1px solid ${colors.error}`,
          color: colors.error,
        }}
      >
        <AlertTriangle size={16} />
        <div className="text-xs">
          <div className="font-bold">This action cannot be undone.</div>
          <div>
            {duplicate?.name || "The duplicate"} will be
            soft-deleted. All related records (jobs, quotes,
            invoices, payments, messages, alerts) will be
            re-parented to <b>{primary?.name}</b>.
          </div>
        </div>
      </div>
      <div className="text-xs mb-2"
            style={{ color: colors.onSurface }}>
        <b>Summary of choices:</b>
      </div>
      <ul className="text-xs list-disc pl-5 mb-3"
           style={{ color: colors.onSurfaceSecondary }}>
        {_FIELDS.map((f) => (
          <li key={f.key} data-testid={`cmw-summary-${f.key}`}>
            {f.label}: keep{" "}
            <b>{choices[f.key] === "duplicate" ? "duplicate" : "primary"}</b>
          </li>
        ))}
      </ul>
      <label className="block text-xs font-semibold mb-1"
              style={{ color: colors.onSurface }}>
        Type <code className="font-mono">MERGE</code> to enable:
      </label>
      <input
        type="text"
        data-testid="cmw-confirm-input"
        value={confirmText}
        onChange={(e) => setConfirmText(e.target.value)}
        placeholder="Type MERGE"
        className="w-full px-3 py-2 text-sm rounded focus:outline-none focus-visible:ring-1"
        style={{
          background: colors.surfaceSecondary,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
      />
    </div>
  );
}
