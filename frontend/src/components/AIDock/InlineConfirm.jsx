/**
 * Feb-2026 · MARCO-AI-CHAT Phase B — inline Confirm/Cancel card.
 *
 * Rendered inside Marco's assistant-message bubble when the message
 * carries a ``pending_confirmation`` payload. Shows the compact
 * dry-run summary (recipient, invoice number, customer count, phones
 * masked, etc.) and offers two actions:
 *   - "Confirm & Send" → POST /ai-employees/actions/{action_id}/approve
 *   - "Cancel"         → POST /ai-employees/actions/{action_id}/reject
 *
 * Other 8 personas keep rendering the existing top-of-pane chip strip
 * for ``ai_employee_actions`` with other ``kind`` values — this card
 * only renders when the parent passes ``pending_confirmation`` from a
 * Marco assistant message (``kind === "marco_inline_confirm"``).
 */
import React from "react";
import { Check, X, Sparkles, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function _formatPayload(payload) {
  if (!payload || typeof payload !== "object") return null;
  const rows = [];
  if (payload.recipient_masked) {
    rows.push({ label: "Recipient", value: payload.recipient_masked });
  }
  if (payload.invoice_number) {
    rows.push({ label: "Invoice", value: payload.invoice_number });
  }
  if (payload.quote_number) {
    rows.push({ label: "Estimate", value: payload.quote_number });
  }
  if (payload.total != null) {
    rows.push({ label: "Total",
                value: `$${Number(payload.total).toFixed(2)}` });
  }
  if (payload.balance != null && payload.balance !== payload.total) {
    rows.push({ label: "Balance",
                value: `$${Number(payload.balance).toFixed(2)}` });
  }
  if (payload.when) {
    rows.push({ label: "When",
                value: `${payload.when}${payload.date ? ` (${payload.date})` : ""}` });
  }
  if (payload.customer_count != null) {
    rows.push({ label: "Customers", value: String(payload.customer_count) });
  }
  if (Array.isArray(payload.phones_masked) && payload.phones_masked.length > 0) {
    const preview = payload.phones_masked.slice(0, 5).join(", ");
    const more = payload.phones_masked.length > 5
      ? ` (+${payload.phones_masked.length - 5} more)` : "";
    rows.push({ label: "Phones", value: `${preview}${more}` });
  }
  if (payload.subject_preview) {
    rows.push({ label: "Subject", value: payload.subject_preview });
  }
  if (payload.message_preview) {
    rows.push({ label: "Message", value: payload.message_preview });
  }
  return rows;
}

export default function InlineConfirm({ pending, onDecided }) {
  const [state, setState] = React.useState("idle"); // idle | confirming | done | error
  const [result, setResult] = React.useState(null);
  const [err, setErr] = React.useState(null);

  if (!pending || !pending.action_id) return null;
  const rows = _formatPayload(pending.payload);

  const call = async (decision) => {
    if (state === "confirming" || state === "done") return;
    setState("confirming");
    setErr(null);
    try {
      const r = await api.post(
        `/ai-employees/actions/${pending.action_id}/${decision}`,
        {},
      );
      setResult({ decision, row: r });
      setState("done");
      if (typeof onDecided === "function") onDecided(decision, r);
    } catch (e) {
      setErr(e?.message || `${decision} failed`);
      setState("error");
    }
  };

  if (state === "done") {
    const decision = result?.decision || "confirmed";
    const label = decision === "approve" ? "Sent ✓" : "Cancelled";
    const resKind = (result?.row?.result?.kind) || "";
    const ok = !resKind.includes("failed");
    return (
      <div
        className="mt-2 p-2 rounded-lg text-xs flex items-center gap-2"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          color: ok ? colors.onSurface : colors.danger,
        }}
        data-testid={`ai-dock-inline-confirm-done-${pending.action_id}`}
      >
        {ok ? <Check size={12} /> : <AlertTriangle size={12} />}
        <span>{label}{resKind ? ` · ${resKind}` : ""}</span>
      </div>
    );
  }

  return (
    <div
      className="mt-2 p-2 rounded-lg text-xs"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        color: colors.onSurface,
      }}
      data-testid={`ai-dock-inline-confirm-${pending.action_id}`}
    >
      <div className="font-semibold uppercase mb-1"
            style={{ color: colors.muted, fontSize: 10 }}>
        Confirm action
      </div>
      {rows && rows.length > 0 ? (
        <ul className="space-y-0.5 mb-2">
          {rows.map((r) => (
            <li key={r.label} className="flex gap-1">
              <span className="font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                {r.label}:
              </span>
              <span style={{ color: colors.onSurface, overflowWrap: "anywhere" }}>
                {r.value}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {err ? (
        <div className="mb-1 text-[11px]" style={{ color: colors.danger }}
             data-testid={`ai-dock-inline-confirm-error-${pending.action_id}`}>
          {err}
        </div>
      ) : null}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => call("approve")}
          disabled={state === "confirming"}
          className="rounded-lg px-2 py-1 text-xs font-semibold flex items-center gap-1"
          style={{
            backgroundColor: colors.brand,
            color: colors.onBrand,
            opacity: state === "confirming" ? 0.6 : 1,
            cursor: state === "confirming" ? "wait" : "pointer",
          }}
          data-testid={`ai-dock-inline-confirm-approve-${pending.action_id}`}
        >
          {state === "confirming" ? <Sparkles size={12} /> : <Check size={12} />}
          Confirm & Send
        </button>
        <button
          type="button"
          onClick={() => call("reject")}
          disabled={state === "confirming"}
          className="rounded-lg px-2 py-1 text-xs flex items-center gap-1"
          style={{
            backgroundColor: colors.surfaceMuted,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
            cursor: state === "confirming" ? "wait" : "pointer",
          }}
          data-testid={`ai-dock-inline-confirm-cancel-${pending.action_id}`}
        >
          <X size={12} /> Cancel
        </button>
      </div>
    </div>
  );
}
