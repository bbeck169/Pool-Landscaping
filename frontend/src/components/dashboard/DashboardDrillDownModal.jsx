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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import PortalErrorBoundary from "@/components/errors/PortalErrorBoundary";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors, money } from "@/theme";

/* ── helpers ─────────────────────────────────────────────────── */
const _EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/* K41b — client-minted UUID v4 for bulk-batch idempotency. */
function makeBulkBatchId() {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      return crypto.randomUUID();
    }
  } catch { /* fallthrough */ }
  return `bulk-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/* K41b — page-scope bulk cap must match backend _BULK_CAP. */
const BULK_CAP = 100;

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

function DataIntegrityRow({ row, refClass, onResolved, selected, onToggleSelect, faded: externalFaded }) {
  const [action, setAction] = useState(""); // "assign" | "delete"
  const [_target, setTarget] = useState(null);
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
      faded={faded || externalFaded}
      testid={`di-row-${row.job_id}`}
    >
      <td style={{ padding: "8px 8px", width: 32 }}>
        <Checkbox
          checked={!!selected}
          onCheckedChange={(v) => onToggleSelect?.(row.job_id, !!v)}
          aria-label={`Select job ${row.job_id}`}
          data-testid={`di-row-${row.job_id}-select`}
        />
      </td>
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
                onClick={() => submit(refClass === "orphaned_customer_refs"
                                        ? "hard_delete" : "delete")}
                data-testid={`di-row-${row.job_id}-delete-btn`}
              >
                {refClass === "orphaned_customer_refs" ? "Hard-delete job" : "Unassign"}
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

/* K48 · Feb-2026 — invoice status values that require an
 * acknowledgement on the backend PATCH pipeline before a line-item
 * mutation is accepted (K41 lock rule for extended / invoice_total).
 * Business Unit re-classification is money-NEUTRAL — total /
 * subtotal / tax are unchanged by a category-only edit — so the
 * dropdown stays editable in the revenue-by-category drill-down
 * even on ``paid`` / ``sent`` rows.  We simply carry the required
 * confirmation flags (``confirm_edit_sent`` /
 * ``confirm_edit_paid_invoice_number``) through to the PATCH.
 *
 * (Original K48 ship 2026-02-XX rendered a read-only chip here;
 * verified by tester on preview 2026-02-XX and reverted because
 * ~100% of rows in a revenue drill-down are paid, making the
 * feature unusable.  New rule: always render the Select; hard-
 * reject only ``void`` / ``cancelled`` where the backend refuses
 * even with confirmations.)
 */
const K48_TERMINAL_STATUSES = new Set(["void", "cancelled"]);
const K48_CONFIRM_SENT_STATUSES = new Set(["sent"]);
const K48_CONFIRM_PAID_STATUSES = new Set([
  "paid", "partially_paid", "refunded",
]);
function _k48StatusFlags(row) {
  const s = String(row?.invoice_status || "").toLowerCase();
  const p = String(row?.payment_status || "").toLowerCase();
  const any = (set) => set.has(s) || set.has(p);
  return {
    isTerminal: any(K48_TERMINAL_STATUSES),
    needsSentConfirm: any(K48_CONFIRM_SENT_STATUSES),
    needsPaidConfirm: any(K48_CONFIRM_PAID_STATUSES),
  };
}

function IncomeRow({
  row, tile, onEdited, onOpenFull,
  /* K48 additions — only meaningful for variant="income-by-category". */
  variant,
  incomeCategories = [],
  currentBucket = null,
  /* INCOME-DRILLDOWN-EDIT · Feb-2026 — tenant-scoped service_categories
   * drive the new Service Unit Select in BOTH income variants.  Empty
   * list falls back to a read-only display so a fetch failure never
   * crashes the row. */
  serviceCategories = [],
}) {
  /* Atomic A2 · Feb-2026 — role-aware auto-pass of the paid/sent
   * confirmation flags for CATEGORY edits only.  Privileged roles
   * (admin, super_admin, manager, owner) carry both
   * ``confirm_edit_sent`` and ``acknowledged_lock_bypass`` on
   * category PATCH bodies so sent / accepted invoice categories
   * can be re-classified without the 409 friction dialog.  Non-
   * category fields keep the existing status gate (regression
   * lock), and non-privileged roles never get the auto-flags. */
  const { role } = useAuth() || {};
  const canBypassCategoryConfirm = [
    "admin", "super_admin", "manager", "owner",
  ].includes(String(role || "").toLowerCase());
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

  /* K48 — Business Unit editor state.  ``buCategoryId`` reflects the
   * live selection (income_categories.id).  We resolve it from the
   * row's ``income_category_id`` first, falling back to a name-match
   * against ``incomeCategories`` for legacy rows that only carry the
   * denormalized name in ``category``.  ``movedTo`` holds the name
   * of the destination bucket AFTER a successful save so the row can
   * stay in place with a "Moved to X" indicator (K48 default per
   * user brief). */
  const k48Status = _k48StatusFlags(row);
  const isRevenueVariant = variant === "income-by-category";
  const resolveInitialBuId = () => {
    // K48 Round-4 · Feb-2026 — prefer the invoice-level
    // ``business_unit`` written by ``commitBusinessUnit`` over the
    // legacy per-line-item ``income_category_id`` / ``category``
    // fallbacks.  ``business_unit`` is the K48 source of truth on
    // the wire; the fallbacks stay in place so legacy rows that
    // predate the write-path fix (or rows that were re-tagged via
    // the earlier Path-B pipeline) still hydrate correctly.
    const bu = (row?.business_unit || "").trim().toLowerCase();
    if (bu) {
      const buHit = incomeCategories.find(
        (c) => (c?.name || "").trim().toLowerCase() === bu,
      );
      if (buHit) return buHit.id;
    }
    const direct = (row?.income_category_id || "").trim();
    if (direct) return direct;
    const nm = (row?.category || "").trim().toLowerCase();
    if (!nm) return "";
    const hit = incomeCategories.find(
      (c) => (c?.name || "").trim().toLowerCase() === nm,
    );
    return hit ? hit.id : "";
  };
  const [buCategoryId, setBuCategoryId] = useState(resolveInitialBuId);
  const [movedTo, setMovedTo] = useState(null);
  const buOriginalRef = useRef(buCategoryId);

  /* INCOME-DRILLDOWN-EDIT · Feb-2026 — Service Unit dropdown state.
   * Mirrors the BU resolver pattern: prefer the canonical FK if the
   * backend projects it, otherwise fall back to a case-insensitive
   * match against the ``serviceCategories`` list using the
   * denormalized ``service_category`` display name.  Empty list
   * (fetch failure) → svc id stays "" and the Select renders a
   * placeholder without crashing. */
  const resolveInitialSvcId = () => {
    const direct = (row?.service_category_id || "").trim();
    if (direct) return direct;
    const nm = (row?.service_category || "").trim().toLowerCase();
    if (!nm) return "";
    const hit = serviceCategories.find(
      (c) => (c?.name || "").trim().toLowerCase() === nm,
    );
    return hit ? hit.id : "";
  };
  const [svcCategoryId, setSvcCategoryId] = useState(resolveInitialSvcId);
  const svcOriginalRef = useRef(svcCategoryId);

  /* INCOME-DRILLDOWN-EDIT · Feb-2026 — re-resolve Service Unit id
   * once the async ``serviceCategories`` fetch lands (parallel to
   * the BU resolver above).  Skips the upgrade when the user has
   * already committed a change on this row. */
  useEffect(() => {
    if (svcCategoryId) return;
    if (!Array.isArray(serviceCategories) || serviceCategories.length === 0) return;
    const resolved = resolveInitialSvcId();
    if (resolved && resolved !== svcCategoryId) {
      setSvcCategoryId(resolved);
      svcOriginalRef.current = resolved;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceCategories]);

  /* INCOME-DRILLDOWN-EDIT · Feb-2026 — line-level Category (income
   * category) dropdown state for the ``income-by-service`` variant.
   * The revenue-by-category variant uses the invoice-level BU
   * Select above and doesn't render this one. */
  const resolveInitialLineCatId = () => {
    const direct = (row?.income_category_id || "").trim();
    if (direct) return direct;
    const nm = (row?.category || "").trim().toLowerCase();
    if (!nm) return "";
    const hit = incomeCategories.find(
      (c) => (c?.name || "").trim().toLowerCase() === nm,
    );
    return hit ? hit.id : "";
  };
  const [lineCatId, setLineCatId] = useState(resolveInitialLineCatId);
  const lineCatOriginalRef = useRef(lineCatId);

  useEffect(() => {
    if (lineCatId) return;
    if (!Array.isArray(incomeCategories) || incomeCategories.length === 0) return;
    const resolved = resolveInitialLineCatId();
    if (resolved && resolved !== lineCatId) {
      setLineCatId(resolved);
      lineCatOriginalRef.current = resolved;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomeCategories]);

  // K48 Round-4 · Feb-2026 — re-resolve the initial BU id once the
  // async ``incomeCategories`` fetch lands.  ``useState`` snapshots
  // the initial value at mount when the categories list is still
  // empty, so name-based lookups (``business_unit`` / ``category``)
  // return "" even though a match would exist post-fetch.  Only
  // upgrade when the user hasn't yet edited the row (guarded via
  // ``buOriginalRef`` — a live commit updates the ref).
  useEffect(() => {
    if (!isRevenueVariant) return;
    if (buCategoryId) return;
    if (!Array.isArray(incomeCategories) || incomeCategories.length === 0) return;
    const resolved = resolveInitialBuId();
    if (resolved && resolved !== buCategoryId) {
      setBuCategoryId(resolved);
      buOriginalRef.current = resolved;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incomeCategories, isRevenueVariant]);

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
      // Atomic A2 · Feb-2026 — ONLY for CATEGORY edits, privileged
      // roles auto-carry the paid/sent confirmation flags so the
      // status gate on PATCH does not surface a 409.  Non-category
      // edits (quantity / unit_price / description) still hit the
      // lock → regression preserved.
      if (field === "category" && canBypassCategoryConfirm) {
        patchBody.confirm_edit_sent = true;
        patchBody.acknowledged_lock_bypass = true;
      }
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

  /* ── K48 · Business Unit commit ─────────────────────────────────
   * Reuses the existing K41 PATCH /api/quotes/{iid} pipeline.  We
   * write BOTH the canonical ``income_category_id`` and the
   * denormalized ``category`` (Path B — no schema change), then
   * emit the standard drill-down audit companion with
   * ``field="income_category_id"``.  On success we stamp
   * ``movedTo`` so the row stays visible with a "Moved to X" chip
   * until the modal is refreshed (user-approved default). */
  const commitBusinessUnit = async (nextId) => {
    // K48 verify-hotfix · Feb-2026 — send a MINIMAL BU-only PATCH
    // payload.  Prior ship spread the row's ``line_items`` into the
    // body which triggered the numeric ``_validate_line_items`` guard
    // upstream of the paid/sent confirmation gate (409 with
    // ``line_items[0].quantity/unit_price must be numeric``).  The
    // backend now accepts a top-level ``business_unit`` field
    // written via ``$set`` — money-neutral, no ``line_items``
    // required.  We still carry the paid/sent confirmation flags
    // through so the K41 status gate accepts the edit on realised-
    // revenue rows.
    if (k48Status.isTerminal) {
      setSaveErr("Invoice is void/cancelled — cannot re-classify.");
      toast.error("Invoice is void/cancelled — cannot re-classify.");
      return;
    }
    if (!nextId) return;
    if (nextId === buOriginalRef.current) return;
    const nextCat = incomeCategories.find((c) => c.id === nextId);
    if (!nextCat) {
      setSaveErr("Unknown business unit.");
      return;
    }
    const beforeId = buOriginalRef.current;
    const beforeName = (row.category || "").trim();
    setSaving(true);
    setSaveErr("");
    // Optimistic — reflect the new selection immediately.
    setBuCategoryId(nextId);
    try {
      // K48 verify-hotfix — BU-only patch body.  Do NOT spread
      // row.line_items or any other invoice fields into this
      // payload; the shape validators upstream of the paid-lock
      // guard reject stringified numerics and would 409 the edit.
      //
      // INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID contract.
      // Send BOTH the canonical ``business_unit_id`` FK and the
      // denormalized ``business_unit`` display name so the backend
      // never has to name-lookup on read. Backend accepts both
      // via ``$set`` on ``InvoiceEditBody``.
      const patchBody = {
        business_unit: nextCat.name,
        business_unit_id: nextCat.id,
      };
      if (k48Status.needsSentConfirm) {
        patchBody.confirm_edit_sent = true;
      }
      if (k48Status.needsPaidConfirm) {
        patchBody.confirm_edit_paid_invoice_number = row.invoice_number || "";
      }
      await api.patch(`/quotes/${row.invoice_id}`, patchBody);
      try {
        await api.post("/dashboard/drilldown/line-item-audit", {
          tile,
          invoice_id: row.invoice_id,
          line_index: row.line_index ?? null,
          field: "business_unit",
          before: beforeId || beforeName || null,
          after: nextCat.name,
        });
      } catch (auditErr) {
        // eslint-disable-next-line no-console
        console.warn("[k48] audit companion failed", auditErr);
      }
      buOriginalRef.current = nextId;
      // Keep the denormalized draft in sync so any subsequent free-
      // text bindings don't step on the new value.
      setDraft((d) => ({ ...d, category: nextCat.name }));
      originalRef.current = { ...originalRef.current, category: nextCat.name };
      // K48 · Moved-to indicator — only render when the new bucket
      // differs from the bucket the modal is currently drilled into.
      const currentLc = String(currentBucket || "").trim().toLowerCase();
      const newLc = String(nextCat.name || "").trim().toLowerCase();
      if (currentLc && newLc && currentLc !== newLc) {
        setMovedTo(nextCat.name);
      } else {
        setMovedTo(null);
      }
      onEdited?.(row, "business_unit", beforeId, nextId);
      setFaded(true);
      setTimeout(() => setFaded(false), 300);
    } catch (e) {
      setBuCategoryId(beforeId);
      const detail = e?.data?.detail;
      const msg = typeof detail === "string" ? detail
        : detail?.error || detail?.message || e?.message || "Save failed";
      setSaveErr(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  /* INCOME-DRILLDOWN-EDIT · Feb-2026 — line-level Service Unit
   * commit.  Sends the paired-ID contract on the same PATCH the
   * K41 commitField already uses: rebuild ``line_items`` with the
   * affected row swapped to include BOTH the canonical FK
   * ``service_category_id`` and the denormalized ``service_category``
   * name.  Optimistic UI (setSvcCategoryId → nextId immediately),
   * rollback on PATCH reject.  Money-neutral (qty × unit_price
   * unchanged), and the K41 audit companion still fires with
   * ``field="service_category_id"``. */
  const commitServiceUnit = async (nextId) => {
    if (!nextId) return;
    if (nextId === svcOriginalRef.current) return;
    const nextCat = serviceCategories.find((c) => c.id === nextId);
    if (!nextCat) {
      setSaveErr("Unknown service unit.");
      return;
    }
    if (row.line_item_id == null && row.line_index == null) {
      setSaveErr("Legacy row — use Open full edit.");
      return;
    }
    const before = svcOriginalRef.current;
    setSaving(true);
    setSaveErr("");
    setSvcCategoryId(nextId);
    try {
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
      // Paired-ID write: canonical FK + denormalized display name.
      items[idx] = {
        ...items[idx],
        service_category_id: nextCat.id,
        service_category: nextCat.name,
      };
      await api.patch(`/quotes/${row.invoice_id}`, { line_items: items });
      try {
        await api.post("/dashboard/drilldown/line-item-audit", {
          tile,
          invoice_id: row.invoice_id,
          line_index: idx,
          field: "service_category_id",
          before,
          after: nextCat.id,
        });
      } catch (auditErr) {
        // eslint-disable-next-line no-console
        console.warn("[income-drilldown] audit companion failed", auditErr);
      }
      svcOriginalRef.current = nextId;
      onEdited?.(row, "service_category_id", before, nextId);
      setFaded(true);
      setTimeout(() => setFaded(false), 300);
    } catch (e) {
      setSvcCategoryId(before);
      const detail = e?.data?.detail;
      const msg = typeof detail === "string" ? detail
        : detail?.error || detail?.message || e?.message || "Save failed";
      setSaveErr(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  /* INCOME-DRILLDOWN-EDIT · Feb-2026 — line-level Category commit
   * for the ``income-by-service`` variant.  Sends the paired-ID
   * contract on the same PATCH pipeline as commitServiceUnit:
   * BOTH ``income_category_id`` (canonical FK) AND ``category``
   * (denormalized display) land on the target line item.  Backend
   * ``validate_line_item_categories`` verifies the FK against
   * ``income_categories`` at write time. */
  const commitLineCategoryPaired = async (nextId) => {
    if (!nextId) return;
    if (nextId === lineCatOriginalRef.current) return;
    const nextCat = incomeCategories.find((c) => c.id === nextId);
    if (!nextCat) {
      setSaveErr("Unknown category.");
      return;
    }
    if (row.line_item_id == null && row.line_index == null) {
      setSaveErr("Legacy row — use Open full edit.");
      return;
    }
    const before = lineCatOriginalRef.current;
    setSaving(true);
    setSaveErr("");
    setLineCatId(nextId);
    try {
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
      items[idx] = {
        ...items[idx],
        income_category_id: nextCat.id,
        category: nextCat.name,
      };
      // Atomic A2 · Feb-2026 — privileged roles bypass the sent /
      // accepted lock without a confirm dialog.  Non-privileged
      // fallback keeps the pre-A2 call shape so lower roles still
      // hit the backend status gate (409 surfaced via toast).
      if (canBypassCategoryConfirm) {
        await api.patch(`/quotes/${row.invoice_id}`, {
          line_items: items,
          confirm_edit_sent: true,
          acknowledged_lock_bypass: true,
        });
      } else {
        await api.patch(`/quotes/${row.invoice_id}`, { line_items: items });
      }
      try {
        await api.post("/dashboard/drilldown/line-item-audit", {
          tile,
          invoice_id: row.invoice_id,
          line_index: idx,
          field: "income_category_id",
          before,
          after: nextCat.id,
        });
      } catch (auditErr) {
        // eslint-disable-next-line no-console
        console.warn("[income-drilldown] audit companion failed", auditErr);
      }
      lineCatOriginalRef.current = nextId;
      setDraft((d) => ({ ...d, category: nextCat.name }));
      originalRef.current = { ...originalRef.current, category: nextCat.name };
      onEdited?.(row, "income_category_id", before, nextId);
      setFaded(true);
      setTimeout(() => setFaded(false), 300);
    } catch (e) {
      setLineCatId(before);
      const detail = e?.data?.detail;
      const msg = typeof detail === "string" ? detail
        : detail?.error || detail?.message || e?.message || "Save failed";
      setSaveErr(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

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
      <td
        style={{ padding: "6px 10px" }}
        data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-bu-cell`}
      >
        {isRevenueVariant ? (
          k48Status.isTerminal ? (
            <LockedCell
              testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-bu-locked`}
            >
              {(() => {
                const hit = incomeCategories.find((c) => c.id === buCategoryId);
                return hit?.name || row.category || "—";
              })()}
            </LockedCell>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Select
                value={buCategoryId || undefined}
                onValueChange={commitBusinessUnit}
                disabled={saving}
              >
                <SelectTrigger
                  className="h-8 text-sm"
                  style={{ maxWidth: 160 }}
                  data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-bu-trigger`}
                >
                  <SelectValue placeholder="Select…" />
                </SelectTrigger>
                <SelectContent>
                  {incomeCategories.map((c) => (
                    <SelectItem
                      key={c.id}
                      value={c.id}
                      data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-bu-option-${c.id}`}
                    >
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {movedTo ? (
                <span
                  style={{
                    fontSize: 10,
                    color: colors.muted,
                    fontStyle: "italic",
                  }}
                  data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-bu-moved`}
                >
                  Moved to {movedTo}
                </span>
              ) : null}
            </div>
          )
        ) : (
          /* INCOME-DRILLDOWN-EDIT · Feb-2026 — line-level Category
           * Select replaces the pre-K48 free-text ``category`` input
           * on the ``income-by-service`` variant.  Same paired-ID
           * contract as the invoice-level BU Select above: PATCH
           * writes BOTH ``income_category_id`` (canonical FK) and
           * ``category`` (denormalized name) on the target line
           * item.  Terminal-status rows fall back to a locked chip
           * (mirrors K48). */
          k48Status.isTerminal ? (
            <LockedCell
              testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-cat-locked`}
            >
              {(() => {
                const hit = incomeCategories.find((c) => c.id === lineCatId);
                return hit?.name || row.category || "—";
              })()}
            </LockedCell>
          ) : (
            <Select
              value={lineCatId || undefined}
              onValueChange={commitLineCategoryPaired}
              disabled={saving}
            >
              <SelectTrigger
                className="h-8 text-sm"
                style={{ maxWidth: 160 }}
                data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-cat-trigger`}
              >
                <SelectValue placeholder="Select…" />
              </SelectTrigger>
              <SelectContent>
                {incomeCategories.map((c) => (
                  <SelectItem
                    key={c.id}
                    value={c.id}
                    data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-cat-option-${c.id}`}
                  >
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )
        )}
      </td>
      <td
        style={{ padding: "6px 10px", fontSize: 12 }}
        data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-svc-cell`}
      >
        {/* INCOME-DRILLDOWN-EDIT · Feb-2026 — Service Unit Select
          * replaces the pre-K48 read-only ``row.service_category``
          * text.  Available in BOTH income variants.  Paired-ID
          * PATCH writes ``service_category_id`` (canonical FK) plus
          * ``service_category`` (denormalized display name) onto
          * the target line item.  Terminal rows lock to a chip. */}
        {k48Status.isTerminal ? (
          <LockedCell
            testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-svc-locked`}
          >
            {(() => {
              const hit = serviceCategories.find((c) => c.id === svcCategoryId);
              return hit?.name || row.service_category || "—";
            })()}
          </LockedCell>
        ) : (
          <Select
            value={svcCategoryId || undefined}
            onValueChange={commitServiceUnit}
            disabled={saving}
          >
            <SelectTrigger
              className="h-8 text-sm"
              style={{ maxWidth: 160 }}
              data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-svc-trigger`}
            >
              <SelectValue placeholder="Select…" />
            </SelectTrigger>
            <SelectContent>
              {serviceCategories.map((c) => (
                <SelectItem
                  key={c.id}
                  value={c.id}
                  data-testid={`income-row-${row.invoice_id}-${row.line_index ?? "x"}-svc-option-${c.id}`}
                >
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
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
   K41b — Bulk resolve action bar (data-integrity only)
   ═══════════════════════════════════════════════════════════════ */

/** Per-class action affordances.  Buttons the current class doesn't
 * support are disabled with a tooltip so the UX is uniform across
 * classes even though the modal is single-class today.
 */
function classSupports(refClass) {
  if (refClass === "orphaned_customer_refs") {
    return { customer: true, tech: false, delete: true };
  }
  if (refClass === "orphaned_technician_refs") {
    return { customer: false, tech: true, delete: false };
  }
  // unassigned_pending_jobs
  return { customer: false, tech: true, delete: false };
}

function BulkResolveBar({
  refClass,
  selectedRows,
  onClearSelection,
  onBulkComplete,
}) {
  const [mode, setMode] = useState(""); // "" | "customer" | "tech" | "delete"
  const [target, setTarget] = useState(null); // {id, name} for assigns
  const [confirming, setConfirming] = useState(false); // destructive 2-step
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState([]); // {job_id, error}

  const support = classSupports(refClass);
  const n = selectedRows.length;

  const reset = () => {
    setMode("");
    setTarget(null);
    setConfirming(false);
    setError("");
    setFailed([]);
  };

  // Reset the transient picker/confirm state when the selection is
  // cleared or the pending action's target changes classes.
  useEffect(() => { if (n === 0) reset(); }, [n]);

  const confirmDisabled = busy
    || (mode === "customer" && !target)
    || (mode === "tech" && !target)
    || (mode === "delete" && !support.delete);

  const buildSummary = () => {
    if (mode === "customer") {
      return `Reassign ${n} orphan job${n === 1 ? "" : "s"} to Customer "${target?.name || target?.email || target?.id || "—"}".`;
    }
    if (mode === "tech") {
      return `Reassign ${n} job${n === 1 ? "" : "s"} to Technician "${target?.name || target?.email || target?.id || "—"}".`;
    }
    // Note: the delete mode branch is now dead code from the UI —
    // R4=B removed the confirm strip for delete.  Preserved as a
    // defensive fallback in case a future feature re-introduces the
    // strip for a different delete flavor.
    if (mode === "delete") {
      return `Hard-delete ${n} orphan job${n === 1 ? "" : "s"} — cannot be undone.`;
    }
    return "";
  };

  const runBulk = async (act, tgtId) => {
    if (n > BULK_CAP) {
      setError(`Batch cap exceeded (max ${BULK_CAP}).`);
      return;
    }
    setBusy(true);
    setError("");
    setFailed([]);
    const bulkBatchId = makeBulkBatchId();
    const items = selectedRows.map((jobId) => ({
      ref_class: refClass,
      job_id: jobId,
      action: act,
      target_id: tgtId || null,
    }));
    try {
      const resp = await api.post(
        "/dashboard/data-integrity/resolve-bulk",
        { items, bulk_batch_id: bulkBatchId },
      );
      const results = Array.isArray(resp?.results) ? resp.results : [];
      const okIds = results.filter((r) => r.ok).map((r) => r.job_id);
      const failedRows = results.filter((r) => !r.ok);
      setFailed(failedRows);
      if (okIds.length > 0) {
        // Feb-2026 · Force ``mode: "delete"`` in the meta when the
        // action is ``hard_delete`` so the parent's
        // ``handleBulkComplete`` skips arming the K41c undo banner.
        // The top-level Hard-delete button bypasses the mode state
        // (see onClick above) so ``mode`` in the closure is stale
        // for the hard-delete path; overriding here keeps the
        // undo-skip logic authoritative.
        const metaMode = act === "hard_delete" ? "delete" : mode;
        onBulkComplete(okIds, {
          bulkBatchId: resp?.bulk_batch_id || bulkBatchId,
          action: act,
          mode: metaMode,
          targetLabel: target?.name || target?.email || null,
        });
        toast.success(
          `Resolved ${okIds.length}/${n} row${n === 1 ? "" : "s"}` +
            (failedRows.length > 0 ? ` · ${failedRows.length} failed` : ""),
        );
      } else if (failedRows.length > 0) {
        toast.error(`All ${n} rows failed.  See details below.`);
      }
      if (failedRows.length === 0) {
        reset();
      } else {
        // Keep the strip up so the user can see the per-row errors.
        setConfirming(false);
      }
    } catch (e) {
      const msg = e?.data?.detail || e?.message || "Bulk resolve failed";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const fireConfirm = () => {
    if (mode === "delete") {
      if (!confirming) {
        // First click on destructive — arm the second-click.
        setConfirming(true);
        return;
      }
      runBulk("delete", null);
      return;
    }
    if (mode === "customer" || mode === "tech") {
      runBulk("assign", target?.id);
    }
  };

  if (n === 0 && failed.length === 0) return null;

  return (
    <div
      data-testid="bulk-resolve-bar"
      style={{
        background: colors.surface,
        // Feb-2026 · Data-Integrity hard-delete upgrade (ruling R5=A).
        // Reference ``colors.inputBorder`` (#3B82F6) as a subtle top
        // accent so the bulk-action zone reads as a distinct chrome
        // surface separate from the row list.  Bottom border stays
        // ``colors.border`` (neutral zinc) to avoid double-emphasis.
        borderTop: `2px solid ${colors.inputBorder}`,
        borderBottom: `1px solid ${colors.border}`,
        padding: "10px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div
        style={{ display: "flex", flexWrap: "wrap", alignItems: "center",
                  gap: 10 }}
      >
        <span
          data-testid="bulk-resolve-selection-count"
          style={{
            fontSize: 13, fontWeight: 600,
            // Feb-2026 · ruling R5=A — reference ``colors.nav.bg``
            // (#1B1F5C) on the selection-count chip so the count
            // reads as a first-class action-zone identifier.
            color: colors.nav?.bg || colors.onSurface,
          }}
        >
          {n} selected
        </span>

        <span style={{ color: colors.muted }}>·</span>

        {/* Assign to customer */}
        {mode === "customer" ? (
          <div style={{ minWidth: 220 }}>
            <AssignPicker
              kind="customers"
              onSelect={(r) => setTarget(r)}
            />
          </div>
        ) : (
          <Button
            size="sm"
            variant={support.customer ? "secondary" : "outline"}
            disabled={busy || !support.customer}
            onClick={() => { setMode("customer"); setTarget(null); setConfirming(false); }}
            title={support.customer ? "Reassign the selected rows to a customer" : "Not applicable for this issue class"}
            data-testid="bulk-resolve-mode-customer"
          >
            Assign to customer ▾
          </Button>
        )}

        {/* Assign to tech */}
        {mode === "tech" ? (
          <div style={{ minWidth: 220 }}>
            <AssignPicker
              kind="technicians"
              onSelect={(r) => setTarget(r)}
            />
          </div>
        ) : (
          <Button
            size="sm"
            variant={support.tech ? "secondary" : "outline"}
            disabled={busy || !support.tech}
            onClick={() => { setMode("tech"); setTarget(null); setConfirming(false); }}
            title={support.tech ? "Reassign the selected rows to a technician" : "Not applicable for this issue class"}
            data-testid="bulk-resolve-mode-tech"
          >
            Assign to tech ▾
          </Button>
        )}

        {/* Hard-delete (Feb-2026 · Data-Integrity hard-delete upgrade).
             Ruling R4=B: this button fires immediately on first click,
             skipping the outer confirm strip entirely.  Ruling R6:
             backend soft-delete "action":"delete" preserved; frontend
             now sends "action":"hard_delete".  The assign modes below
             still use the confirm strip (unchanged) — the strip is a
             target-picker surface for them, not a friction gate.
             K41c undo intentionally skipped for delete-mode bulks —
             hard deletes are irreversible. See recon surprise S4
             (2026-02-XX). Backend /undo-bulk endpoint remains
             defensive for direct API callers on pre-existing
             soft-delete audit rows. */}
        <Button
          size="sm"
          variant="destructive"
          disabled={busy || !support.delete}
          onClick={() => {
            // R4=B — single click on top-level button fires the API
            // call directly.  Do not set ``mode="delete"`` so the
            // confirm strip does NOT render for this action.
            runBulk("hard_delete", null);
          }}
          title={support.delete
            ? "Hard-delete every selected orphan job (irreversible)"
            : "Only enabled when every selected row is a job-type orphan"}
          data-testid="bulk-resolve-mode-delete"
        >
          Hard-delete jobs
        </Button>

        <Button
          size="sm"
          variant="ghost"
          onClick={() => { onClearSelection(); reset(); }}
          disabled={busy}
          data-testid="bulk-resolve-clear"
        >
          Clear
        </Button>
      </div>

      {/* Inline confirm strip — appears when a mode is selected. */}
      {mode && (
        <div
          style={{
            display: "flex", flexWrap: "wrap", alignItems: "center",
            gap: 10, padding: "8px 10px",
            background: mode === "delete" ? "#FEF2F2" : colors.surfaceSecondary,
            border: `1px solid ${mode === "delete" ? "#FCA5A5" : colors.border}`,
            borderRadius: 6,
          }}
          data-testid="bulk-resolve-confirm-strip"
        >
          <span
            style={{ fontSize: 12, color: mode === "delete" ? colors.error : colors.onSurface }}
            data-testid="bulk-resolve-confirm-summary"
          >
            {buildSummary()}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => { setMode(""); setTarget(null); setConfirming(false); }}
              disabled={busy}
              data-testid="bulk-resolve-confirm-cancel"
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant={mode === "delete" ? "destructive" : "default"}
              disabled={confirmDisabled}
              onClick={fireConfirm}
              data-testid="bulk-resolve-confirm-fire"
            >
              {busy
                ? "Applying…"
                : mode === "delete"
                  ? (confirming ? `Confirm delete ${n} job${n === 1 ? "" : "s"}` : "Confirm")
                  : `Confirm (${n})`}
            </Button>
          </div>
        </div>
      )}

      {error ? (
        <div
          data-testid="bulk-resolve-error"
          style={{ color: colors.error, fontSize: 12 }}
        >
          {error}
        </div>
      ) : null}

      {failed.length > 0 ? (
        <div
          data-testid="bulk-resolve-failed-list"
          style={{
            padding: "8px 10px", background: "#FEF2F2",
            border: `1px solid #FCA5A5`, borderRadius: 6,
            fontSize: 12, color: colors.error,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {failed.length} row{failed.length === 1 ? "" : "s"} failed:
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, maxHeight: 100, overflow: "auto" }}>
            {failed.map((f) => (
              <li key={f.job_id} data-testid={`bulk-resolve-failed-${f.job_id}`}>
                {String(f.job_id).slice(0, 8)}… — {f.error || "error"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════
   K41c — Undo Last Bulk banner (Data-Integrity only)
   ═══════════════════════════════════════════════════════════════ */
const UNDO_WINDOW_MS = 10 * 60 * 1000;

function formatMMSS(msLeft) {
  const total = Math.max(0, Math.floor(msLeft / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function UndoBanner({ lastBulk, onUndone, onDismiss }) {
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [failedRows, setFailedRows] = useState([]);

  useEffect(() => {
    setNow(Date.now());
    setConfirming(false);
    setError("");
    setFailedRows([]);
  }, [lastBulk?.bulkBatchId]);

  useEffect(() => {
    if (!lastBulk) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [lastBulk]);

  if (!lastBulk) return null;
  const msLeft = lastBulk.expiresAt - now;
  const expired = msLeft <= 0;

  const summary = (() => {
    const n = lastBulk.count;
    const noun = n === 1 ? "" : "s";
    if (lastBulk.mode === "delete") {
      return `Soft-deleted ${n} orphan job${noun}.`;
    }
    if (lastBulk.mode === "customer") {
      return `Reassigned ${n} orphan job${noun} to ${lastBulk.targetLabel || "—"}.`;
    }
    if (lastBulk.mode === "tech") {
      return `Reassigned ${n} job${noun} to ${lastBulk.targetLabel || "—"}.`;
    }
    return `Applied ${n} change${noun}.`;
  })();

  const fireUndo = async () => {
    if (!confirming) { setConfirming(true); return; }
    setBusy(true);
    setError("");
    setFailedRows([]);
    try {
      const resp = await api.post(
        "/dashboard/data-integrity/undo-bulk",
        { bulk_batch_id: lastBulk.bulkBatchId },
      );
      const restored = Array.isArray(resp?.restored) ? resp.restored : [];
      const failed = Array.isArray(resp?.failed) ? resp.failed : [];
      setFailedRows(failed);
      if (restored.length > 0) {
        toast.success(
          `Restored ${restored.length} row${restored.length === 1 ? "" : "s"}` +
            (failed.length > 0 ? ` · ${failed.length} failed` : ""),
        );
      } else if (failed.length > 0) {
        toast.error(`All ${failed.length} rows failed to restore.`);
      }
      onUndone(restored.map((r) => r.job_id));
    } catch (e) {
      const detail = e?.data?.detail || e?.message || "Undo failed";
      setError(typeof detail === "string" ? detail : JSON.stringify(detail));
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  };

  const isDelete = lastBulk.mode === "delete";
  const bg = isDelete ? "#FEF2F2" : "#EFF6FF";
  const border = isDelete ? "#FCA5A5" : "#93C5FD";
  const fg = isDelete ? colors.error : "#1D4ED8";

  return (
    <div
      data-testid="undo-banner"
      style={{
        padding: "8px 14px",
        background: bg,
        borderTop: `1px solid ${border}`,
        borderBottom: `1px solid ${border}`,
        display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10,
      }}
    >
      <span
        style={{ fontSize: 13, color: fg }}
        data-testid="undo-banner-summary"
      >
        {summary}
      </span>
      {!expired ? (
        <span
          style={{ fontSize: 12, color: colors.muted, fontFamily: "monospace" }}
          data-testid="undo-banner-countdown"
        >
          expires in {formatMMSS(msLeft)}
        </span>
      ) : (
        <span
          style={{ fontSize: 12, color: colors.muted, fontStyle: "italic" }}
          data-testid="undo-banner-expired"
        >
          undo window expired
        </span>
      )}
      <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
        {!expired ? (
          confirming ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirming(false)}
                disabled={busy}
                data-testid="undo-banner-cancel"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="default"
                onClick={fireUndo}
                disabled={busy}
                data-testid="undo-banner-confirm"
              >
                {busy
                  ? "Restoring…"
                  : `Confirm — undo ${lastBulk.count} change${lastBulk.count === 1 ? "" : "s"}`}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={fireUndo}
              disabled={busy}
              data-testid="undo-banner-undo"
            >
              Undo
            </Button>
          )
        ) : (
          <Button
            size="sm"
            variant="ghost"
            onClick={onDismiss}
            data-testid="undo-banner-dismiss"
          >
            Dismiss
          </Button>
        )}
      </div>
      {error ? (
        <div
          data-testid="undo-banner-error"
          style={{ width: "100%", color: colors.error, fontSize: 12 }}
        >
          {error}
        </div>
      ) : null}
      {failedRows.length > 0 ? (
        <div
          data-testid="undo-banner-failed-list"
          style={{
            width: "100%", padding: "6px 8px", background: "#FFF",
            border: `1px solid ${border}`, borderRadius: 6,
            fontSize: 12, color: colors.error,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {failedRows.length} row{failedRows.length === 1 ? "" : "s"} failed to restore:
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, maxHeight: 100, overflow: "auto" }}>
            {failedRows.map((f) => (
              <li key={f.job_id || Math.random()}
                  data-testid={`undo-banner-failed-${f.job_id || "unknown"}`}>
                {String(f.job_id || "?").slice(0, 8)}… — {f.error || "error"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
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
  /* K41b — selection state (data-integrity only; page-scope). */
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  /* K41b — track rows that just resolved via bulk so they fade before
   * being removed from the array on the next render tick. */
  const [pendingBulkFade, setPendingBulkFade] = useState(() => new Set());
  /* K41c — last bulk's info powers the Undo banner (10-min window). */
  const [lastBulk, setLastBulk] = useState(null);
  /* K41c — bump to force a re-fetch after undo restores rows. */
  const [reloadKey, setReloadKey] = useState(0);
  /* K48 · Feb-2026 — tenant-scoped income_categories drive the
   * Business Unit dropdown in the revenue-by-category drill-down.
   * Fetch once when the modal opens on that variant; empty list on
   * failure so the fallback locked-chip rendering still works.
   *
   * INCOME-DRILLDOWN-EDIT · Feb-2026 — both income variants now
   * need the income_categories list (Category dropdown lives on
   * the ``income-by-service`` variant too), and BOTH variants
   * need the service_categories list to power the new Service
   * Unit Select.  Two effects, each guarded by
   * ``variant.startsWith("income-")`` so the data-integrity
   * variant never fires them. */
  const [incomeCategories, setIncomeCategories] = useState([]);
  const [serviceCategories, setServiceCategories] = useState([]);
  useEffect(() => {
    if (variant !== "income-by-category" && variant !== "income-by-service") {
      return undefined;
    }
    let cancelled = false;
    api.get("/income-categories?include_archived=false")
      .then((r) => {
        if (cancelled) return;
        const list = Array.isArray(r?.items) ? r.items : [];
        setIncomeCategories(list.map((c) => ({
          id: c.id, name: c.name, color: c.color,
        })));
      })
      .catch(() => { if (!cancelled) setIncomeCategories([]); });
    return () => { cancelled = true; };
  }, [variant]);
  useEffect(() => {
    if (variant !== "income-by-category" && variant !== "income-by-service") {
      return undefined;
    }
    let cancelled = false;
    api.get("/service-categories?include_archived=false")
      .then((r) => {
        if (cancelled) return;
        const list = Array.isArray(r?.items) ? r.items : [];
        setServiceCategories(list.map((c) => ({
          id: c.id, name: c.name, color: c.color,
        })));
      })
      .catch(() => { if (!cancelled) setServiceCategories([]); });
    return () => { cancelled = true; };
  }, [variant]);

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
      .catch((e) => {
        // Feb-2026 · Drill-down role expansion — the backend gate
        // on the 3 ``/rows`` endpoints returns 403 for any caller
        // that isn't admin / super_admin / manager / owner.  Show
        // the exact QA-contract copy so a non-privileged user
        // clicking a dashboard tile learns why the drawer is empty.
        // All other errors (500, network, timeout) fall through to
        // the pre-existing generic banner unchanged.
        if (e?.status === 403) {
          setErr("You do not have permission to view this data");
        } else {
          setErr(e?.message || "Load failed");
        }
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, reloadKey]);

  const handleResolved = useCallback((jobId) => {
    setRows((prev) => prev.filter((r) => r.job_id !== jobId));
    setSelectedIds((prev) => {
      if (!prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.delete(jobId);
      return next;
    });
  }, []);

  /* K41b — bulk selection helpers. */
  const toggleSelect = useCallback((jobId, checked) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(jobId); else next.delete(jobId);
      return next;
    });
  }, []);

  const visibleJobIds = useMemo(
    () => rows.map((r) => r.job_id), [rows],
  );
  const allVisibleSelected = visibleJobIds.length > 0
    && visibleJobIds.every((id) => selectedIds.has(id));
  const someVisibleSelected = !allVisibleSelected
    && visibleJobIds.some((id) => selectedIds.has(id));

  const toggleSelectAllVisible = useCallback((checked) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        visibleJobIds.forEach((id) => next.add(id));
      } else {
        visibleJobIds.forEach((id) => next.delete(id));
      }
      return next;
    });
  }, [visibleJobIds]);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const handleBulkComplete = useCallback((okIds, meta) => {
    if (!Array.isArray(okIds) || okIds.length === 0) return;
    // Fade the resolved rows, then drop them + de-select on next tick.
    setPendingBulkFade((prev) => {
      const next = new Set(prev);
      okIds.forEach((id) => next.add(id));
      return next;
    });
    setTimeout(() => {
      setRows((prev) => prev.filter((r) => !okIds.includes(r.job_id)));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        okIds.forEach((id) => next.delete(id));
        return next;
      });
      setPendingBulkFade((prev) => {
        const next = new Set(prev);
        okIds.forEach((id) => next.delete(id));
        return next;
      });
    }, 400);
    // K41c — arm the undo banner with the just-completed batch info.
    //
    // Feb-2026 · Data-Integrity hard-delete upgrade (ruling R3=A).
    // K41c undo intentionally skipped for delete-mode bulks — hard
    // deletes are irreversible. See recon surprise S4 (2026-02-XX).
    // Backend /undo-bulk endpoint remains defensive for direct API
    // callers on pre-existing soft-delete audit rows.  After this
    // commit the modal's bulk-delete button only emits
    // ``action: "hard_delete"`` for ``orphaned_customer_refs``, so
    // this filter has zero effect on live soft-delete-through-UI
    // flows (no such surface exists today).
    if (meta?.bulkBatchId && meta.mode !== "delete") {
      setLastBulk({
        bulkBatchId: meta.bulkBatchId,
        count: okIds.length,
        mode: meta.mode,           // "customer" | "tech"
        action: meta.action,       // "assign"
        targetLabel: meta.targetLabel || null,
        expiresAt: Date.now() + UNDO_WINDOW_MS,
      });
    }
  }, []);

  /* K41c — after undo succeeds, drop the banner + re-fetch the rows
   * so restored jobs reappear at their natural sort position. */
  const handleUndone = useCallback(() => {
    setLastBulk(null);
    setCursor(null);
    setReloadKey((k) => k + 1);
  }, []);

  const dismissBanner = useCallback(() => setLastBulk(null), []);

  if (variant === "data-integrity") {
    const selectedList = Array.from(selectedIds);
    return (
      <div
        data-testid="drilldown-body-data-integrity"
        style={{
          maxHeight: "70vh",
          overflowY: "auto",
          overflowX: "hidden",
          position: "relative",
        }}
      >
        {/* K41b sticky action zone — pinned at the TOP of the scroll
            region so users can keep selecting rows while the buttons
            stay visible.  Contains the BulkResolveBar and, once a
            bulk has fired, the K41c UndoBanner underneath. */}
        <div
          data-testid="drilldown-di-sticky-zone"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 20,
            background: colors.surface,
            boxShadow: "0 4px 12px rgba(0,0,0,0.05)",
          }}
        >
          <BulkResolveBar
            refClass={params?.issueClass}
            selectedRows={selectedList}
            onClearSelection={clearSelection}
            onBulkComplete={handleBulkComplete}
          />
          <UndoBanner
            lastBulk={lastBulk}
            onUndone={handleUndone}
            onDismiss={dismissBanner}
          />
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: `2px solid ${colors.border}` }}>
              <th style={{ padding: "8px 8px", width: 32 }}>
                <Checkbox
                  checked={allVisibleSelected
                    ? true
                    : (someVisibleSelected ? "indeterminate" : false)}
                  onCheckedChange={(v) => toggleSelectAllVisible(!!v)}
                  aria-label="Select all visible rows"
                  data-testid="di-select-all"
                />
              </th>
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
                selected={selectedIds.has(r.job_id)}
                onToggleSelect={toggleSelect}
                faded={pendingBulkFade.has(r.job_id)}
              />
            ))}
          </tbody>
        </table>
        <div
          style={{ padding: "6px 12px", fontSize: 11, color: colors.muted }}
          data-testid="di-select-all-hint"
        >
          Selects visible rows only.
        </div>
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
              {["DATE", "CUSTOMER", "INVOICE #", "DESCRIPTION",
                 variant === "income-by-category" ? "BUSINESS UNIT" : "CATEGORY",
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
                variant={variant}
                incomeCategories={incomeCategories}
                serviceCategories={serviceCategories}
                currentBucket={variant === "income-by-category" ? params?.category : null}
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
