/**
 * Phase K41 · Feb-2026 — Dashboard tile drill-down modal.
 *
 * Single component, THREE variants (do NOT fork):
 *   • variant="data-integrity"     — dangling-ref rows, resolve inline
 *   • variant="income-by-category" — invoice line items in one category
 *   • variant="income-by-service"  — invoice line items in one service unit
 *
 * Cross-cutting invariants (K41 phase brief):
 *   1. admin + super only.  Backend already gates 403.
 *   2. Modal, NOT a new page.  Wrap in K37 <PortalErrorBoundary> so a
 *      row-render crash never blanks the dashboard.
 *   3. True inline edit — text/number/dropdown cell editors, no sub-
 *      modal.  Blur or Enter to save.  Optimistic UI with rollback on
 *      4xx.  Row fades out on successful resolution (integrity variant).
 *   4. Income variants: qty / unit_price / description / category /
 *      service edits recompute the invoice server-side via the existing
 *      PATCH /api/quotes/{iid}; extended/total/tax/paid_at/payment_method
 *      are LOCKED (read-only, greyed).  We then fire a separate audit
 *      call to POST /api/dashboard/drilldown/line-item-audit so the K41
 *      audit event + K6 completed-job audit both land.
 *   5. Cursor pagination when result count > limit.
 *   6. Every interactive element carries a data-testid.
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import PortalErrorBoundary from "@/components/errors/PortalErrorBoundary";
import { api } from "@/api";
import { colors, money } from "@/theme";

/* ── helpers ─────────────────────────────────────────────────── */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function useDebounced(value, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

function formatMoney(n) {
  try {
    return money(Number(n) || 0);
  } catch {
    const num = Number(n) || 0;
    return `$${num.toFixed(2)}`;
  }
}

function LockedCell({ children, testid }) {
  return (
    <span
      data-testid={testid}
      style={{
        color: colors.muted,
        background: colors.surfaceSecondary,
        padding: "3px 8px",
        borderRadius: 6,
        display: "inline-block",
        fontSize: 12,
      }}
      title="Locked (computed / status field)"
    >
      {children}
    </span>
  );
}

/* ── shared row wrapper — fades out on successful resolution ── */
function RowShell({ children, faded, testid }) {
  return (
    <tr
      data-testid={testid}
      style={{
        opacity: faded ? 0 : 1,
        transition: "opacity 350ms ease",
        borderBottom: `1px solid ${colors.border}`,
      }}
    >
      {children}
    </tr>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Data-integrity variant
   ═══════════════════════════════════════════════════════════════ */
function AssignPicker({ kind, onSelect }) {
  // kind = "customers" | "technicians"
  const [q, setQ] = useState("");
  const debouncedQ = useDebounced(q);
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const url = `/dashboard/drilldown/pickers/${kind}?q=${encodeURIComponent(debouncedQ)}&limit=20`;
    api.get(url).then((r) => setRows(r?.rows || [])).catch(() => setRows([]));
  }, [debouncedQ, kind, open]);

  return (
    <div style={{ position: "relative" }} data-testid={`assign-picker-${kind}`}>
      <Input
        value={q}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => setQ(e.target.value)}
        placeholder={kind === "customers" ? "Search customer…" : "Search technician…"}
        data-testid={`assign-picker-${kind}-input`}
        className="h-8 text-sm"
      />
      {open && rows.length > 0 ? (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            maxHeight: 220,
            overflow: "auto",
            zIndex: 50,
          }}
        >
          {rows.map((r) => (
            <button
              key={r.id}
              type="button"
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50"
              data-testid={`assign-picker-${kind}-option-${r.id}`}
              onMouseDown={(e) => {
                e.preventDefault();
                onSelect(r);
                setOpen(false);
                setQ(r.name || r.email || "");
              }}
            >
              <div style={{ color: colors.onSurface }}>{r.name || r.email}</div>
              {r.email && r.name ? (
                <div style={{ color: colors.muted, fontSize: 11 }}>{r.email}</div>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DataIntegrityRow({ row, refClass, onResolved }) {
  const [action, setAction] = useState(""); // "assign" | "delete"
  const [target, setTarget] = useState(null);
  const [busy, setBusy] = useState(false);
  const [faded, setFaded] = useState(false);
  const [err, setErr] = useState("");

  const pickerKind = refClass === "orphaned_customer_refs" ? "customers" : "technicians";

  const submit = async (act, targetId) => {
    setBusy(true);
    setErr("");
    try {
      await api.post("/dashboard/data-integrity/resolve", {
        ref_class: refClass,
        job_id: row.job_id,
        action: act,
        target_id: targetId || null,
      });
      setFaded(true);
      setTimeout(() => onResolved(row.job_id), 400);
    } catch (e) {
      const msg = e?.data?.detail || e?.message || "Save failed";
      setErr(typeof msg === "string" ? msg : JSON.stringify(msg));
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <RowShell
      faded={faded}
      testid={`di-row-${row.job_id}`}
    >
      <td style={{ padding: "8px 12px", fontSize: 12 }} data-testid={`di-row-${row.job_id}-jobid`}>
        {row.job_id.slice(0, 8)}…
      </td>
      <td style={{ padding: "8px 12px", fontSize: 12 }}>
        {refClass === "orphaned_customer_refs"
          ? row.customer_name_denorm || "(no name)"
          : refClass === "orphaned_technician_refs"
            ? row.technician_name_denorm || "(no name)"
            : row.title || "(untitled)"}
      </td>
      <td style={{ padding: "8px 12px", fontSize: 12 }}>
        {row.scheduled_at || "—"}
      </td>
      <td style={{ padding: "8px 12px", width: 280 }}>
        {action === "assign" ? (
          <AssignPicker
            kind={pickerKind}
            onSelect={(sel) => {
              setTarget(sel);
              submit("assign", sel.id);
            }}
          />
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => setAction("assign")}
              data-testid={`di-row-${row.job_id}-assign-btn`}
            >
              {refClass === "orphaned_customer_refs" ? "Assign customer…" : "Assign tech…"}
            </Button>
            {refClass !== "unassigned_pending_jobs" ? (
              <Button
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => submit("delete")}
                data-testid={`di-row-${row.job_id}-delete-btn`}
              >
                {refClass === "orphaned_customer_refs" ? "Soft-delete job" : "Unassign"}
              </Button>
            ) : null}
          </div>
        )}
        {err ? (
          <div
            data-testid={`di-row-${row.job_id}-error`}
            style={{ color: colors.error, fontSize: 11, marginTop: 4 }}
          >
            {err}
          </div>
        ) : null}
      </td>
    </RowShell>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Income variant row (shared for both by-category + by-service)
   ═══════════════════════════════════════════════════════════════ */
const EDITABLE_INCOME_FIELDS = new Set([
  "description", "quantity", "unit_price", "category",
]);

function IncomeRow({ row, tile, onEdited, onOpenFull }) {
  const [draft, setDraft] = useState({
    description: row.description || "",
    quantity: row.quantity ?? 0,
    unit_price: row.unit_price ?? 0,
    category: row.category || "",
  });
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");
  const [faded, setFaded] = useState(false);
  const originalRef = useRef({ ...draft });

  const commitField = async (field) => {
    if (!EDITABLE_INCOME_FIELDS.has(field)) return;
    const before = originalRef.current[field];
    const after = draft[field];
    if (before === after) return;
    if (row.line_item_id == null && row.line_index == null) {
      setSaveErr("Legacy row — use Open full edit.");
      return;
    }
    setSaving(true);
    setSaveErr("");
    // Optimistic — draft already reflects.  Rollback if API rejects.
    try {
      // Rebuild line_items with only the affected one changed.  The
      // server-side recompute is the source of truth for extended/
      // total/tax; we do NOT pre-compute here.
      const fetched = await api.get(`/quotes/${row.invoice_id}`);
      const items = Array.isArray(fetched?.line_items)
        ? fetched.line_items.map((li) => ({ ...li }))
        : [];
      const idx = row.line_index != null
        ? row.line_index
        : items.findIndex((li) => li.id === row.line_item_id);
      if (idx < 0 || idx >= items.length) {
        throw new Error("Line item not found in current invoice");
      }
      const target = { ...items[idx] };
      if (field === "quantity") target.quantity = Number(after) || 0;
      else if (field === "unit_price") target.unit_price = Number(after) || 0;
      else if (field === "description") target.description = String(after || "");
      else if (field === "category") target.category = String(after || "");
      items[idx] = target;
      const patchBody = { line_items: items };
      // If invoice is paid/sent the PATCH will reject with a 409; the
      // modal surfaces the message and prompts "Open full edit".
      await api.patch(`/quotes/${row.invoice_id}`, patchBody);
      // Fire K41 + K6 audit companion.
      try {
        await api.post("/dashboard/drilldown/line-item-audit", {
          tile,
          invoice_id: row.invoice_id,
          line_index: idx,
          field,
          before,
          after,
        });
      } catch (auditErr) {
        // Audit is best-effort; do NOT block the UX.
        // eslint-disable-next-line no-console
        console.warn("[k41] audit companion failed", auditErr);
      }
      originalRef.current = { ...draft };
      onEdited?.(row, field, before, after);
      // Brief flash to indicate save landed.
      setFaded(true);
      setTimeout(() => setFaded(false), 300);
    } catch (e) {
      // Rollback the draft to the last-good value.
      setDraft((d) => ({ ...d, [field]: before }));
      const detail = e?.data?.detail;
      const msg = typeof detail === "string" ? detail
        : detail?.error || detail?.message || e?.message || "Save failed";
      setSaveErr(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const bindText = (field) => ({
    value: draft[field] ?? "",
    onChange: (e) => setDraft((d) => ({ ...d, [field]: e.target.value })),
    onBlur: () => commitField(field),
    onKeyDown: (e) => {
      if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
      if (e.key === "Escape") {
        setDraft((d) => ({ ...d, [field]: originalRef.current[field] }));
        e.currentTarget.blur();
      }
    },
    disabled: saving,
    className: "h-8 text-sm",
    "data-testid": `income-row-${row.invoice_id}-${row.line_index ?? "x"}-${field}`,
  });

  return (
    <RowShell
      faded={faded}
      testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}`}
    >
      <td style={{ padding: "6px 10px", fontSize: 12, whiteSpace: "nowrap" }}>
        {(row.date || "").slice(0, 10)}
      </td>
      <td style={{ padding: "6px 10px", fontSize: 12 }}>
        {row.customer_name || (row.customer_id || "").slice(0, 8)}
      </td>
      <td style={{ padding: "6px 10px", fontSize: 12 }}>
        {row.invoice_number || row.invoice_id.slice(0, 8)}
      </td>
      <td style={{ padding: "6px 10px", minWidth: 200 }}>
        <Input {...bindText("description")} />
      </td>
      <td style={{ padding: "6px 10px" }}>
        <Input {...bindText("category")} style={{ maxWidth: 140 }} />
      </td>
      <td style={{ padding: "6px 10px", fontSize: 12 }}>
        {row.service_category || "—"}
      </td>
      <td style={{ padding: "6px 10px" }}>
        <Input {...bindText("quantity")} type="number" step="1" style={{ maxWidth: 80 }} />
      </td>
      <td style={{ padding: "6px 10px" }}>
        <Input {...bindText("unit_price")} type="number" step="0.01" style={{ maxWidth: 100 }} />
      </td>
      <td style={{ padding: "6px 10px", fontSize: 12, fontFamily: "monospace" }}>
        <LockedCell testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-extended`}>
          {formatMoney(row.extended)}
        </LockedCell>
      </td>
      <td style={{ padding: "6px 10px", fontSize: 12, fontFamily: "monospace" }}>
        <LockedCell testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-invoice-total`}>
          {formatMoney(row.invoice_total)}
        </LockedCell>
      </td>
      <td style={{ padding: "6px 10px", fontSize: 12 }}>
        <LockedCell testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-status`}>
          {row.invoice_status || "—"}
          {row.payment_status ? ` · ${row.payment_status}` : ""}
        </LockedCell>
      </td>
      <td style={{ padding: "6px 10px" }}>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => onOpenFull(row)}
          data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-open-full`}
        >
          Open full edit
        </Button>
        {saveErr ? (
          <div
            style={{ color: colors.error, fontSize: 11, marginTop: 2 }}
            data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-error`}
          >
            {saveErr}
          </div>
        ) : null}
      </td>
    </RowShell>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Main modal
   ═══════════════════════════════════════════════════════════════ */
function ModalBody({ variant, params, onOpenFullEdit }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState(null);
  const [nextCursor, setNextCursor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const url = useMemo(() => {
    if (variant === "data-integrity") {
      const c = params?.issueClass || "orphaned_customer_refs";
      return `/dashboard/data-integrity/rows?class=${encodeURIComponent(c)}&limit=100${cursor ? `&cursor=${cursor}` : ""}`;
    }
    if (variant === "income-by-category") {
      return `/dashboard/income/by-category/rows?category=${encodeURIComponent(params.category)}&from=${params.from}&to=${params.to}&limit=100${cursor ? `&cursor=${cursor}` : ""}`;
    }
    return `/dashboard/income/by-service/rows?service_category_id=${encodeURIComponent(params.service_category_id)}&from=${params.from}&to=${params.to}&limit=100${cursor ? `&cursor=${cursor}` : ""}`;
  }, [variant, params, cursor]);

  useEffect(() => {
    setLoading(true);
    setErr("");
    api.get(url)
      .then((r) => {
        setRows((prev) => cursor ? [...prev, ...(r.rows || [])] : (r.rows || []));
        setTotal(r.total || 0);
        setNextCursor(r.next_cursor || null);
      })
      .catch((e) => setErr(e?.message || "Load failed"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const handleResolved = useCallback((jobId) => {
    setRows((prev) => prev.filter((r) => r.job_id !== jobId));
  }, []);

  if (variant === "data-integrity") {
    return (
      <div data-testid="drilldown-body-data-integrity">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: `2px solid ${colors.border}` }}>
              <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, color: colors.muted }}>JOB</th>
              <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, color: colors.muted }}>
                {params?.issueClass === "orphaned_customer_refs" ? "CUSTOMER (DENORM)"
                  : params?.issueClass === "orphaned_technician_refs" ? "TECHNICIAN (DENORM)"
                    : "TITLE"}
              </th>
              <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, color: colors.muted }}>SCHEDULED</th>
              <th style={{ padding: "8px 12px", textAlign: "left", fontSize: 11, color: colors.muted }}>ACTIONS</th>
            </tr>
          </thead>
          <tbody data-testid="drilldown-di-tbody">
            {rows.map((r) => (
              <DataIntegrityRow
                key={r.job_id}
                row={r}
                refClass={params?.issueClass}
                onResolved={handleResolved}
              />
            ))}
          </tbody>
        </table>
        {loading ? <div style={{ padding: 12, color: colors.muted }} data-testid="drilldown-loading">Loading…</div> : null}
        {err ? <div style={{ padding: 12, color: colors.error }} data-testid="drilldown-error">{err}</div> : null}
        {!loading && rows.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: colors.muted }} data-testid="drilldown-empty">
            No dangling refs in this class.  Nothing to fix.
          </div>
        ) : null}
        {nextCursor ? (
          <div style={{ padding: 12, textAlign: "center" }}>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setCursor(nextCursor)}
              data-testid="drilldown-load-more"
            >
              Load more ({total - rows.length} remaining)
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div data-testid={`drilldown-body-${variant}`}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: `2px solid ${colors.border}` }}>
              {["DATE", "CUSTOMER", "INVOICE #", "DESCRIPTION", "CATEGORY",
                 "SERVICE UNIT", "QTY", "UNIT PRICE", "EXTENDED",
                 "INVOICE TOTAL", "STATUS", ""].map((h) => (
                <th key={h}
                    style={{ padding: "8px 10px", textAlign: "left",
                              fontSize: 10, color: colors.muted, whiteSpace: "nowrap" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody data-testid={`drilldown-${variant}-tbody`}>
            {rows.map((r) => (
              <IncomeRow
                key={`${r.invoice_id}-${r.line_index ?? "x"}`}
                row={r}
                tile={variant}
                onOpenFull={onOpenFullEdit}
              />
            ))}
          </tbody>
        </table>
      </div>
      {loading ? <div style={{ padding: 12, color: colors.muted }} data-testid="drilldown-loading">Loading…</div> : null}
      {err ? <div style={{ padding: 12, color: colors.error }} data-testid="drilldown-error">{err}</div> : null}
      {!loading && rows.length === 0 ? (
        <div style={{ padding: 24, textAlign: "center", color: colors.muted }} data-testid="drilldown-empty">
          No line items in this bucket for the selected range.
        </div>
      ) : null}
      {nextCursor ? (
        <div style={{ padding: 12, textAlign: "center" }}>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setCursor(nextCursor)}
            data-testid="drilldown-load-more"
          >
            Load more ({total - rows.length} remaining)
          </Button>
        </div>
      ) : null}
    </div>
  );
}

const VARIANT_TITLES = {
  "data-integrity": "Data Integrity — dangling refs",
  "income-by-category": "Income by Category — drill down",
  "income-by-service": "Income by Service Category — drill down",
};

export default function DashboardDrillDownModal({
  open,
  onClose,
  variant,
  params,
}) {
  const openFullEdit = useCallback((row) => {
    if (!row?.invoice_id) return;
    // Existing invoice edit page lives at /admin/invoice-edit/<id>
    // via K35 modernization; if unavailable in preview, the browser
    // still opens the invoice view. Do NOT invent a new route.
    window.open(`/invoices/${row.invoice_id}`, "_blank", "noopener");
  }, []);

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose?.(); }}>
      <DialogContent
        className="max-w-6xl"
        data-testid={`dashboard-drilldown-modal-${variant}`}
      >
        <DialogHeader>
          <DialogTitle>{VARIANT_TITLES[variant]}</DialogTitle>
        </DialogHeader>
        <PortalErrorBoundary
          label="dashboard-drilldown"
          resetKey={`${variant}-${JSON.stringify(params || {})}`}
        >
          <ModalBody
            variant={variant}
            params={params}
            onOpenFullEdit={openFullEdit}
          />
        </PortalErrorBoundary>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            data-testid={`dashboard-drilldown-close-${variant}`}
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
