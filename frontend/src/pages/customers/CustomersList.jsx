import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Search,
  Upload,
  Download,
  Filter,
  MoreVertical,
  Users,
  Tag,
  Trash2,
  BellRing,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Gate } from "@/hooks/usePermissions";
import {
  PageHeader,
  TagChip,
  Chip,
  Skeleton,
  EmptyState,
  Button,
  Modal,
  TextInput,
  Toast,
} from "@/components/ui-kit";

const TAG_PRESETS = ["VIP", "Specialty"];

function useDebounced(value, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

export default function CustomersList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [scope, setScope] = useState("all"); // all | waitlist | unscheduled
  const [selected, setSelected] = useState(new Set());
  const [bulkTag, setBulkTag] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const searchDeb = useDebounced(q);

  const load = async () => {
    setRows(null);
    const params = new URLSearchParams();
    if (searchDeb) params.set("search", searchDeb);
    if (tag) params.set("tag", tag);
    if (scope === "waitlist") params.set("waitlisted", "true");
    if (scope === "unscheduled") params.set("unscheduled", "true");
    try {
      const data = await api.get(`/customers${params.toString() ? "?" + params : ""}`);
      setRows(data || []);
      setSelected(new Set());
    } catch (e) {
      setToast({ tone: "error", message: e.message });
      setRows([]);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDeb, tag, scope]);

  const cities = useMemo(() => {
    const s = new Set();
    (rows || []).forEach((r) => {
      const c = (r.address || "").split(",").slice(-2, -1)[0]?.trim();
      if (c) s.add(c);
    });
    return Array.from(s).sort();
  }, [rows]);

  const [city, setCity] = useState("");
  const filtered = useMemo(() => {
    if (!rows) return null;
    if (!city) return rows;
    return rows.filter((r) => (r.address || "").includes(city));
  }, [rows, city]);

  const toggle = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const bulk = async (action, extra = {}) => {
    if (!selected.size) return;
    try {
      const res = await api.post("/customers/bulk", {
        ids: Array.from(selected),
        action,
        ...extra,
      });
      setToast({
        tone: "success",
        message: `Bulk ${action}: ${res.updated ?? res.deleted ?? 0} customer${
          (res.updated ?? res.deleted ?? 0) === 1 ? "" : "s"
        }`,
      });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const doExport = async () => {
    try {
      const res = await api.get("/export/customers");
      const blob = new Blob([res.content || ""], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.filename || "customers.csv";
      a.click();
      URL.revokeObjectURL(url);
      setToast({ tone: "success", message: `Exported ${res.count} customers` });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const nextScheduled = (c) => c.next_scheduled_at || "—";

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customers-page">
      <PageHeader
        title="Customers"
        subtitle={`${(filtered || []).length} shown`}
        right={
          <>
            <Button variant="ghost" onClick={doExport} testid="customers-export">
              <Download size={16} /> Export
            </Button>
            <Button variant="ghost" onClick={() => setImportOpen(true)} testid="customers-import">
              <Upload size={16} /> Import
            </Button>
            <Button onClick={() => navigate("/customers/new")} testid="customers-new-button">
              <Plus size={16} /> New Customer
            </Button>
          </>
        }
      />

      {/* Filter row */}
      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2"
            style={{ color: colors.muted }}
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, email, phone, address…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
            style={{
              backgroundColor: colors.surfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customers-search"
          />
        </div>
        <div className="flex items-center gap-1">
          <Filter size={14} style={{ color: colors.muted }} />
          {[
            { k: "all", label: "All" },
            { k: "unscheduled", label: "Unscheduled" },
            { k: "waitlist", label: "Waitlist" },
          ].map((s) => (
            <button
              key={s.k}
              onClick={() => setScope(s.k)}
              className="text-xs font-semibold px-3 py-1.5 rounded-full transition"
              style={{
                backgroundColor: scope === s.k ? colors.brandTertiary : colors.surfaceSecondary,
                color: scope === s.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                border: `1px solid ${scope === s.k ? colors.brandTertiary : colors.border}`,
              }}
              data-testid={`customers-scope-${s.k}`}
            >
              {s.label}
            </button>
          ))}
        </div>
        <select
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="customers-filter-tag"
        >
          <option value="">All tags</option>
          {TAG_PRESETS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        {cities.length ? (
          <select
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customers-filter-city"
          >
            <option value="">All cities</option>
            {cities.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        ) : null}
      </div>

      {/* Bulk-actions toolbar (visible when selection exists) */}
      {selected.size > 0 ? (
        <div
          className="mb-3 flex flex-wrap gap-2 items-center rounded-xl px-4 py-2.5"
          style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          data-testid="bulk-toolbar"
        >
          <span className="text-sm font-semibold mr-2">{selected.size} selected</span>
          <select
            value={bulkTag}
            onChange={(e) => setBulkTag(e.target.value)}
            className="text-xs font-semibold px-2 py-1 rounded"
            style={{
              backgroundColor: "#fff",
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <option value="">Choose tag…</option>
            {TAG_PRESETS.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <Button variant="ghost" onClick={() => bulk("add_tag", { tag: bulkTag })} testid="bulk-add-tag">
            <Tag size={14} /> Add tag
          </Button>
          <Button variant="ghost" onClick={() => bulk("remove_tag", { tag: bulkTag })}>
            Remove tag
          </Button>
          <Button variant="ghost" onClick={() => bulk("add_waitlist")} testid="bulk-add-waitlist">
            <BellRing size={14} /> Add to waitlist
          </Button>
          <Button variant="ghost" onClick={() => bulk("remove_waitlist")}>
            Remove from waitlist
          </Button>
          <Gate perm="Customers" action="write">
            <Button variant="danger" onClick={() => bulk("delete")} testid="bulk-delete">
              <Trash2 size={14} /> Delete
            </Button>
          </Gate>
        </div>
      ) : null}

      {/* Data table */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        {filtered === null ? (
          <div className="p-4 space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} style={{ height: 52 }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No customers"
            hint="Try adjusting filters or import a CSV to get started."
          />
        ) : (
          <table className="w-full text-sm" data-testid="customers-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 w-8">
                  <input
                    type="checkbox"
                    onChange={(e) => {
                      if (e.target.checked) setSelected(new Set(filtered.map((r) => r.id)));
                      else setSelected(new Set());
                    }}
                    data-testid="select-all"
                  />
                </th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                  Name
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                  Contact
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                  Address
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                  Next visit
                </th>
                <th className="w-8 px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer hover:bg-zinc-50 transition"
                  style={{ borderTop: `1px solid ${colors.divider}` }}
                  onClick={() => navigate(`/customers/${c.id}`)}
                  data-testid={`customer-row-${c.id}`}
                >
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggle(c.id)}
                      data-testid={`customer-select-${c.id}`}
                    />
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold" style={{ color: colors.onSurface }}>
                        {c.name}
                      </span>
                      {(c.tags || []).map((t) => (
                        <TagChip tag={t} key={t} testid={`row-${c.id}-tag-${t}`} />
                      ))}
                      {c.waitlisted ? <Chip label="Waitlist" tone="warning" /> : null}
                    </div>
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                    <div>{c.phone || "—"}</div>
                    <div className="text-xs" style={{ color: colors.muted }}>
                      {c.email || "—"}
                    </div>
                  </td>
                  <td className="px-3 py-3 hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                    {c.address || "—"}
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>
                    {nextScheduled(c)}
                  </td>
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => navigate(`/customers/${c.id}`)}
                      className="opacity-60 hover:opacity-100"
                    >
                      <MoreVertical size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); load(); }} setToast={setToast} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function ImportModal({ open, onClose, onDone, setToast }) {
  const [busy, setBusy] = useState(false);
  const fileRef = useRef();

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const text = await file.text();
      const res = await api.post("/import/customers", { csv: text });
      setToast({ tone: "success", message: `Imported ${res.created ?? res.count ?? 0} customers` });
      onDone();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setBusy(false);
    }
  };

  const template =
    "name,email,phone,address,notes\nJohn Smith,john@example.com,555-0100,123 Main St, Peoria AZ,VIP customer\n";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import Customers (CSV)"
      testid="customer-import-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={upload} testid="customer-import-upload">
            {busy ? "Uploading…" : "Upload CSV"}
          </Button>
        </>
      }
    >
      <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>
        CSV columns: <code className="text-xs">name, email, phone, address, notes</code>.
        Extra columns are ignored.
      </p>
      <button
        onClick={() => {
          const blob = new Blob([template], { type: "text/csv" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = "customers-template.csv";
          a.click();
          URL.revokeObjectURL(url);
        }}
        className="text-xs font-semibold mb-3"
        style={{ color: colors.brand }}
      >
        Download template CSV
      </button>
      <input ref={fileRef} type="file" accept=".csv,text/csv" data-testid="customer-import-file" />
    </Modal>
  );
}
