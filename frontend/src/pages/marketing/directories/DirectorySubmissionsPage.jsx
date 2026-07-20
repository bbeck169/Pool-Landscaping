/**
 * Directories · Submissions Kanban + Table (D2 · Feb 2026)
 * -----------------------------------------------------------------
 * Backend contract:
 *   GET  /api/directories/submissions?status=&category=&limit=&cursor=
 *     → { count, submissions:[...], next_cursor }
 *   GET  /api/directories/submissions/{sid}                       → row
 *   PATCH /api/directories/submissions/{sid}                      → updated row
 *   POST /api/directories/submissions/{sid}/mark-verified         → updated row
 *   POST /api/directories/submissions/{sid}/assign                → updated row
 *   POST /api/directories/submissions/bulk-create
 *     → { created, created_ids, skipped }
 *   GET  /api/directories/submissions/export/csv?directory_slug=  → CSV
 *   GET  /api/directories/definitions                             → { count, definitions }
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, LayoutGrid, Table as TableIcon, Filter, PlusCircle, Download,
  ExternalLink, UserCircle2, CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";

const STATUS_COLS = [
  { key: "not_started",  label: "Not started",  color: "#94a3b8" },
  { key: "in_progress",  label: "In progress",  color: "#3b82f6" },
  { key: "submitted",    label: "Submitted",    color: "#f59e0b" },
  { key: "verified",     label: "Verified",     color: "#10b981" },
  { key: "needs_update", label: "Needs update", color: "#f97316" },
  { key: "rejected",     label: "Rejected",     color: "#ef4444" },
  { key: "paid_wall",    label: "Paid wall",    color: "#8b5cf6" },
];

const CATEGORIES = ["maps", "aggregator", "general", "industry_pool",
                     "industry_landscape", "review", "local", "social"];

function statusColor(key) {
  return STATUS_COLS.find((c) => c.key === key)?.color || colors.muted;
}

function scoreBadgeStyle(score) {
  if (score == null) return { color: colors.muted };
  if (score >= 90) return { color: "#10b981" };
  if (score >= 60) return { color: "#f59e0b" };
  return { color: "#ef4444" };
}

export default function DirectorySubmissionsPage() {
  const nav = useNavigate();
  const [view, setView] = useState("kanban");
  const [rows, setRows] = useState([]);
  const [defs, setDefs] = useState({});
  const [users, setUsers] = useState([]);
  const [filter, setFilter] = useState({ category: "", status: "", priority: "" });
  const [selRow, setSelRow] = useState(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkCat, setBulkCat] = useState("");
  const [bulkPmin, setBulkPmin] = useState(1);

  const load = useCallback(async () => {
    try {
      const [subs, dr, usersResp] = await Promise.all([
        api.get("/directories/submissions?limit=200"),
        api.get("/directories/definitions"),
        api.get("/team").catch(() => []),
      ]);
      setRows(subs.submissions || []);
      const byslug = {};
      for (const d of dr.definitions || []) byslug[d.slug] = d;
      setDefs(byslug);
      setUsers(Array.isArray(usersResp) ? usersResp : []);
    } catch (e) {
      toast.error(e?.message || "Load failed");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      const d = defs[r.directory_slug] || {};
      if (filter.category && d.category !== filter.category) return false;
      if (filter.status && r.status !== filter.status) return false;
      if (filter.priority && String(d.priority) !== filter.priority) return false;
      return true;
    });
  }, [rows, defs, filter]);

  const grouped = useMemo(() => {
    const g = {};
    for (const col of STATUS_COLS) g[col.key] = [];
    for (const r of filtered) {
      (g[r.status] || g.not_started).push(r);
    }
    return g;
  }, [filtered]);

  // Optimistic drag-drop status update with rollback.
  const onDrop = async (row, newStatus) => {
    if (row.status === newStatus) return;
    const prevStatus = row.status;
    setRows((cur) => cur.map((x) =>
      x.id === row.id ? { ...x, status: newStatus } : x));
    try {
      await api.patch(`/directories/submissions/${row.id}`,
                        { status: newStatus });
    } catch (e) {
      setRows((cur) => cur.map((x) =>
        x.id === row.id ? { ...x, status: prevStatus } : x));
      toast.error(e?.message || "Move failed — rolled back");
    }
  };

  const runBulk = async () => {
    try {
      const body = {};
      if (bulkCat) body.category = bulkCat;
      if (bulkPmin) body.priority_min = Number(bulkPmin);
      const r = await api.post("/directories/submissions/bulk-create", body);
      toast.success(`Created ${r.created} submissions · skipped ${r.skipped}`);
      setBulkOpen(false);
      await load();
    } catch (e) {
      toast.error(e?.message || "Bulk create failed");
    }
  };

  const downloadCsv = async (slug) => {
    try {
      const url = `${process.env.REACT_APP_BACKEND_URL}/api/directories/submissions/export/csv${slug ? `?directory_slug=${slug}` : ""}`;
      const tok = localStorage.getItem("token");
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (!resp.ok) throw new Error(`export failed ${resp.status}`);
      const blob = await resp.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = `directory_export${slug ? `_${slug}` : ""}.csv`;
      a.click();
      URL.revokeObjectURL(objUrl);
    } catch (e) {
      toast.error(e?.message || "CSV export failed");
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-[1400px] mx-auto space-y-4"
          data-testid="directory-submissions-page">
      <div className="flex items-center gap-3 mb-2">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Directory Submissions
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Track and update your listing status across every citation source.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border overflow-hidden"
                style={{ borderColor: colors.border }}>
            <button onClick={() => setView("kanban")}
                    className="px-3 py-1.5 text-xs flex items-center gap-1"
                    style={{ backgroundColor: view === "kanban" ? colors.brand : "transparent",
                              color: view === "kanban" ? "#fff" : colors.onSurface }}
                    data-testid="view-kanban">
              <LayoutGrid className="w-3 h-3" /> Kanban
            </button>
            <button onClick={() => setView("table")}
                    className="px-3 py-1.5 text-xs flex items-center gap-1"
                    style={{ backgroundColor: view === "table" ? colors.brand : "transparent",
                              color: view === "table" ? "#fff" : colors.onSurface }}
                    data-testid="view-table">
              <TableIcon className="w-3 h-3" /> Table
            </button>
          </div>
          <Button variant="outline" onClick={() => downloadCsv("")}
                    data-testid="bulk-csv-btn">
            <Download className="w-3 h-3 mr-1" /> All CSV
          </Button>
          <Button onClick={() => setBulkOpen(true)} data-testid="bulk-create-btn">
            <PlusCircle className="w-4 h-4 mr-1" /> Bulk Create
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="rounded-xl p-3 flex flex-wrap gap-2 items-center"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="filter-bar">
        <Filter className="w-4 h-4" style={{ color: colors.muted }} />
        <select className="border rounded px-2 py-1 text-xs"
                value={filter.category}
                onChange={(e) => setFilter((f) => ({ ...f, category: e.target.value }))}
                data-testid="filter-category">
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="border rounded px-2 py-1 text-xs"
                value={filter.status}
                onChange={(e) => setFilter((f) => ({ ...f, status: e.target.value }))}
                data-testid="filter-status">
          <option value="">All statuses</option>
          {STATUS_COLS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select className="border rounded px-2 py-1 text-xs"
                value={filter.priority}
                onChange={(e) => setFilter((f) => ({ ...f, priority: e.target.value }))}>
          <option value="">All priorities</option>
          {[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>Priority {p}</option>)}
        </select>
        <span className="text-xs ml-auto" style={{ color: colors.muted }}>
          {filtered.length} of {rows.length}
        </span>
      </div>

      {/* Views */}
      {view === "kanban" ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          {STATUS_COLS.map((col) => (
            <div key={col.key}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    const id = e.dataTransfer.getData("text/plain");
                    const row = rows.find((r) => r.id === id);
                    if (row) onDrop(row, col.key);
                  }}
                  className="rounded-xl p-2"
                  style={{ backgroundColor: colors.surface,
                            border: `1px solid ${colors.border}`,
                            borderTop: `4px solid ${col.color}` }}
                  data-testid={`col-${col.key}`}>
              <div className="text-xs font-bold mb-2 flex justify-between"
                    style={{ color: colors.onSurface }}>
                <span>{col.label}</span>
                <span style={{ color: colors.muted }}>{grouped[col.key].length}</span>
              </div>
              <div className="space-y-2 min-h-[80px]">
                {grouped[col.key].map((r) => {
                  const d = defs[r.directory_slug] || {};
                  return (
                    <div key={r.id}
                          draggable
                          onDragStart={(e) => e.dataTransfer.setData("text/plain", r.id)}
                          onClick={() => setSelRow(r)}
                          className="rounded-lg p-2 text-xs cursor-grab hover:brightness-95"
                          style={{ backgroundColor: colors.surfaceSecondary,
                                    border: `1px solid ${colors.border}` }}
                          data-testid={`kanban-card-${r.directory_slug}`}>
                      <div className="font-semibold truncate">{d.name || r.directory_slug}</div>
                      <div className="flex items-center gap-1 mt-1 flex-wrap">
                        <Badge variant="outline" className="text-[9px]">
                          {d.category || "?"}
                        </Badge>
                        <Badge variant="outline" className="text-[9px]">P{d.priority || "?"}</Badge>
                        {r.nap_match_score != null && (
                          <span className="text-[10px]" style={scoreBadgeStyle(r.nap_match_score)}>
                            {r.nap_match_score}%
                          </span>
                        )}
                        {r.assigned_user_id && (
                          <UserCircle2 className="w-3 h-3" style={{ color: colors.muted }} />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-xl overflow-x-auto"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="submissions-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left p-2">Directory</th>
                <th className="text-left p-2">Category</th>
                <th className="text-left p-2">Priority</th>
                <th className="text-left p-2">Status</th>
                <th className="text-left p-2">NAP Score</th>
                <th className="text-left p-2">Last Checked</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const d = defs[r.directory_slug] || {};
                return (
                  <tr key={r.id}
                       className="border-t cursor-pointer hover:brightness-95"
                       style={{ borderColor: colors.border }}
                       onClick={() => setSelRow(r)}
                       data-testid={`table-row-${r.directory_slug}`}>
                    <td className="p-2 font-semibold">{d.name || r.directory_slug}</td>
                    <td className="p-2">{d.category}</td>
                    <td className="p-2">P{d.priority}</td>
                    <td className="p-2">
                      <span className="inline-block px-2 py-0.5 rounded-full text-white text-[10px]"
                             style={{ backgroundColor: statusColor(r.status) }}>
                        {r.status}
                      </span>
                    </td>
                    <td className="p-2" style={scoreBadgeStyle(r.nap_match_score)}>
                      {r.nap_match_score == null ? "—" : `${r.nap_match_score}%`}
                    </td>
                    <td className="p-2" style={{ color: colors.muted }}>
                      {r.last_checked_at ? new Date(r.last_checked_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="p-2">
                      <button onClick={(e) => { e.stopPropagation(); downloadCsv(r.directory_slug); }}
                              className="text-[10px] underline"
                              style={{ color: colors.brand }}
                              data-testid={`csv-single-${r.directory_slug}`}>
                        CSV
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail drawer */}
      <SubmissionDetail
        row={selRow}
        defn={selRow ? defs[selRow.directory_slug] : null}
        users={users}
        onClose={() => setSelRow(null)}
        onUpdated={(r) => {
          setRows((cur) => cur.map((x) => x.id === r.id ? r : x));
          setSelRow(r);
        }}
      />

      {/* Bulk-create modal */}
      {bulkOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
              style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
              onClick={() => setBulkOpen(false)}>
          <div className="rounded-2xl p-6 w-96"
                style={{ backgroundColor: colors.surface }}
                onClick={(e) => e.stopPropagation()}
                data-testid="bulk-modal">
            <h3 className="font-bold mb-3">Bulk Create Submissions</h3>
            <Label className="text-xs">Category (optional)</Label>
            <select className="border rounded px-2 py-1 w-full text-sm mb-2"
                    value={bulkCat}
                    onChange={(e) => setBulkCat(e.target.value)}
                    data-testid="bulk-cat">
              <option value="">All</option>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <Label className="text-xs">Minimum priority</Label>
            <select className="border rounded px-2 py-1 w-full text-sm mb-3"
                    value={bulkPmin}
                    onChange={(e) => setBulkPmin(e.target.value)}>
              {[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setBulkOpen(false)}>Cancel</Button>
              <Button onClick={runBulk} data-testid="bulk-confirm">Create</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Detail drawer ────────────────────────────────────────────────────
function SubmissionDetail({ row, defn, users, onClose, onUpdated }) {
  const [status, setStatus] = useState(row?.status || "not_started");
  const [notes, setNotes] = useState(row?.notes || "");
  const [url, setUrl] = useState(row?.external_listing_url || "");
  const [saving, setSaving] = useState(false);
  const [assigning, setAssigning] = useState(false);

  useEffect(() => {
    if (row) {
      setStatus(row.status);
      setNotes(row.notes || "");
      setUrl(row.external_listing_url || "");
    }
  }, [row]);

  if (!row) return null;

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.patch(`/directories/submissions/${row.id}`, {
        status, notes, external_listing_url: url,
      });
      onUpdated(r);
      toast.success("Saved");
    } catch (e) {
      toast.error(e?.message || "Save failed");
    }
    setSaving(false);
  };
  const verify = async () => {
    try {
      const r = await api.post(`/directories/submissions/${row.id}/mark-verified`, {});
      onUpdated(r);
      toast.success("Marked verified");
    } catch (e) {
      toast.error(e?.message || "Verify failed");
    }
  };
  const assign = async (uid) => {
    setAssigning(true);
    try {
      const r = await api.post(`/directories/submissions/${row.id}/assign`,
                                  { assigned_user_id: uid || null });
      onUpdated(r);
      toast.success(uid ? "Assigned" : "Cleared assignment");
    } catch (e) {
      toast.error(e?.message || "Assign failed");
    }
    setAssigning(false);
  };

  const assignedUser = (users || []).find((u) => u.id === row.assigned_user_id);
  const initials = (assignedUser?.name || assignedUser?.email || "?")
    .split(/\s+/).filter(Boolean).slice(0, 2).map((s) => s[0]?.toUpperCase()).join("");

  return (
    <Sheet open={!!row} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto"
                     data-testid="submission-drawer">
        <SheetHeader>
          <SheetTitle>{defn?.name || row.directory_slug}</SheetTitle>
        </SheetHeader>
        <div className="mt-3 space-y-3 text-sm">
          {defn && (
            <div className="rounded-lg p-3 text-xs"
                  style={{ backgroundColor: colors.surfaceSecondary }}>
              <div><b>Category:</b> {defn.category}</div>
              <div><b>Priority:</b> {defn.priority}</div>
              <div className="mt-1">
                {defn.requires_manual && <Badge className="mr-1 bg-slate-500">Manual</Badge>}
                {defn.requires_paid_account && <Badge className="bg-purple-500">Paid</Badge>}
              </div>
              <div className="mt-1">
                <b>Expected fields:</b> {(defn.expected_fields || []).join(", ")}
              </div>
              <div className="flex flex-wrap gap-2 mt-2">
                {defn.homepage_url && (
                  <a href={defn.homepage_url} target="_blank" rel="noreferrer"
                      className="underline text-xs" style={{ color: colors.brand }}>
                    Homepage <ExternalLink className="inline w-3 h-3" />
                  </a>
                )}
                {defn.submission_url && (
                  <a href={defn.submission_url} target="_blank" rel="noreferrer"
                      className="underline text-xs" style={{ color: colors.brand }}
                      data-testid="detail-submission-url">
                    Submit here <ExternalLink className="inline w-3 h-3" />
                  </a>
                )}
              </div>
            </div>
          )}

          <div>
            <Label className="text-xs">Status</Label>
            <select className="border rounded px-2 py-1 w-full text-sm"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                    data-testid="detail-status">
              {STATUS_COLS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <div>
            <Label className="text-xs">External listing URL</Label>
            <Input value={url} onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://…" />
          </div>
          <div>
            <Label className="text-xs">Notes</Label>
            <Textarea value={notes} rows={3}
                        onChange={(e) => setNotes(e.target.value)} />
          </div>

          <div className="rounded-lg p-3"
                style={{ backgroundColor: colors.surfaceSecondary }}
                data-testid="assign-section">
            <Label className="text-xs mb-1 block">Assign to</Label>
            <div className="flex items-center gap-2">
              {assignedUser ? (
                <div className="flex items-center gap-1 px-2 py-1 rounded-full"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}>
                  <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold"
                         style={{ backgroundColor: "rgba(255,255,255,0.25)" }}>
                    {initials || "?"}
                  </span>
                  <span className="text-xs" data-testid="assigned-name">
                    {assignedUser.name || assignedUser.email}
                  </span>
                </div>
              ) : (
                <span className="text-xs" style={{ color: colors.muted }}>
                  Unassigned
                </span>
              )}
              <select className="border rounded px-2 py-1 text-xs ml-auto"
                       value={row.assigned_user_id || ""}
                       disabled={assigning}
                       onChange={(e) => assign(e.target.value)}
                       data-testid="assign-select">
                <option value="">— Unassigned —</option>
                {(users || []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name || u.email} · {u.role}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {row.nap_match_score != null && (
            <div className="rounded-lg p-3 text-xs"
                  style={{ backgroundColor: colors.surfaceSecondary }}
                  data-testid="detail-diff">
              <div className="font-bold mb-1">NAP match · {row.nap_match_score}%</div>
              {(row.discrepancies || []).length === 0 && (
                <div style={{ color: "#10b981" }}>All fields match. ✓</div>
              )}
              {(row.discrepancies || []).map((d, i) => (
                <div key={i} className="mt-1">
                  <b>{d.field}</b> · expected <code>{String(d.expected)}</code> · found <code>{String(d.found)}</code>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <Button onClick={save} disabled={saving} data-testid="detail-save">Save</Button>
            <Button variant="outline" onClick={verify} data-testid="detail-verify">
              <CheckCircle2 className="w-4 h-4 mr-1" /> Mark Verified
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
