/**
 * Phase 51.I — Recurring Jobs admin.
 * Endpoints:
 *   GET    /api/recurring-jobs
 *   POST   /api/recurring-jobs
 *   PATCH  /api/recurring-jobs/{id}
 *   DELETE /api/recurring-jobs/{id}
 *   POST   /api/recurring-jobs/{id}/generate?through=YYYY-MM-DD
 */
import React, { useEffect, useState } from "react";
import { CalendarClock, Plus, Pause, Play, Trash2, RefreshCw, X, Ban, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  MonthlyNthWeekdaySelector,
} from "@/components/recurring/MonthlyNthWeekdaySelector";
import CustomerCombobox from "@/components/customers/CustomerCombobox";

const FREQ_OPTIONS = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Bi-weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly (every 3 months)" },
  { value: "semi_annual", label: "Semi-annual (every 6 months)" },
  { value: "custom", label: "Custom (every N days)" },
];
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmtMoney(cents) { return `$${(Number(cents || 0) / 100).toFixed(2)}`; }
function todayIso() { return new Date().toISOString().slice(0, 10); }
function addDaysIso(iso, days) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function RecurringJobs() {
  const [items, setItems] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [techs, setTechs] = useState([]);
  // Phase H9 · Feb-2026 — load crews for the combined "Assigned
  // to" dropdown. Falls back to an empty list if the endpoint
  // 403s (tech role) so the modal still renders.
  const [crews, setCrews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  // Phase H9 · Feb-2026 — user-facing price string. Kept
  // separate from ``editing.price_cents`` so the input is
  // freely typable (backspace / select-all / partial decimals)
  // WITHOUT round-tripping through Number() on every keystroke.
  const [priceStr, setPriceStr] = useState("0.00");
  const [priceErr, setPriceErr] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  // Feb-2026 · Recurring Jobs · hard-delete confirmation modal.
  // Kept OUT of the row's own state so the modal survives a row
  // re-render (busy flag flips as soon as the confirm click
  // fires) — the confirmation is a distinct destructive action
  // gated behind its own explicit confirm button.
  const [hardDeleteTarget, setHardDeleteTarget] = useState(null);
  // Phase R1 · Feb-2026 — Bulk Hard Delete state.
  //   ``selectedIds``: Set<string> of the checked rows across the
  //     currently-visible page.  Cleared after a successful bulk.
  //   ``bulkModalOpen``: gates the confirmation popup.
  //   ``bulkAcked``: user MUST tick the acknowledgement checkbox
  //     before the red "Permanently Delete" button becomes
  //     enabled — no type-to-confirm.
  //   ``bulkBusy``: prevents double-submits + drives the button's
  //     visual busy state during the network round-trip.
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkAcked, setBulkAcked] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  // Feb-2026 P0 · Orphan-backfill state. Populated lazily on mount
  // so operators see a "Missing N template(s)" banner without
  // running the mutating backfill first.
  const [orphanPreview, setOrphanPreview] = useState(null);
  const [orphanBusy, setOrphanBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [tpls, custs, techsRes, crewsRes] = await Promise.all([
        api.get("/recurring-jobs"),
        api.get("/customers?is_active=true&limit=500").catch(() => ({ items: [] })),
        api.get("/technicians").catch(() => []),
        // Phase H9 · Feb-2026 — crews. Same 403-safe pattern.
        api.get("/crews").catch(() => ({ items: [] })),
      ]);
      setItems(tpls?.items || []);
      setCustomers(Array.isArray(custs) ? custs : (custs?.items || []));
      setTechs(Array.isArray(techsRes) ? techsRes : (techsRes?.items || []));
      setCrews(Array.isArray(crewsRes) ? crewsRes : (crewsRes?.items || []));
    } catch (e) {
      setError(e?.message || "Failed to load");
    } finally { setLoading(false); }
    // Feb-2026 P0 · Fire an orphan-preview scan right after the main
    // load. Best-effort — a failure just leaves the banner hidden.
    try {
      const preview = await api.get("/recurring-jobs/orphans");
      setOrphanPreview(preview);
    } catch (_e) {
      setOrphanPreview(null);
    }
  };

  const runBackfill = async () => {
    // eslint-disable-next-line no-alert
    const ok = window.confirm(
      `Create ${orphanPreview?.orphan_count || 0} missing recurring-job templates for ` +
      `${orphanPreview?.total_occurrences || 0} orphan occurrences?\n\n` +
      `This is idempotent — existing templates stay untouched.`
    );
    if (!ok) return;
    setOrphanBusy(true);
    try {
      const res = await api.post("/recurring-jobs/backfill-orphans", {});
      // Refresh both the main table and the orphan preview.
      await load();
      // eslint-disable-next-line no-alert
      window.alert(
        `Backfill complete.\n\n` +
        `Created: ${res?.created ?? 0}\n` +
        `Skipped (already existed): ${res?.skipped_existing ?? 0}`
      );
    } catch (e) {
      setError(e?.message || "Backfill failed");
    } finally {
      setOrphanBusy(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditing({ frequency: "weekly", day_of_week: 0, start_date: todayIso(), price_cents: 12000, active: true, is_active: false, notes: "", recurrence_never_ends: true, end_date: null });
    setPriceStr("120.00");
    setPriceErr("");
    setModalOpen(true);
  };
  const openEdit = (row) => {
    // Feb-2026 · Ends-mode default. Legacy rows may have neither
    // `recurrence_never_ends` nor `end_date`; treat that as "Never"
    // per the product rule ("if neither set, fall back to Never").
    const neverEnds = row.recurrence_never_ends === true
      || (row.recurrence_never_ends == null && !row.end_date);
    setEditing({ ...row, recurrence_never_ends: neverEnds });
    setPriceStr(((row.price_cents || 0) / 100).toFixed(2));
    setPriceErr("");
    setModalOpen(true);
  };

  // Phase H9 · Feb-2026 — Accept optional leading "$", 0-5 digit
  // integer part, optional decimal with up to 2 fraction digits.
  // Empty string counts as invalid so the caller can't accidentally
  // silently blank the price.
  const _PRICE_RE = /^\$?\d{1,5}(\.\d{0,2})?$/;
  const _validatePrice = (s) => {
    const trimmed = (s || "").trim();
    if (!trimmed) return false;
    if (!_PRICE_RE.test(trimmed)) return false;
    const n = Number(trimmed.replace("$", ""));
    if (!Number.isFinite(n)) return false;
    if (n < 0 || n > 99999.99) return false;
    return true;
  };

  const save = async () => {
    setError(null);
    // Phase H9 · Feb-2026 — validate the free-text price. UI's
    // save button is disabled while ``priceErr`` is non-empty
    // but we defense-in-depth here too.
    if (!_validatePrice(priceStr)) {
      setPriceErr("Enter a valid price (0.00 – 99999.99)");
      return;
    }
    try {
      const priceCents = Math.round(
        Number(priceStr.replace("$", "")) * 100,
      );
      // Feb-2026 · Never-end recurrence · UI intent maps to backend
      // flag. When true, clear the end_date field client-side too so
      // the payload doesn't fight the backend override.
      const payload = { ...editing, price_cents: priceCents };
      if (payload.recurrence_never_ends) payload.end_date = null;
      if (editing.id) {
        await api.patch(`/recurring-jobs/${editing.id}`, payload);
      } else {
        // Feb-2026 · Phase — Recommended Schedule auto-assign v1.
        // Backend returns ``auto_assign_info`` on create so we can
        // pick the toast variant without a second round-trip.
        const created = await api.post("/recurring-jobs", payload);
        const info = created?.auto_assign_info || {};
        if (info.auto_assigned) {
          const dowName = DOW[info.day_of_week] || "the assigned day";
          toast.success(
            `Assigned to ${info.technician_name || "a technician"} ` +
            `on ${dowName} based on route proximity`,
            { duration: 4500 },
          );
        } else if (info.reason === "no_geocode") {
          toast(
            "Created — no coordinates on customer, please assign manually",
            { duration: 4500 },
          );
        } else if (info.reason === "no_existing_routes") {
          toast(
            "Created without auto-assign — no existing routes for this frequency yet",
            { duration: 4500 },
          );
        }
        // ``manual_override`` and any other reason → no extra toast;
        // the create itself is the confirmation.
      }
      setModalOpen(false); setEditing(null);
      await load();
    } catch (e) {
      setError(e?.message || "Save failed");
    }
  };

  const togglePause = async (row) => {
    setBusy(row.id);
    try { await api.patch(`/recurring-jobs/${row.id}`, { active: !row.active }); await load(); }
    finally { setBusy(null); }
  };

  const softDelete = async (row) => {
    setBusy(row.id);
    try { await api.del(`/recurring-jobs/${row.id}`); await load(); }
    finally { setBusy(null); }
  };

  const hardDelete = async (row) => {
    // Feb-2026 · Recurring Jobs · HARD delete. Backend removes the
    // template row + cancels every future-scheduled child job.
    // Completed / in-progress children are preserved.
    setBusy(row.id);
    try {
      await api.del(`/recurring-jobs/${row.id}?hard=true`);
      setHardDeleteTarget(null);
      await load();
    } finally { setBusy(null); }
  };

  // Phase R1 · Feb-2026 — Bulk Hard Delete.
  //
  // Posts every selected template id to
  // ``POST /api/recurring-jobs/bulk-delete``.  The backend returns
  // HTTP 200 even on partial failures with a summary + per-id
  // status list, so the toast reflects the TRUTH — "Deleted 3 of 3"
  // vs "Deleted 2 of 3; 1 failed — see log".  On any per-id error
  // we fire a warning-style toast, never a success.
  const bulkHardDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!bulkAcked) return;
    setBulkBusy(true);
    try {
      const ids = Array.from(selectedIds);
      const res = await api.post("/recurring-jobs/bulk-delete", {
        recurring_job_ids: ids,
      });
      const summary = res?.summary || {};
      const deleted = Number(summary.templates_deleted || 0);
      const visits = Number(summary.future_visits_deleted || 0);
      const errs = Number(summary.errors || 0);
      const total = ids.length;
      if (errs === 0) {
        toast.success(
          `Deleted ${deleted} template${deleted === 1 ? "" : "s"}` +
          ` and ${visits} future visit${visits === 1 ? "" : "s"}.`,
        );
      } else {
        toast.warning(
          `Deleted ${deleted} of ${total}; ${errs} failed — see log.`,
        );
      }
      setSelectedIds(new Set());
      setBulkModalOpen(false);
      setBulkAcked(false);
      await load();
    } catch (e) {
      toast.error(e?.message || "Bulk delete failed");
    } finally {
      setBulkBusy(false);
    }
  };

  // Header "select all on page" checkbox.  Respects any client-side
  // filtering — currently the page has none, but the helper reads
  // ``items`` directly so a future filter drop-in wires through
  // without a rewrite.
  const _visibleIds = () => items.map((r) => r.id);
  const _allVisibleSelected = () => {
    const vis = _visibleIds();
    return vis.length > 0 && vis.every((id) => selectedIds.has(id));
  };
  const _someVisibleSelected = () => {
    const vis = _visibleIds();
    return vis.some((id) => selectedIds.has(id));
  };
  const _toggleAllVisible = () => {
    if (_allVisibleSelected()) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(_visibleIds()));
    }
  };
  const _toggleOne = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const stopRecurrence = async (row) => {
    // Feb-2026 · Never-end recurrence · Stop action. Confirm because
    // this removes unstarted future occurrences from db.jobs.
    // eslint-disable-next-line no-alert
    const ok = window.confirm(
      "Stop generating future occurrences?\n\nExisting scheduled visits from today onward that haven't been started will be removed. Started/completed visits and today's route stay untouched."
    );
    if (!ok) return;
    setBusy(row.id);
    try {
      const res = await api.post(`/recurring-jobs/${row.id}/stop`, {});
      alertOk(`Stopped. Removed ${res?.removed_future_jobs ?? 0} future occurrences.`);
      await load();
    } catch (e) {
      setError(e?.message || "Stop failed");
    } finally {
      setBusy(null);
    }
  };

  const generateNow = async (row) => {
    setBusy(row.id);
    try {
      const through = addDaysIso(todayIso(), 14);
      const res = await api.post(`/recurring-jobs/${row.id}/generate?through=${through}`, {});
      alertOk(`Generated ${res?.inserted || 0} jobs (skipped ${res?.skipped || 0}).`);
      await load();
    } catch (e) { setError(e?.message || "Generate failed"); }
    finally { setBusy(null); }
  };

  const alertOk = (msg) => { setError(null); setBusy(null); window.setTimeout(() => setError(null), 100); /* mini-toast substitute */ setError(msg); setTimeout(() => setError(null), 2500); };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="recurring-jobs-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center"
               style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
            <CalendarClock size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Recurring Jobs</h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Auto-generates a rolling 2-week horizon of jobs. Nightly cron @ 02:00 UTC.
            </p>
          </div>
        </div>
        <button type="button" onClick={openCreate}
                className="inline-flex items-center gap-1 text-sm font-bold px-3 py-2 rounded-md"
                style={{ background: colors.brand, color: "#fff", border: 0 }}
                data-testid="recurring-jobs-create">
          <Plus size={14} /> New recurring job
        </button>
        {/* Phase R1 · Feb-2026 — bulk hard-delete toolbar button.
             Always rendered so its testid is queryable by unit
             tests + Playwright; disabled when nothing is
             selected. The label appends the running count so
             ops always sees ``Delete permanently (N)`` — the
             count comes from the visible-page checkbox state,
             not the server. */}
        <button
          type="button"
          onClick={() => { setBulkAcked(false); setBulkModalOpen(true); }}
          disabled={selectedIds.size === 0}
          className="inline-flex items-center gap-1 text-sm font-bold px-3 py-2 rounded-md ml-2"
          style={{
            background: selectedIds.size === 0 ? "#FEE2E2" : "#B91C1C",
            color: selectedIds.size === 0 ? "#B91C1C" : "#FFFFFF",
            border: 0,
            opacity: selectedIds.size === 0 ? 0.5 : 1,
            cursor: selectedIds.size === 0 ? "not-allowed" : "pointer",
          }}
          aria-disabled={selectedIds.size === 0}
          data-testid="recurring-bulk-hard-delete"
        >
          <Trash2 size={14} />{" "}
          Delete permanently{selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}
        </button>
      </div>

      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="recurring-jobs-error">{error}</div>
      ) : null}

      {/* Feb-2026 P0 · Orphan cluster banner. Renders only when the
          orphan-preview scan found at least one cluster missing a
          matching template. Operator can click "Backfill now" to
          mint them; idempotent so re-running is safe. */}
      {orphanPreview && orphanPreview.orphan_count > 0 ? (
        <div
          className="rounded-2xl p-4 mb-4 text-sm flex items-start justify-between gap-3"
          style={{ background: "#FEF3C7", border: "1px solid #FCD34D",
                    color: "#78350F" }}
          data-testid="recurring-jobs-orphan-banner"
        >
          <div>
            <div className="font-bold">
              {orphanPreview.orphan_count} recurring customer
              {orphanPreview.orphan_count === 1 ? "" : "s"} missing from this list.
            </div>
            <div className="mt-0.5 text-xs">
              Detected {orphanPreview.total_occurrences} pre-scheduled visits from
              the Schedule page that have no matching recurring template. Click
              &ldquo;Backfill now&rdquo; to add them here — existing entries won&rsquo;t be touched.
            </div>
          </div>
          <button
            type="button"
            onClick={runBackfill}
            disabled={orphanBusy}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-2 rounded-md whitespace-nowrap"
            style={{ background: "#B45309", color: "#FFFFFF", border: 0,
                      opacity: orphanBusy ? 0.5 : 1 }}
            data-testid="recurring-jobs-backfill-btn"
          >
            {orphanBusy ? "Backfilling…" : "Backfill now"}
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
          Loading…
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="recurring-jobs-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                {/* Phase R1 · Feb-2026 — bulk-select header cell.
                     Tri-state semantics: unchecked when nothing on
                     the page is selected, checked when EVERY visible
                     row is selected, ``indeterminate`` when some
                     rows are selected. */}
                <th className="px-3 py-2.5" style={{ width: "36px" }}>
                  <input
                    type="checkbox"
                    checked={_allVisibleSelected()}
                    ref={(el) => {
                      if (el) {
                        el.indeterminate = !_allVisibleSelected() && _someVisibleSelected();
                      }
                    }}
                    onChange={_toggleAllVisible}
                    aria-label="Select all recurring jobs on this page"
                    data-testid="recurring-select-all"
                    className="cursor-pointer"
                  />
                </th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Customer</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Service</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Frequency</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Next</th>
                <th className="text-right px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Price</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Status</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="recurring-jobs-empty">
                  No recurring jobs yet — click "New recurring job" to add your first.
                </td></tr>
              ) : items.map((r) => (
                <tr key={r.id} data-testid={`recurring-job-row-${r.id}`}
                    style={{ borderBottom: `1px solid ${colors.border}`,
                              backgroundColor: selectedIds.has(r.id)
                                ? "#EFF6FF" : "transparent" }}>
                  {/* Phase R1 · Feb-2026 — bulk-select row checkbox. */}
                  <td className="px-3 py-2.5" style={{ width: "36px" }}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(r.id)}
                      onChange={() => _toggleOne(r.id)}
                      aria-label={`Select ${r.customer_name || r.id}`}
                      data-testid={`recurring-row-checkbox-${r.id}`}
                      className="cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-2.5" style={{ color: colors.onSurface }}>{r.customer_name}</td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>{r.service_type}</td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>
                    {r.frequency}{r.frequency === "weekly" || r.frequency === "biweekly" ? ` (${DOW[r.day_of_week] || "?"})` : ""}
                    {r.frequency === "monthly" ? ` (day ${r.day_of_month})` : ""}
                    {r.frequency === "custom" ? ` (${r.interval_days}d)` : ""}
                  </td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>
                    {(r.upcoming || []).slice(0, 1).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-semibold" style={{ color: colors.onSurface }}>
                    {fmtMoney(r.price_cents)}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                          style={r.active
                            ? { background: "#DCFCE7", color: "#166534" }
                            : { background: "#FEE2E2", color: "#991B1B" }}>
                      {r.active ? "Active" : "Paused"}
                    </span>
                    {/* Feb-2026 · Recurring Jobs · is_active badge.
                        Rendered when the new gate is explicitly off,
                        distinct from the legacy "Paused" (which
                        derives from ``active``). A row can be
                        "Paused + Inactive" simultaneously — both
                        chips render side-by-side. */}
                    {r.is_active === false ? (
                      <span className="inline-block ml-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                            style={{ background: "#FEF3C7", color: "#92400E" }}
                            data-testid={`recurring-job-inactive-badge-${r.id}`}>
                        Inactive
                      </span>
                    ) : null}
                    {/* Feb-2026 · Recommended Schedule auto-assign v1.
                        Persistent breadcrumb — this template was
                        placed by the route-proximity centroid pick,
                        not by a human choosing a tech/day. Tooltip
                        surfaces the extra-drive-time estimate. */}
                    {r.auto_assigned ? (
                      <span
                        className="inline-flex items-center gap-1 ml-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                        style={{ background: "#DBEAFE", color: "#1E3A8A" }}
                        title={`via route proximity · +${r.auto_assign_extra_minutes || 0}m extra drive time`}
                        data-testid={`recurring-job-auto-assign-badge-${r.id}`}
                      >
                        <Sparkles size={9} /> Auto-assigned
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    <button type="button" onClick={() => generateNow(r)} disabled={busy === r.id || !r.active}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`recurring-job-generate-${r.id}`}>
                      <RefreshCw size={11} /> Gen 14d
                    </button>
                    <button type="button" onClick={() => openEdit(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`recurring-job-edit-${r.id}`}>
                      Edit
                    </button>
                    <button type="button" onClick={() => togglePause(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`recurring-job-toggle-${r.id}`}>
                      {r.active ? <Pause size={11} /> : <Play size={11} />}{r.active ? "Pause" : "Resume"}
                    </button>
                    {r.active ? (
                      <button type="button" onClick={() => stopRecurrence(r)} disabled={busy === r.id}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                              style={{ border: `1px solid #FCD34D`, background: colors.surface, color: "#B45309" }}
                              data-testid={`recurring-job-stop-${r.id}`}>
                        <Ban size={11} /> Stop
                      </button>
                    ) : null}
                    <button type="button" onClick={() => softDelete(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid #FECACA`, background: colors.surface, color: "#B91C1C" }}
                            data-testid={`recurring-job-soft-delete-btn-${r.id}`}>
                      <Trash2 size={11} /> Delete
                    </button>
                    {/* Feb-2026 · Recurring Jobs · HARD delete.
                        Visually distinct (solid red) so it can't be
                        confused with the soft-delete button above.
                        Gated behind its own dedicated confirmation
                        modal — never a browser ``confirm()`` — so
                        the destructive action is a two-tap flow. */}
                    <button type="button"
                            onClick={() => setHardDeleteTarget(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold"
                            style={{ border: `1px solid #B91C1C`, background: "#B91C1C", color: "#FFFFFF" }}
                            data-testid={`recurring-job-hard-delete-btn-${r.id}`}>
                      <Trash2 size={11} /> Delete permanently
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(15,23,42,0.55)" }}>
          <div className="w-full max-w-lg rounded-2xl" style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
              <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                {editing.id ? "Edit Recurring Job" : "New Recurring Job"}
              </h2>
              <button type="button" onClick={() => { setModalOpen(false); setEditing(null); }}
                      data-testid="recurring-jobs-modal-close">
                <X size={18} />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Customer
                <div className="mt-1">
                  <CustomerCombobox
                    value={editing.customer_id || ""}
                    onChange={(cid) => setEditing((x) => ({ ...x, customer_id: cid }))}
                    customers={customers}
                    testid="recurring-jobs-customer"
                    placeholder="Select customer…"
                  />
                </div>
              </label>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Service type
                <input type="text" value={editing.service_type || ""} onChange={(e) => setEditing((x) => ({ ...x, service_type: e.target.value }))}
                       className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                       style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                       data-testid="recurring-jobs-service" placeholder="Weekly Pool Service" />
              </label>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Frequency
                <select value={editing.frequency || "weekly"} onChange={(e) => setEditing((x) => ({ ...x, frequency: e.target.value }))}
                        className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                        style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                        data-testid="recurring-jobs-frequency">
                  {FREQ_OPTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                </select>
              </label>
              {(editing.frequency === "weekly" || editing.frequency === "biweekly") ? (
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Day of week
                  <select value={editing.day_of_week ?? 0} onChange={(e) => setEditing((x) => ({ ...x, day_of_week: Number(e.target.value) }))}
                          className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                          style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                          data-testid="recurring-jobs-dow">
                    {DOW.map((d, i) => <option key={d} value={i}>{d}</option>)}
                  </select>
                </label>
              ) : null}
              {editing.frequency === "monthly" ? (
                // Feb-2026 · Monthly recurrence — shared component
                // exposing both "Same day each month" (day_of_month)
                // AND "Nth weekday" (monthly_pattern="nth_weekday"
                // with monthly_nth_week + monthly_weekday). Same
                // component is used on /jobs/new so the wire
                // contract is canonical in one place.
                <MonthlyNthWeekdaySelector
                  value={editing}
                  onChange={(patch) => setEditing((x) => ({ ...x, ...patch }))}
                  testidPrefix="recurring-jobs-monthly-"
                />
              ) : null}
              {editing.frequency === "custom" ? (
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Interval days
                  <input type="number" min="1" max="365" value={editing.interval_days ?? 7}
                         onChange={(e) => setEditing((x) => ({ ...x, interval_days: Number(e.target.value) }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="recurring-jobs-interval" />
                </label>
              ) : null}
              <div>
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Start date
                  <input type="date" value={editing.start_date || todayIso()}
                         onChange={(e) => setEditing((x) => ({ ...x, start_date: e.target.value }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="recurring-job-start-date-input" />
                </label>
              </div>

              {/* Feb-2026 · Recurring Jobs — Active switch + is_active.
                  New records default off so the operator can save
                  a draft and flip the switch later. Backend rejects
                  ``is_active=true`` without a ``start_date`` with a
                  422 ``start_date_required_for_active`` — the
                  ``disabled`` guard here surfaces that as a client-
                  side hint before the request even fires. */}
              <div className="rounded-lg p-3 flex items-start justify-between gap-3"
                    style={{ border: `1px solid ${colors.border}` }}>
                <div className="flex-1">
                  <div className="text-xs font-semibold uppercase tracking-wide"
                        style={{ color: colors.muted }}>
                    Active
                  </div>
                  <p className="text-xs mt-1" style={{ color: colors.muted }}>
                    {(editing.start_date || "").trim()
                      ? "Nightly generator materializes occurrences when active."
                      : "Requires start date"}
                  </p>
                </div>
                <label className="inline-flex items-center gap-2 text-xs font-semibold shrink-0"
                        style={{ color: colors.onSurface }}>
                  <input type="checkbox"
                          checked={!!editing.is_active}
                          disabled={!(editing.start_date || "").trim()}
                          onChange={(e) => setEditing((x) => ({
                            ...x, is_active: e.target.checked,
                          }))}
                          data-testid="recurring-job-active-toggle" />
                  {editing.is_active ? "On" : "Off"}
                </label>
              </div>
              {/* Feb-2026 · Ends mode · explicit radio group. Two mutually-
                  exclusive modes: Never (recurrence_never_ends=true) or
                  On date (end_date=<picked>). Default Never. Backend
                  forces end_date=null when recurrence_never_ends is on. */}
              <fieldset className="rounded-lg p-3" style={{ border: `1px solid ${colors.border}` }}>
                <legend className="text-xs font-semibold px-1" style={{ color: colors.muted }}>Ends</legend>
                <div className="space-y-2">
                  <label className="flex items-start gap-2 text-xs font-semibold" style={{ color: colors.onSurface }}>
                    <input type="radio" name="recurrence-ends-mode"
                           checked={!!editing.recurrence_never_ends}
                           onChange={() => setEditing((x) => ({ ...x, recurrence_never_ends: true, end_date: null }))}
                           className="mt-0.5"
                           data-testid="recurring-jobs-ends-never" />
                    <span>
                      Never
                      <span className="block font-normal mt-0.5" style={{ color: colors.muted }}>
                        {editing.recurrence_never_ends
                          ? "Continues indefinitely — stop from the row action bar."
                          : "Rolls forward on a 14-day horizon until you stop it."}
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 text-xs font-semibold" style={{ color: colors.onSurface }}>
                    <input type="radio" name="recurrence-ends-mode"
                           checked={!editing.recurrence_never_ends}
                           onChange={() => setEditing((x) => ({ ...x, recurrence_never_ends: false }))}
                           className="mt-0.5"
                           data-testid="recurring-jobs-ends-on-date" />
                    <span className="flex-1">
                      On date
                      <input type="date"
                             value={editing.end_date || ""}
                             disabled={!!editing.recurrence_never_ends}
                             onChange={(e) => setEditing((x) => ({ ...x, end_date: e.target.value || null, recurrence_never_ends: false }))}
                             className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                             style={{
                               border: `1px solid ${colors.border}`,
                               background: editing.recurrence_never_ends ? colors.surfaceSecondary : colors.surface,
                               color: editing.recurrence_never_ends ? colors.muted : colors.onSurface,
                               opacity: editing.recurrence_never_ends ? 0.55 : 1,
                             }}
                             data-testid="recurring-jobs-end" />
                      {(!editing.recurrence_never_ends && editing.end_date) ? (
                        <span className="block font-normal mt-1" style={{ color: colors.muted }}>
                          Final visit on or before {editing.end_date}.
                        </span>
                      ) : null}
                    </span>
                  </label>
                </div>
              </fieldset>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Assigned to
                {/* Phase H9 · Feb-2026 — Combined "Assigned to"
                    dropdown. Value shape: ``"tech:{id}"`` or
                    ``"crew:{id}"`` (dispatch table on save so
                    payload lands with exactly one of
                    ``assigned_tech_id`` / ``crew_id`` populated
                    and the opposite side explicitly ``null``). */}
                <select
                  value={editing.crew_id
                    ? `crew:${editing.crew_id}`
                    : (editing.assigned_tech_id
                        ? `tech:${editing.assigned_tech_id}`
                        : "")}
                  onChange={(e) => {
                    const v = e.target.value;
                    setEditing((x) => {
                      if (!v) {
                        return { ...x, assigned_tech_id: null,
                                     crew_id: null };
                      }
                      const [kind, id] = v.split(":", 2);
                      if (kind === "crew") {
                        return { ...x, assigned_tech_id: null,
                                     crew_id: id };
                      }
                      return { ...x, assigned_tech_id: id,
                                   crew_id: null };
                    });
                  }}
                  className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                  style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                  data-testid="recurring-jobs-assign">
                  <option value=""
                             data-testid="recurring-jobs-assign-auto">
                    Auto-assign
                  </option>
                  {techs.length ? (
                    <optgroup label="Technicians"
                                 data-testid="recurring-jobs-assign-techs">
                      {techs.map((t) => (
                        <option key={`tech-${t.id}`}
                                   value={`tech:${t.id}`}
                                   data-testid={`recurring-jobs-assign-tech-${t.id}`}>
                          {t.name || t.email}
                        </option>
                      ))}
                    </optgroup>
                  ) : null}
                  {crews.length ? (
                    <optgroup label="Crews"
                                 data-testid="recurring-jobs-assign-crews">
                      {crews.map((c) => (
                        <option key={`crew-${c.id}`}
                                   value={`crew:${c.id}`}
                                   data-testid={`recurring-jobs-assign-crew-${c.id}`}>
                          Crew: {c.name}
                        </option>
                      ))}
                    </optgroup>
                  ) : null}
                </select>
              </label>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Price ($)
                {/* Phase H9 · Feb-2026 — free-typing price input.
                    ``type=text`` + ``inputMode=decimal`` kills the
                    number-spinner AND surfaces a decimal keypad
                    on mobile. Validation runs on save via
                    ``_validatePrice``; inline error surfaces
                    below the input. */}
                <input
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  value={priceStr}
                  onChange={(e) => {
                    const v = e.target.value;
                    setPriceStr(v);
                    setPriceErr(_validatePrice(v)
                      ? ""
                      : "Enter a valid price");
                  }}
                  onBlur={() => {
                    // Normalize on blur only — don't re-format
                    // mid-edit or the caret jumps.
                    if (_validatePrice(priceStr)) {
                      const n = Number(priceStr.replace("$", ""));
                      setPriceStr(n.toFixed(2));
                    }
                  }}
                  aria-invalid={!!priceErr}
                  className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                  style={{ border: `1px solid ${priceErr ? colors.error : colors.border}`, background: colors.surface, color: colors.onSurface }}
                  data-testid="recurring-jobs-price" />
                {priceErr ? (
                  <span className="block text-xs mt-1"
                           style={{ color: colors.error }}
                           data-testid="recurring-jobs-price-error">
                    {priceErr}
                  </span>
                ) : null}
              </label>
              <label className="flex items-center gap-2 text-xs font-semibold" style={{ color: colors.muted }}>
                <input type="checkbox" checked={!!editing.allow_sunday}
                       onChange={(e) => setEditing((x) => ({ ...x, allow_sunday: e.target.checked }))}
                       data-testid="recurring-jobs-sunday" />
                Allow Sunday
              </label>
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2" style={{ borderTop: `1px solid ${colors.border}` }}>
              <button type="button" onClick={() => { setModalOpen(false); setEditing(null); }}
                      className="text-sm font-semibold px-3 py-1.5 rounded"
                      style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                      data-testid="recurring-jobs-cancel">Cancel</button>
              <button type="button" onClick={save} disabled={!editing.customer_id || !editing.service_type || !!priceErr}
                      className="text-sm font-bold px-4 py-1.5 rounded"
                      style={{ background: colors.brand, color: "#fff", border: 0, opacity: (!editing.customer_id || !editing.service_type || !!priceErr) ? 0.5 : 1 }}
                      data-testid="recurring-jobs-save">
                {editing.id ? "Save changes" : "Create"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Feb-2026 · Recurring Jobs · HARD-delete confirmation modal.
          Distinct from the soft-delete row action so the operator
          has to explicitly opt in to the destructive path. Backend
          removes the template + cancels every future-scheduled
          child job (completed / in-progress children are
          preserved) + writes an audit_logs entry. */}
      {hardDeleteTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
              style={{ background: "rgba(15,23,42,0.55)" }}
              data-testid="recurring-job-hard-delete-confirm-modal">
          <div className="w-full max-w-md rounded-2xl"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between px-5 py-3"
                  style={{ borderBottom: `1px solid ${colors.border}` }}>
              <h2 className="text-lg font-bold" style={{ color: "#B91C1C" }}>
                Permanently delete this recurring job?
              </h2>
              <button type="button"
                       onClick={() => setHardDeleteTarget(null)}
                       aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <div className="p-5 text-sm" style={{ color: colors.onSurface }}>
              <p>
                This removes the recurring template AND cancels any
                future scheduled jobs derived from it. Completed jobs
                will not be affected. This cannot be undone.
              </p>
              {(hardDeleteTarget.customer_name || hardDeleteTarget.service_type) ? (
                <p className="mt-3 text-xs" style={{ color: colors.muted }}>
                  Target: <span className="font-semibold" style={{ color: colors.onSurface }}>
                    {hardDeleteTarget.customer_name || "—"} · {hardDeleteTarget.service_type || "—"}
                  </span>
                </p>
              ) : null}
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2"
                  style={{ borderTop: `1px solid ${colors.border}` }}>
              <button type="button"
                       onClick={() => setHardDeleteTarget(null)}
                       className="text-sm font-semibold px-3 py-1.5 rounded"
                       style={{ border: `1px solid ${colors.border}`,
                                 background: colors.surface,
                                 color: colors.onSurface }}
                       data-testid="recurring-job-hard-delete-cancel-btn">
                Cancel
              </button>
              <button type="button"
                       onClick={() => hardDelete(hardDeleteTarget)}
                       disabled={busy === hardDeleteTarget.id}
                       className="text-sm font-bold px-4 py-1.5 rounded"
                       style={{ background: "#B91C1C", color: "#FFFFFF",
                                 border: 0,
                                 opacity: busy === hardDeleteTarget.id ? 0.6 : 1 }}
                       data-testid="recurring-job-hard-delete-confirm-btn">
                Delete permanently
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {/* Phase R1 · Feb-2026 — Bulk Hard Delete confirmation modal.
           Independent of the per-row ``hardDeleteTarget`` modal — a
           distinct flow keyed off ``bulkModalOpen``. Primary button
           is gated behind an ack checkbox (no type-to-confirm), and
           displays the running selection count so the operator
           always sees exactly what's about to be permanently
           removed.  Cancel closes without any network activity. */}
      {bulkModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
              style={{ background: "rgba(15,23,42,0.55)" }}
              data-testid="recurring-bulk-hard-delete-modal">
          <div className="w-full max-w-md rounded-2xl"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between px-5 py-3"
                  style={{ borderBottom: `1px solid ${colors.border}` }}>
              <h2 className="text-lg font-bold" style={{ color: "#B91C1C" }}>
                Permanently delete {selectedIds.size} recurring template{selectedIds.size === 1 ? "" : "s"}?
              </h2>
              <button type="button"
                       onClick={() => { setBulkModalOpen(false); setBulkAcked(false); }}
                       aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <div className="p-5 text-sm" style={{ color: colors.onSurface }}>
              <p className="mb-2">The following will be removed:</p>
              <ul className="list-disc pl-5 space-y-1">
                <li>
                  <span className="font-semibold">{selectedIds.size}</span>{" "}
                  recurring job template{selectedIds.size === 1 ? "" : "s"}
                </li>
                <li>
                  All future scheduled visits (date &ge; today) linked
                  to these templates
                </li>
                <li style={{ color: colors.muted }}>
                  Past / completed visits will be preserved for reporting
                </li>
              </ul>
              <label className="flex items-start gap-2 mt-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={bulkAcked}
                  onChange={(e) => setBulkAcked(e.target.checked)}
                  className="mt-0.5 cursor-pointer"
                  data-testid="recurring-bulk-hard-delete-ack"
                />
                <span>I understand — this cannot be undone</span>
              </label>
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2"
                  style={{ borderTop: `1px solid ${colors.border}` }}>
              <button type="button"
                       onClick={() => { setBulkModalOpen(false); setBulkAcked(false); }}
                       className="text-sm font-semibold px-3 py-1.5 rounded"
                       style={{ border: `1px solid ${colors.border}`,
                                 background: colors.surface,
                                 color: colors.onSurface }}
                       data-testid="recurring-bulk-hard-delete-cancel">
                Cancel
              </button>
              <button type="button"
                       onClick={bulkHardDelete}
                       disabled={!bulkAcked || bulkBusy || selectedIds.size === 0}
                       aria-disabled={!bulkAcked || bulkBusy || selectedIds.size === 0}
                       className="text-sm font-bold px-4 py-1.5 rounded"
                       style={{ background: "#B91C1C", color: "#FFFFFF",
                                 border: 0,
                                 opacity: (!bulkAcked || bulkBusy) ? 0.5 : 1,
                                 cursor: (!bulkAcked || bulkBusy) ? "not-allowed" : "pointer" }}
                       data-testid="recurring-bulk-hard-delete-confirm">
                {bulkBusy ? "Deleting…" : "Permanently Delete"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
