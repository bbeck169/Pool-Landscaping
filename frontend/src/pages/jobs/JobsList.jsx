import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Plus,
  Search,
  Filter,
  Briefcase,
  Grid3x3,
  Rows,
  Calendar,
  User,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  PageHeader,
  Button,
  Skeleton,
  StatusPill,
  Chip,
  EmptyState,
  TagChip,
} from "@/components/ui-kit";
import { useAuth } from "@/auth";
import { useAttendance } from "@/hooks/useAttendance";
import WeatherWidget5Day from "@/pages/aitools/WeatherWidget5Day";

const STATUS_ORDER = ["scheduled", "active", "pending", "requested", "completed", "reopened", "cancelled"];

export default function JobsList() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const attendance = useAttendance();
  const [search, setSearch] = useSearchParams();
  const [jobs, setJobs] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [techs, setTechs] = useState([]);
  const [view, setView] = useState("list"); // list | kanban

  const status = search.get("status") || "";
  const techId = search.get("technician_id") || "";
  const q = search.get("q") || "";
  const setParam = (k, v) => {
    const s = new URLSearchParams(search);
    if (v) s.set(k, v);
    else s.delete(k);
    setSearch(s, { replace: true });
  };

  const load = async () => {
    try {
      const [j, c, t] = await Promise.all([
        api.get("/jobs"),
        api.get("/customers").catch(() => []),
        api.get("/technicians").catch(() => []),
      ]);
      setJobs(j || []);
      setCustomers(c || []);
      setTechs(t || []);
    } catch {
      setJobs([]);
    }
  };
  useEffect(() => {
    load();
  }, []);

  const isTech = user?.role === "technician";
  const locked = isTech && !attendance.clockedIn;

  const filtered = useMemo(() => {
    if (!jobs) return null;
    const cById = Object.fromEntries(customers.map((c) => [c.id, c]));
    return jobs
      .map((j) => ({ ...j, _tags: cById[j.customer_id]?.tags || [] }))
      .filter((j) => (status ? j.status === status : true))
      .filter((j) => (techId ? j.technician_id === techId : true))
      .filter((j) =>
        q
          ? [j.title, j.customer_name, j.address, j.service_type]
              .filter(Boolean)
              .some((s) => s.toLowerCase().includes(q.toLowerCase()))
          : true
      );
  }, [jobs, customers, status, techId, q]);

  const kanban = useMemo(() => {
    const g = {};
    for (const s of STATUS_ORDER) g[s] = [];
    (filtered || []).forEach((j) => {
      const k = STATUS_ORDER.includes(j.status) ? j.status : "pending";
      g[k].push(j);
    });
    return g;
  }, [filtered]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="jobs-page">
      {isTech && (
        <div className="mb-4" data-testid="tech-weather-strip">
          <WeatherWidget5Day role="technician" />
        </div>
      )}
      <PageHeader
        title="Jobs"
        subtitle={
          isTech && !attendance.clockedIn
            ? "Read-only — clock in to open a job."
            : `${(filtered || []).length} shown`
        }
        right={
          <>
            <div
              className="flex rounded-lg overflow-hidden"
              style={{ border: `1px solid ${colors.border}` }}
            >
              {[
                { k: "list", icon: Rows },
                { k: "kanban", icon: Grid3x3 },
              ].map((v) => (
                <button
                  key={v.k}
                  onClick={() => setView(v.k)}
                  className="px-3 py-2 text-sm"
                  style={{
                    backgroundColor: view === v.k ? colors.brandTertiary : colors.surface,
                    color: view === v.k ? colors.onBrandTertiary : colors.muted,
                  }}
                  data-testid={`jobs-view-${v.k}`}
                >
                  <v.icon size={14} />
                </button>
              ))}
            </div>
            {user?.role !== "customer" ? (
              <Button
                onClick={() => navigate("/jobs/new")}
                testid="jobs-new-button"
                disabled={isTech}
              >
                <Plus size={16} /> New Job
              </Button>
            ) : null}
          </>
        }
      />

      {locked ? (
        <div
          className="mb-4 rounded-xl px-4 py-3 flex items-center gap-2"
          style={{ backgroundColor: "#FEF3C7", color: "#92400E", border: "1px solid #FDE68A" }}
          data-testid="jobs-lock-banner"
        >
          🔒 Clock in on the mobile app to open a job. Web schedule view is read-only.
        </div>
      ) : null}

      {/* Filter row */}
      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.muted }} />
          <input
            value={q}
            onChange={(e) => setParam("q", e.target.value)}
            placeholder="Search title, customer, address…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
            style={{
              backgroundColor: colors.surfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="jobs-search"
          />
        </div>
        <select
          value={status}
          onChange={(e) => setParam("status", e.target.value)}
          className="text-xs font-semibold px-3 py-2 rounded-lg"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="jobs-filter-status"
        >
          <option value="">All statuses</option>
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {s[0].toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        {techs.length ? (
          <select
            value={techId}
            onChange={(e) => setParam("technician_id", e.target.value)}
            className="text-xs font-semibold px-3 py-2 rounded-lg"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="jobs-filter-tech"
          >
            <option value="">All techs</option>
            {techs.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {/* List / kanban */}
      {filtered === null ? (
        <Skeleton style={{ height: 300 }} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Briefcase} title="No jobs match" hint="Try clearing filters or create a new job." />
      ) : view === "list" ? (
        <div
          className="rounded-2xl overflow-hidden"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-sm" data-testid="jobs-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Job</th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Customer</th>
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Tech</th>
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Scheduled</th>
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => (
                <tr
                  key={j.id}
                  onClick={() => (locked ? undefined : navigate(`/jobs/${j.id}`))}
                  className={locked ? "" : "cursor-pointer hover:bg-zinc-50"}
                  style={{
                    borderTop: `1px solid ${colors.divider}`,
                    opacity: locked ? 0.55 : 1,
                  }}
                  data-testid={`job-row-${j.id}`}
                >
                  <td className="px-3 py-3">
                    <div className="font-semibold" style={{ color: colors.onSurface }}>{j.title}</div>
                    <div className="text-xs" style={{ color: colors.muted }}>{j.service_type}</div>
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span style={{ color: colors.onSurfaceSecondary }}>{j.customer_name}</span>
                      {(j._tags || []).slice(0, 2).map((t) => (
                        <TagChip tag={t} key={t} />
                      ))}
                    </div>
                    <div className="text-xs" style={{ color: colors.muted }}>{j.address}</div>
                  </td>
                  <td className="px-3 py-3 hidden lg:table-cell text-xs" style={{ color: colors.onSurfaceSecondary }}>
                    <User size={12} className="inline mr-1" />{j.technician_name || "Unassigned"}
                  </td>
                  <td className="px-3 py-3 hidden lg:table-cell text-xs" style={{ color: colors.muted }}>
                    <Calendar size={12} className="inline mr-1" />{j.scheduled_date || "—"}
                  </td>
                  <td className="px-3 py-3 text-right"><StatusPill status={j.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-3" data-testid="jobs-kanban">
          {STATUS_ORDER.map((s) => (
            <div
              key={s}
              className="rounded-2xl p-3"
              style={{ backgroundColor: colors.surfaceSecondary, minHeight: 200 }}
            >
              <div className="flex items-center justify-between mb-3">
                <StatusPill status={s} />
                <span className="text-xs font-semibold" style={{ color: colors.muted }}>
                  {kanban[s].length}
                </span>
              </div>
              <div className="space-y-2">
                {kanban[s].slice(0, 20).map((j) => (
                  <button
                    key={j.id}
                    onClick={() => (locked ? undefined : navigate(`/jobs/${j.id}`))}
                    className="w-full text-left rounded-xl p-3"
                    style={{
                      backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}`,
                      opacity: locked ? 0.55 : 1,
                    }}
                    data-testid={`kanban-card-${j.id}`}
                  >
                    <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                      {j.title}
                    </div>
                    <div className="text-xs" style={{ color: colors.muted }}>
                      {j.customer_name}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
