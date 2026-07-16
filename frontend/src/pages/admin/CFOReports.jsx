/**
 * Phase 51.K — CFO Reports: COGS · AP Aging · Payroll.
 * Endpoints: /api/cfo/cogs · /api/cfo/ap-aging · /api/cfo/payroll
 */
import React, { useEffect, useState } from "react";
import { PieChart, Users, Receipt, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function fmtMoney(cents) { return `$${(Number(cents || 0) / 100).toFixed(2)}`; }
function currentMonth() { return new Date().toISOString().slice(0, 7); }

export default function CFOReports() {
  const [cogs, setCogs] = useState(null);
  const [ap, setAp] = useState(null);
  const [payroll, setPayroll] = useState(null);
  const [period, setPeriod] = useState(currentMonth());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const [y, m] = period.split("-").map(Number);
      const [c, a, p] = await Promise.all([
        api.get(`/cfo/cogs?year=${y}&month=${m}`),
        api.get("/cfo/ap-aging"),
        api.get(`/cfo/payroll?period=${period}`),
      ]);
      setCogs(c); setAp(a); setPayroll(p);
    } catch (e) { setError(e?.message || "Failed to load"); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [period]);

  const cogsRows = cogs ? [
    { label: "Materials (chemicals)", cents: cogs.materials_cents },
    { label: "Labor (direct)", cents: cogs.labor_cents },
    { label: "Equipment / Inventory", cents: cogs.equipment_cents },
  ] : [];

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="cfo-reports-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center"
               style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
            <PieChart size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>CFO Reports</h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Real COGS · AP Aging · Payroll — replaces the Phase 32 mocks.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)}
                 className="text-sm px-2 py-1.5 rounded-md"
                 style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                 data-testid="cfo-reports-period" />
          <button type="button" onClick={load}
                  className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
                  style={{ border: `1px solid ${colors.border}`, color: colors.onSurface, background: colors.surface }}
                  data-testid="cfo-reports-refresh">
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="cfo-reports-error">{error}</div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>Loading…</div>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {/* COGS card */}
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="cfo-reports-cogs-card">
            <div className="px-4 py-3 flex items-center gap-2" style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
              <PieChart size={14} style={{ color: colors.muted }} />
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>COGS breakdown</span>
              <div style={{ flex: 1 }} />
              <span className="text-xs font-bold" style={{ color: colors.onSurface }}
                    data-testid="cfo-reports-cogs-total">
                {fmtMoney(cogs?.total_cents)}
              </span>
            </div>
            <table className="w-full text-sm" data-testid="cfo-reports-cogs-table">
              <tbody>
                {cogsRows.map((r) => (
                  <tr key={r.label} style={{ borderBottom: `1px solid ${colors.border}` }}>
                    <td className="px-4 py-2" style={{ color: colors.onSurface }}>{r.label}</td>
                    <td className="px-4 py-2 text-right font-semibold" style={{ color: colors.onSurface }}>{fmtMoney(r.cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* AP Aging card */}
          <div className="rounded-2xl overflow-hidden"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="cfo-reports-ap-card">
            <div className="px-4 py-3 flex items-center gap-2" style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
              <Receipt size={14} style={{ color: colors.muted }} />
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>AP Aging</span>
              <div style={{ flex: 1 }} />
              <span className="text-xs font-bold" style={{ color: colors.onSurface }}
                    data-testid="cfo-reports-ap-total">
                {fmtMoney(ap?.total_open_cents)}
              </span>
            </div>
            <table className="w-full text-sm">
              <tbody>
                {[
                  { label: "Current (not due)", cents: ap?.current_cents, key: "current" },
                  { label: "1–30 days overdue", cents: ap?.["1_30_cents"], key: "1_30" },
                  { label: "31–60 days overdue", cents: ap?.["31_60_cents"], key: "31_60" },
                  { label: "61–90 days overdue", cents: ap?.["61_90_cents"], key: "61_90" },
                  { label: "90+ days overdue", cents: ap?.over_90_cents, key: "90plus" },
                ].map((r) => (
                  <tr key={r.key} style={{ borderBottom: `1px solid ${colors.border}` }}
                      data-testid={`cfo-reports-ap-row-${r.key}`}>
                    <td className="px-4 py-2" style={{ color: colors.onSurface }}>{r.label}</td>
                    <td className="px-4 py-2 text-right font-semibold" style={{ color: colors.onSurface }}>{fmtMoney(r.cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Payroll card */}
          <div className="md:col-span-2 rounded-2xl overflow-hidden"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="cfo-reports-payroll-card">
            <div className="px-4 py-3 flex items-center gap-2" style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
              <Users size={14} style={{ color: colors.muted }} />
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Payroll — {period}</span>
              <div style={{ flex: 1 }} />
              <span className="text-xs font-bold" style={{ color: colors.onSurface }}
                    data-testid="cfo-reports-payroll-total">
                {fmtMoney(payroll?.total_cents)}
              </span>
            </div>
            <table className="w-full text-sm" data-testid="cfo-reports-payroll-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <th className="text-left px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Employee</th>
                  <th className="text-right px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Hourly rate</th>
                  <th className="text-right px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Hours</th>
                  <th className="text-right px-4 py-2 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Cost</th>
                </tr>
              </thead>
              <tbody>
                {(payroll?.employees || []).length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-6 text-center text-sm" style={{ color: colors.muted }}>
                    No hours logged in this period.
                  </td></tr>
                ) : (
                  (payroll?.employees || []).map((e) => (
                    <tr key={e.user_id} data-testid={`cfo-reports-payroll-row-${e.user_id}`}
                        style={{ borderBottom: `1px solid ${colors.border}` }}>
                      <td className="px-4 py-2" style={{ color: colors.onSurface }}>{e.name}</td>
                      <td className="px-4 py-2 text-right" style={{ color: colors.muted }}>{fmtMoney(e.hourly_rate_cents)}/hr</td>
                      <td className="px-4 py-2 text-right" style={{ color: colors.muted }}>{(e.minutes / 60).toFixed(1)}h</td>
                      <td className="px-4 py-2 text-right font-semibold" style={{ color: colors.onSurface }}>{fmtMoney(e.cost_cents)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
