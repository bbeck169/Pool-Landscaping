/**
 * FLEET-A · Feb-2026 — Admin fleet-membership manager.
 *
 * Route: /admin/settings/fleet-membership (AdminOnly).
 *
 * Toggles each technician in/out of the fleet. Only in-fleet techs
 * can ping via ``POST /api/fleet/ping`` and appear on the dispatch
 * board.
 *
 * The list is populated by ``GET /api/fleet/membership`` — a
 * server-joined view of every technician + their membership row.
 * Toggles fire ``POST /api/fleet/membership/{tech_id}`` with an
 * optimistic UI update.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Users, RefreshCw, Search as SearchIcon } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";

export default function FleetMembership() {
  const [rows, setRows] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [search, setSearch] = useState("");
  const [notesById, setNotesById] = useState({});

  const load = useCallback(async () => {
    try {
      const res = await api.get("/fleet/membership");
      setRows(res.items || []);
    } catch (e) {
      toast.error(`Membership load failed: ${e?.message || e}`);
      setRows([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = async (row, next) => {
    setBusyId(row.tech_user_id);
    // Optimistic UI — flip the toggle in place.
    setRows((prev) =>
      (prev || []).map((r) =>
        r.tech_user_id === row.tech_user_id ? { ...r, in_fleet: next } : r
      )
    );
    try {
      await api.post(`/fleet/membership/${row.tech_user_id}`, {
        in_fleet: next,
        notes: notesById[row.tech_user_id] ?? row.notes ?? null,
      });
      toast.success(
        next
          ? `${row.tech_name} enabled for fleet tracking`
          : `${row.tech_name} removed from fleet`
      );
    } catch (e) {
      // Revert on failure.
      setRows((prev) =>
        (prev || []).map((r) =>
          r.tech_user_id === row.tech_user_id ? { ...r, in_fleet: !next } : r
        )
      );
      toast.error(`Toggle failed: ${e?.message || e}`);
    } finally {
      setBusyId(null);
    }
  };

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return rows || [];
    return (rows || []).filter(
      (r) =>
        (r.tech_name || "").toLowerCase().includes(s) ||
        (r.email || "").toLowerCase().includes(s) ||
        (r.role || "").toLowerCase().includes(s)
    );
  }, [rows, search]);

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid="admin-fleet-membership-page"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1
            className="text-2xl md:text-3xl font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}
            data-testid="admin-fleet-membership-title"
          >
            <Users size={22} /> Fleet Membership
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Techs must be in the fleet before they can ping or appear on
            the live board. Toggle below.
          </p>
        </div>
        <button
          type="button"
          data-testid="admin-fleet-membership-reload"
          onClick={load}
          className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
        >
          <RefreshCw size={12} /> Reload
        </button>
      </div>

      <div
        className="rounded-2xl p-3 mb-3 flex items-center gap-2"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <SearchIcon size={14} style={{ color: colors.searchIcon }} />
        <input
          type="search"
          data-testid="admin-fleet-membership-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, email, or role"
          className="w-full text-sm outline-none"
          style={{ background: "transparent", color: colors.onSurface }}
        />
      </div>

      {rows === null ? (
        <div style={{ padding: 30, color: colors.muted }}>Loading…</div>
      ) : null}
      {rows !== null && filtered.length === 0 ? (
        <div
          data-testid="admin-fleet-membership-empty"
          className="rounded-2xl p-8 text-center"
          style={{
            backgroundColor: colors.surface,
            border: `1px dashed ${colors.border}`,
            color: colors.muted,
          }}
        >
          No technicians match the current filter.
        </div>
      ) : null}

      {rows !== null && filtered.length > 0 ? (
        <div
          className="rounded-2xl overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary }}>
                <th
                  className="px-3 py-2 text-left font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Technician
                </th>
                <th
                  className="px-3 py-2 text-left font-semibold hidden md:table-cell"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Email
                </th>
                <th
                  className="px-3 py-2 text-left font-semibold hidden md:table-cell"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Notes
                </th>
                <th
                  className="px-3 py-2 text-right font-semibold"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  In Fleet
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.tech_user_id}
                  style={{ borderTop: `1px solid ${colors.divider}` }}
                  data-testid={`fleet-membership-row-${r.tech_user_id}`}
                >
                  <td className="px-3 py-3">
                    <div
                      className="font-semibold"
                      style={{ color: colors.onSurface }}
                    >
                      {r.tech_name}
                    </div>
                    <div
                      className="text-xs"
                      style={{ color: colors.muted }}
                    >
                      {r.role}
                    </div>
                  </td>
                  <td
                    className="px-3 py-3 hidden md:table-cell text-xs"
                    style={{ color: colors.muted }}
                  >
                    {r.email || "—"}
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell">
                    <input
                      type="text"
                      data-testid={`fleet-membership-notes-${r.tech_user_id}`}
                      value={notesById[r.tech_user_id] ?? r.notes ?? ""}
                      onChange={(e) =>
                        setNotesById((prev) => ({
                          ...prev,
                          [r.tech_user_id]: e.target.value,
                        }))
                      }
                      placeholder="Optional notes"
                      className="w-full text-xs px-2 py-1 rounded"
                      style={{
                        background: colors.surfaceSecondary,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface,
                      }}
                    />
                  </td>
                  <td className="px-3 py-3 text-right">
                    <button
                      type="button"
                      data-testid={`fleet-membership-toggle-${r.tech_user_id}`}
                      disabled={busyId === r.tech_user_id}
                      onClick={() => toggle(r, !r.in_fleet)}
                      className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold"
                      style={{
                        background: r.in_fleet ? "#DCFCE7" : colors.surfaceSecondary,
                        color: r.in_fleet ? "#166534" : colors.muted,
                        border: `1px solid ${r.in_fleet ? "#4ADE80" : colors.border}`,
                      }}
                    >
                      {r.in_fleet ? "In Fleet" : "Out"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
