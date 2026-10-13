/**
 * Feb-2026 · MergeDialog — the side-by-side, admin-pick-winner
 * merge UI backed by `POST /api/customers/{winner}/merge-from/
 * {loser}` (SHA d8dd7eb49 + prior).
 *
 * Two entry points share this dialog:
 *   1. The Customers-list "Duplicates" tab's inline merge button
 *      (same session, shipped in `CustomersList.jsx` alongside
 *      this file).
 *   2. The portal-invite `ResolveDuplicateDialog` "Option B —
 *      merge both records" placeholder (SHA 20370d86d) is
 *      closed out: its "Coming soon" tooltip is replaced with
 *      a working button that opens this dialog.
 *
 * Dialog contract — props (all required unless noted):
 *   • `open`      — controlled visibility.
 *   • `onClose`   — called with no args on close (cancel or
 *                   success).
 *   • `onMerged`  — called with the merge-endpoint response on
 *                   success (optional).
 *   • `customers` — array of 2+ CustomerSummary objects (per
 *                   the detection endpoint's shape).
 *   • `matchReasons` — array of strings (`"name_exact" | "phone"
 *                   | "email" | "name_fuzzy"`) rendered as
 *                   context chips in the dialog header.
 *   • `canExecute` — boolean; when false, the "Merge" submit
 *                   button is hidden (manager sees the dialog
 *                   read-only).
 *
 * UI flow:
 *   1. Admin picks winner via radio button on each column
 *      header.
 *   2. Per scalar field, admin picks per-column radio.  Non-
 *      conflicting fields show the winner's value with no
 *      override.
 *   3. If any side carries `stripe_customer_id`, a Stripe-remap
 *      notice renders above the submit row.
 *   4. Admin types the loser's name into the confirm input
 *      (case-insensitive, whitespace-collapsed match on client
 *      so the submit button only enables when the type matches
 *      the backend's `_canon_name` contract).
 *   5. If the backend returns the 24h recurring block, a yellow
 *      warning banner surfaces the blocking template ids +
 *      offers a `force` checkbox.
 *   6. Submit → `POST`.  On 200, `onMerged(response)` fires then
 *      `onClose()`.
 */
import React, { useMemo, useState, useCallback } from "react";

// Scalar fields the dialog surfaces for admin-pick merging.
// Metadata fields (`id`, `tenant_id`, `created_at`, etc.) are
// deliberately omitted — the backend silently drops any
// metadata key from `field_overrides` for invariant safety.
const _MERGE_FIELDS = [
  { key: "name", label: "Name" },
  { key: "email", label: "Email" },
  { key: "phone", label: "Phone" },
  { key: "address", label: "Address" },
  { key: "stripe_customer_id", label: "Stripe customer id" },
  { key: "notes", label: "Notes" },
];


function _canonLoose(s) {
  // Light client-side mirror of the backend `_canon_name`
  // so the confirm-name gate is honest at the submit button
  // without a round-trip.  Case + whitespace + ampersand.
  if (!s) return "";
  return String(s).trim().toLowerCase()
    .replace(/\s*&\s*/g, " and ")
    .replace(/\s+/g, " ");
}


export function MergeDialog({
  open, onClose, onMerged,
  customers = [], matchReasons = [],
  canExecute = true,
}) {
  const twoOrMore = Array.isArray(customers) && customers.length >= 2;

  // Winner selection — defaults to the FIRST customer in the
  // array (detection endpoint orders by created_at asc, so the
  // oldest row is the default winner — operators usually keep
  // the oldest).
  const [winnerId, setWinnerId] = useState(
    twoOrMore ? customers[0].id : null,
  );
  const loser = useMemo(
    () => twoOrMore
      ? customers.find((c) => c.id !== winnerId) || customers[1]
      : null,
    [customers, winnerId, twoOrMore],
  );

  // Field pick state — keyed by field name, value is the id
  // of the column whose value should be used.  Defaults to
  // the winner column.
  const [fieldPicks, setFieldPicks] = useState({});
  const setPick = useCallback((field, cid) => {
    setFieldPicks((p) => ({ ...p, [field]: cid }));
  }, []);
  const effectivePick = useCallback(
    (field) => fieldPicks[field] || winnerId,
    [fieldPicks, winnerId],
  );

  const [confirmName, setConfirmName] = useState("");
  const confirmOk = useMemo(() => {
    if (!loser) return false;
    return _canonLoose(confirmName) === _canonLoose(loser.name);
  }, [confirmName, loser]);

  const anyStripe = customers.some((c) => !!c.stripe_customer_id);

  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState(null);
  const [blockingTemplates, setBlockingTemplates] = useState([]);

  const handleSubmit = useCallback(async () => {
    if (!twoOrMore || !winnerId || !loser || !confirmOk) return;
    setBusy(true);
    setServerError(null);
    try {
      // Build field_overrides from the picks — only include
      // entries where the picked column differs from the
      // winner (so metadata is minimal AND the backend's
      // "non-conflicting fields keep the winner's value"
      // invariant holds without any over-sends).
      const overrides = {};
      const winnerRow = customers.find((c) => c.id === winnerId);
      for (const f of _MERGE_FIELDS) {
        const picked = effectivePick(f.key);
        if (picked === winnerId) continue;
        const pickedRow = customers.find((c) => c.id === picked);
        if (!pickedRow) continue;
        if (pickedRow[f.key] !== undefined
            && pickedRow[f.key] !== winnerRow?.[f.key]) {
          overrides[f.key] = pickedRow[f.key];
        }
      }
      const BASE = process.env.REACT_APP_BACKEND_URL || "";
      const TOKEN = (typeof localStorage !== "undefined"
          ? (localStorage.getItem("token") || "") : "");
      const resp = await fetch(
        `${BASE}/api/customers/${winnerId}/merge-from/${loser.id}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
          },
          body: JSON.stringify({
            field_overrides: overrides,
            confirm_name: confirmName,
            force,
          }),
        },
      );
      const envelope = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail = envelope?.detail || envelope || {};
        if (detail.error_code
            === "merge_blocked_recent_recurring_activity") {
          setBlockingTemplates(detail.blocking_templates || []);
          setServerError(detail.message
            || "Loser has recent recurring generation.");
        } else {
          setServerError(detail.message
            || detail.error_code
            || `Merge failed (HTTP ${resp.status}).`);
        }
        return;
      }
      if (typeof onMerged === "function") {
        try { onMerged(envelope); } catch { /* noop */ }
      }
      onClose && onClose();
    } finally {
      setBusy(false);
    }
  }, [customers, winnerId, loser, confirmOk, confirmName,
      effectivePick, force, onMerged, onClose, twoOrMore]);

  if (!open || !twoOrMore) return null;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
      data-testid="merge-dialog"
    >
      <div
        className="w-full max-w-5xl rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-labelledby="merge-dialog-title"
      >
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <h2 id="merge-dialog-title"
                 className="text-xl font-bold">
              Merge duplicate customers
            </h2>
            <p className="text-xs text-gray-600 mt-1">
              Pick the winner column, then resolve any
              conflicting fields.  Child records (jobs,
              invoices, payments, properties, and 8 more
              collections) move to the winner.  Soft-deleted
              with 90-day rollback.
            </p>
            {matchReasons?.length ? (
              <div
                className="mt-2 flex flex-wrap gap-1"
                data-testid="merge-dialog-match-reasons"
              >
                {matchReasons.map((r) => (
                  <span key={r}
                         className="text-[10px] font-semibold uppercase tracking-wider rounded-full px-2 py-0.5"
                         style={{ backgroundColor: "#DBEAFE",
                                   color: "#1E3A8A" }}>
                    {r.replace("_", " ")}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => onClose && onClose()}
            className="text-gray-500 hover:text-gray-800 text-xl leading-none"
            data-testid="merge-dialog-close-btn"
          >×</button>
        </div>

        {/* Side-by-side column table */}
        <div className="overflow-x-auto border rounded-lg">
          <table className="w-full text-sm"
                   data-testid="merge-dialog-columns">
            <thead>
              <tr style={{ backgroundColor: "#F3F4F6" }}>
                <th className="text-left px-3 py-2 w-40">Field</th>
                {customers.map((c) => {
                  const isWinner = c.id === winnerId;
                  return (
                    <th key={c.id}
                         className="text-left px-3 py-2 border-l"
                         style={{
                           backgroundColor: isWinner
                             ? "#DCFCE7" : undefined,
                         }}>
                      <label
                        className="flex items-center gap-2 cursor-pointer"
                        data-testid={`merge-dialog-winner-radio-label-${c.id}`}
                      >
                        <input
                          type="radio"
                          name="merge-winner"
                          checked={isWinner}
                          onChange={() => setWinnerId(c.id)}
                          data-testid={`merge-dialog-winner-radio-${c.id}`}
                        />
                        <span className="font-semibold">
                          {c.name || "(unnamed)"}
                        </span>
                      </label>
                      <div className="text-[10px] text-gray-600 mt-1 font-normal">
                        {c.status || "active"} ·{" "}
                        {c.child_record_counts
                          ? Object.entries(c.child_record_counts)
                              .filter(([, n]) => n > 0)
                              .map(([k, n]) => `${k}: ${n}`)
                              .join(", ") || "no child records"
                          : null}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {_MERGE_FIELDS.map((f) => {
                const values = customers.map((c) => c[f.key] ?? "");
                const uniq = Array.from(new Set(values.map(
                  (v) => (v == null ? "" : String(v)),
                )));
                const isConflict = uniq.length > 1
                                     && uniq.some((v) => v !== "");
                return (
                  <tr key={f.key}
                       data-testid={`merge-dialog-field-row-${f.key}`}
                       className={isConflict ? "bg-amber-50" : ""}>
                    <td className="px-3 py-2 font-semibold text-xs text-gray-700">
                      {f.label}
                      {isConflict ? (
                        <span className="ml-1 text-[10px] text-amber-700">
                          conflict
                        </span>
                      ) : null}
                    </td>
                    {customers.map((c) => {
                      const picked = effectivePick(f.key) === c.id;
                      return (
                        <td key={c.id}
                             className="px-3 py-2 border-l text-xs">
                          <label
                            className="flex items-start gap-2 cursor-pointer"
                            data-testid={`merge-dialog-field-cell-${f.key}-${c.id}`}
                          >
                            {isConflict ? (
                              <input
                                type="radio"
                                name={`merge-field-${f.key}`}
                                checked={picked}
                                onChange={() => setPick(f.key, c.id)}
                                data-testid={`merge-dialog-field-radio-${f.key}-${c.id}`}
                              />
                            ) : null}
                            <span className={
                              picked ? "font-semibold" : "text-gray-600"
                            }>
                              {c[f.key] ?? ""}
                              {!c[f.key] ? (
                                <em className="text-gray-400">
                                  (empty)
                                </em>
                              ) : null}
                            </span>
                          </label>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Stripe remap notice */}
        {anyStripe ? (
          <div
            className="mt-3 rounded-lg p-3 text-xs"
            style={{ backgroundColor: "#DBEAFE", color: "#1E3A8A" }}
            data-testid="merge-dialog-stripe-notice"
          >
            One or more customers has a Stripe customer id.
            Payment methods will be remapped to the winner on
            Stripe's side.  If Stripe rejects the remap, the
            entire merge is rolled back automatically.
          </div>
        ) : null}

        {/* 24h recurring block banner */}
        {blockingTemplates?.length ? (
          <div
            className="mt-3 rounded-lg p-3 text-xs"
            style={{ backgroundColor: "#FEF3C7", color: "#78350F" }}
            data-testid="merge-dialog-recurring-block-banner"
          >
            <strong>Merge blocked:</strong> the loser has
            recurring templates generated in the last 24 hours.
            <ul className="list-disc pl-5 mt-1">
              {blockingTemplates.map((t) => (
                <li key={t.template_id}>
                  template <code>{t.template_id}</code> —{" "}
                  last generated through{" "}
                  {t.last_generated_through}
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2 mt-2 cursor-pointer">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                data-testid="merge-dialog-force-override"
              />
              <span>I understand — override and merge anyway</span>
            </label>
          </div>
        ) : null}

        {/* Confirm-name gate */}
        <div className="mt-4">
          <label
            htmlFor="merge-dialog-confirm-name"
            className="block text-xs font-semibold text-gray-700 mb-1"
          >
            Type the loser's name to confirm (case-insensitive,
            whitespace-collapsed): <code>{loser?.name || ""}</code>
          </label>
          <input
            id="merge-dialog-confirm-name"
            type="text"
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm"
            placeholder={loser?.name || ""}
            data-testid="merge-dialog-confirm-name"
          />
        </div>

        {/* Server error */}
        {serverError ? (
          <div
            className="mt-3 text-xs text-red-700"
            data-testid="merge-dialog-server-error"
          >
            {serverError}
          </div>
        ) : null}

        {/* Actions */}
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => onClose && onClose()}
            className="px-4 py-2 rounded-md border text-sm"
            data-testid="merge-dialog-cancel-btn"
          >Cancel</button>
          {canExecute ? (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!confirmOk || busy || !winnerId}
              className="px-4 py-2 rounded-md text-sm font-semibold text-white"
              style={{
                backgroundColor: (!confirmOk || busy || !winnerId)
                  ? "#9CA3AF" : "#1F2937",
                opacity: (!confirmOk || busy || !winnerId) ? 0.7 : 1,
              }}
              data-testid="merge-dialog-submit-btn"
            >
              {busy ? "Merging…" : "Merge"}
            </button>
          ) : (
            <span
              className="text-xs text-gray-600"
              data-testid="merge-dialog-manager-readonly"
            >
              Admin-only action — contact an admin to execute merge.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}


export default MergeDialog;
