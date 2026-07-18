/**
 * Phase T6 — Service Price Checker (admin only).
 * Reads /calculators/service-price-market for the state + service_type
 * enums, then POSTs /calculators/service-price-check for a specific
 * check + tenant-median comparison.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, MapPin, Copy } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function copy(text) { if (navigator.clipboard) navigator.clipboard.writeText(text); }

export default function ServicePriceChecker() {
  const nav = useNavigate();
  const [index, setIndex] = useState(null);
  const [state, setState] = useState("AZ");
  const [svcType, setSvcType] = useState("weekly_pool_service");
  const [size, setSize] = useState("");
  const [result, setResult] = useState(null);
  const [ref, setRef] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.get("/calculators/service-price-market").then(setIndex).catch(() => setIndex({states: [], service_types: [], service_type_labels: {}}));
  }, []);

  useEffect(() => {
    if (!state) { setRef(null); return; }
    api.get(`/calculators/service-price-market/${state}`).then(setRef).catch(() => setRef(null));
  }, [state]);

  const check = async () => {
    setErr(null);
    try {
      const r = await api.post("/calculators/service-price-check", {
        state_code: state, service_type: svcType, business_size: size || null,
      });
      setResult(r);
    } catch (e) { setErr(e.message); }
  };

  if (!index) return null;

  const pos = result?.market_position;
  const posColor = pos === "below_market" ? "#991B1B"
    : pos === "above_market" ? "#166534"
    : pos === "at_market" ? colors.brand : colors.muted;

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="price-checker-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="pc-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            <MapPin size={22} style={{ color: colors.brand }} />
            Service Price Checker
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Admin-only. 51-state market-rate lookup with tenant-median comparison.
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-6 space-y-3"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block">
            <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>State</span>
            <select value={state} onChange={(e) => setState(e.target.value)}
                    className="mt-1 w-full rounded-lg px-3 py-2"
                    style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                    data-testid="pc-state">
              {index.states.map(s => (
                <option key={s.state_code} value={s.state_code}>{s.state_name} ({s.state_code})</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Service type</span>
            <select value={svcType} onChange={(e) => setSvcType(e.target.value)}
                    className="mt-1 w-full rounded-lg px-3 py-2"
                    style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                    data-testid="pc-svctype">
              {index.service_types.map(t => (
                <option key={t} value={t}>{index.service_type_labels[t] || t}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Business size (optional)</span>
            <select value={size} onChange={(e) => setSize(e.target.value)}
                    className="mt-1 w-full rounded-lg px-3 py-2"
                    style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                    data-testid="pc-size">
              <option value="">— any —</option>
              <option value="small">Small (&lt; 100 customers)</option>
              <option value="medium">Medium (100-300)</option>
              <option value="large">Large (&gt; 300)</option>
            </select>
          </label>
        </div>

        <button onClick={check}
                className="w-full py-2 rounded-xl font-bold"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="pc-check">Check market rate</button>
        {err ? <div className="text-sm" style={{color: "#991B1B"}}>{err}</div> : null}
      </div>

      {result ? (
        <div className="mt-4 rounded-2xl p-6 space-y-3"
             style={{ backgroundColor: `${colors.brand}10`, border: `1px solid ${colors.brand}44` }}
             data-testid="pc-result">
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.brand }}>
            {result.state_name} · {result.service_label} · Region: {result.region}
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Low</div>
              <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>${result.market_rate.low}</div>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.brand }}>Median</div>
              <div className="text-2xl font-bold" style={{ color: colors.brand }}>${result.market_rate.median}</div>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>High</div>
              <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>${result.market_rate.high}</div>
            </div>
          </div>
          {result.business_size_suggestion ? (
            <div className="text-xs" style={{ color: colors.muted }}>
              Business-size suggestion: <b>{result.business_size_suggestion}</b> band recommended.
            </div>
          ) : null}
          {result.your_median_price != null ? (
            <div className="rounded-lg p-3"
                 style={{ backgroundColor: colors.surface, border: `1px solid ${posColor}55` }}
                 data-testid="pc-gap">
              <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>
                Your tenant's median: <span style={{ color: posColor }}>${result.your_median_price}</span> ({(result.market_position || "").replace(/_/g, " ")})
              </div>
              <div className="text-sm" style={{ color: colors.onSurface }}>{result.gap_recommendation}</div>
            </div>
          ) : (
            <div className="text-xs" style={{ color: colors.muted }}>
              No matching tenant billing plans for this service type — market-only comparison.
            </div>
          )}
          <div className="text-xs italic" style={{ color: colors.muted }}>{result.notes}</div>
          <button onClick={() => copy(
            `${result.state_name} ${result.service_label}: low $${result.market_rate.low} · median $${result.market_rate.median} · high $${result.market_rate.high}` +
            (result.your_median_price ? ` — your median $${result.your_median_price} (${result.market_position})` : "")
          )} className="text-xs font-semibold rounded-lg px-2 py-1 flex items-center gap-1"
             style={{ backgroundColor: `${colors.brand}22`, color: colors.brand }}
             data-testid="pc-copy">
            <Copy size={12} /> Copy summary
          </button>
        </div>
      ) : null}

      {ref ? (
        <div className="mt-4 rounded-2xl p-6"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="pc-reftable">
          <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>
            All {ref.state_name} service rates
          </div>
          <table className="w-full text-sm">
            <thead><tr style={{ color: colors.muted }}>
              <th className="text-left py-1">Service</th>
              <th className="text-right">Low</th>
              <th className="text-right">Median</th>
              <th className="text-right">High</th>
            </tr></thead>
            <tbody>
              {Object.entries(ref.market_rates).map(([k, v]) => (
                <tr key={k}>
                  <td className="py-1">{ref.service_type_labels?.[k] || k}</td>
                  <td className="text-right">${v.low}</td>
                  <td className="text-right font-bold" style={{color: colors.brand}}>${v.median}</td>
                  <td className="text-right">${v.high}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-xs mt-2" style={{ color: colors.muted }}>
            Cost-of-living index: {ref.cost_of_living_index}
          </div>
        </div>
      ) : null}
    </div>
  );
}
