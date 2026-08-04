/**
 * Phase 25 · Property Lookup — desktop tech/admin surface.
 * Search by address, view Zillow facts, save notes, browse history.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Search, MapPin, Home as HomeIcon, Clock, Save, AlertCircle, Info } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { ZillowUsageChip } from "@/components/ZillowUsageChip";

export default function PropertyLookupPage() {
  const nav = useNavigate();
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [note, setNote] = useState("");
  const [noteMsg, setNoteMsg] = useState("");
  const [history, setHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);
  const [usageBump, setUsageBump] = useState(0);

  const runSearch = async (addr) => {
    const q = (addr ?? address).trim();
    if (q.length < 5) { setError("Enter a full property address"); return; }
    setLoading(true); setError(null); setResult(null); setNoteMsg("");
    setRateLimited(false);
    try {
      const r = await api.get(
        `/property/search?address=${encodeURIComponent(q)}`);
      setResult(r);
      setAddress(r.property?.address || q);
      setUsageBump((n) => n + 1);
    } catch (e) {
      if (String(e?.message || "").includes("429")) setRateLimited(true);
      setError(e.message || "Search failed");
    } finally { setLoading(false); }
  };

  const loadHistory = useCallback(async () => {
    const r = await api.get("/property/history");
    setHistory(r.items || []);
  }, []);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const saveNote = async () => {
    if (!note.trim() || !result?.property?.address) return;
    setNoteMsg("");
    try {
      await api.post("/property/save-note", {
        address: result.property.address, note,
      });
      setNoteMsg("Saved ✓"); setNote("");
    } catch (e) { setNoteMsg(e.message); }
  };

  const p = result?.property;
  const isMocked = !!result?.mocked;

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6"
         data-testid="property-lookup-page">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="prop-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <HomeIcon size={22} style={{ color: colors.brand }} />
            Property lookup
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Search any address, look up Zillow zestimate, owner, sale history,
            and neighborhood comps. Cached 24h, 30 lookups/hour.
          </p>
        </div>
        <button onClick={() => setShowHistory(!showHistory)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="prop-history-toggle">
          <Clock size={14} /> History ({history.length})
        </button>
      </div>

      <div className="mb-4">
        <ZillowUsageChip rateLimited={rateLimited} refreshKey={usageBump}
                          testid="prop-zillow-chip" />
      </div>

      <div className="flex gap-2 mb-4">
        <input value={address} onChange={(e) => setAddress(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && runSearch()}
               placeholder="742 Evergreen Terrace, Springfield, OR"
               className="flex-1 px-3 py-2 text-base rounded-xl"
               style={{ backgroundColor: colors.surface,
                         border: `1px solid ${colors.border}` }}
               data-testid="prop-address-input" />
        <button onClick={() => runSearch()} disabled={loading}
                className="px-4 py-2 font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="prop-search-btn">
          <Search size={14} /> Search
        </button>
      </div>

      {showHistory ? (
        <div className="rounded-2xl p-4 mb-4"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="prop-history-panel">
          <div className="text-sm font-bold mb-2"
               style={{ color: colors.onSurface }}>Recent lookups</div>
          {history.length === 0 ? (
            <div className="text-xs" style={{ color: colors.muted }}>
              No lookups yet.
            </div>
          ) : (
            <div className="space-y-1">
              {history.slice(0, 10).map((h, i) => (
                <button key={i}
                        onClick={() => runSearch(h.address)}
                        className="w-full text-left flex items-center gap-2 px-2 py-1 text-xs rounded"
                        style={{ color: colors.onSurface }}
                        data-testid={`prop-history-row-${i}`}
                        onMouseOver={(e) => e.currentTarget.style.backgroundColor = colors.background}
                        onMouseOut={(e) => e.currentTarget.style.backgroundColor = "transparent"}>
                  <MapPin size={10} style={{ color: colors.brand }} />
                  <span className="flex-1">{h.address}</span>
                  <span style={{ color: colors.muted }}>
                    {(h.ts || "").slice(0, 16).replace("T", " ")}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.muted }}>
          Searching Zillow…
        </div>
      ) : null}

      {error ? (
        <div className="rounded-xl p-3 mb-4 text-sm flex items-center gap-2"
             style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
             data-testid="prop-error">
          <AlertCircle size={14} /> {error}
        </div>
      ) : null}

      {p ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            {isMocked ? (
              <div className="rounded-xl p-3 text-sm flex items-center gap-2"
                   style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                   data-testid="prop-mock-banner">
                <Info size={14} />
                Live Zillow data unavailable — {result.reason
                                                  || "provider offline"}.
                Only the entered address is shown.
              </div>
            ) : null}

            {p.photos && p.photos.length > 0 ? (
              <div className="rounded-2xl overflow-hidden"
                   style={{ backgroundColor: colors.surface,
                            border: `1px solid ${colors.border}` }}>
                <img src={p.photos[0]} alt=""
                       style={{ width: "100%", height: 300,
                                 objectFit: "cover" }} />
              </div>
            ) : null}

            <div className="rounded-2xl p-5"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
              <div className="text-2xl font-bold"
                   style={{ color: colors.onSurface }}
                   data-testid="prop-result-address">
                {p.address}
              </div>
              {p.city || p.state ? (
                <div className="text-sm"
                     style={{ color: colors.muted }}>
                  {p.city}{p.state ? `, ${p.state}` : ""}
                  {p.zipcode ? ` ${p.zipcode}` : ""}
                </div>
              ) : null}
              {p.zestimate ? (
                <div className="mt-4 p-4 rounded-xl"
                     style={{ backgroundColor: `${colors.brand}10` }}>
                  <div className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.brand }}>Zestimate</div>
                  <div className="text-4xl font-bold mt-1"
                       style={{ color: colors.brand }}
                       data-testid="prop-zestimate">
                    ${Number(p.zestimate).toLocaleString()}
                  </div>
                </div>
              ) : null}

              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4">
                {[
                  ["Beds", p.beds],
                  ["Baths", p.baths],
                  ["Sqft", p.sqft ? Number(p.sqft).toLocaleString() : null],
                  ["Year built", p.year_built],
                  ["Lot size", p.lot_size],
                  ["Type", p.property_type],
                ].filter(([_, v]) => v).map(([l, v], i) => (
                  <div key={i} className="rounded-xl p-3"
                       style={{ backgroundColor: colors.background }}>
                    <div className="text-[10px] font-bold uppercase tracking-wider"
                         style={{ color: colors.muted }}>{l}</div>
                    <div className="text-base font-bold mt-1"
                         style={{ color: colors.onSurface }}>
                      {String(v)}
                    </div>
                  </div>
                ))}
              </div>

              {p.owner_name || p.last_sale_price || p.tax_assessment ? (
                <div className="mt-4 pt-4 border-t"
                     style={{ borderColor: colors.border }}>
                  <h2 className="text-sm font-bold mb-2"
                      style={{ color: colors.onSurface }}>
                    Ownership & taxes
                  </h2>
                  <dl className="text-sm space-y-1">
                    {p.owner_name ? (
                      <div className="flex justify-between">
                        <dt style={{ color: colors.muted }}>Owner</dt>
                        <dd style={{ color: colors.onSurface }}>
                          {p.owner_name}
                        </dd>
                      </div>
                    ) : null}
                    {p.last_sale_price ? (
                      <div className="flex justify-between">
                        <dt style={{ color: colors.muted }}>Last sale</dt>
                        <dd style={{ color: colors.onSurface }}>
                          ${Number(p.last_sale_price).toLocaleString()}
                          {p.last_sale_date ? ` (${p.last_sale_date})` : ""}
                        </dd>
                      </div>
                    ) : null}
                    {p.tax_assessment ? (
                      <div className="flex justify-between">
                        <dt style={{ color: colors.muted }}>Tax assessment</dt>
                        <dd style={{ color: colors.onSurface }}>
                          ${Number(p.tax_assessment).toLocaleString()}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </div>
              ) : null}
            </div>

            {p.neighborhood_comps && p.neighborhood_comps.length > 0 ? (
              <div className="rounded-2xl p-5"
                   style={{ backgroundColor: colors.surface,
                            border: `1px solid ${colors.border}` }}>
                <h2 className="text-lg font-bold mb-3"
                    style={{ color: colors.onSurface }}>
                  Neighborhood comps
                </h2>
                <div className="flex gap-3 overflow-x-auto pb-2">
                  {p.neighborhood_comps.map((c, i) => (
                    <div key={i}
                         className="rounded-xl overflow-hidden shrink-0"
                         style={{ width: 220,
                                    backgroundColor: colors.background,
                                    border: `1px solid ${colors.border}` }}
                         data-testid={`prop-comp-${i}`}>
                      {c.photo ? (
                        <img src={c.photo} alt=""
                               style={{ width: "100%", height: 120,
                                          objectFit: "cover" }} />
                      ) : (
                        <div className="w-full flex items-center justify-center"
                             style={{ height: 120,
                                      backgroundColor: colors.surface,
                                      color: colors.muted }}>
                          <HomeIcon size={28} />
                        </div>
                      )}
                      <div className="p-2">
                        <div className="text-xs font-bold truncate"
                             style={{ color: colors.onSurface }}>
                          {c.address || "—"}
                        </div>
                        {c.price ? (
                          <div className="text-sm font-bold mt-1"
                               style={{ color: colors.brand }}>
                            ${Number(c.price).toLocaleString()}
                          </div>
                        ) : null}
                        <div className="text-[10px] mt-1"
                             style={{ color: colors.muted }}>
                          {[c.beds && `${c.beds}bd`,
                              c.baths && `${c.baths}ba`,
                              c.sqft && `${Number(c.sqft).toLocaleString()} sqft`]
                              .filter(Boolean).join(" · ")}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="space-y-4">
            <div className="rounded-2xl p-5"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
              <h2 className="text-lg font-bold mb-3 flex items-center gap-2"
                  style={{ color: colors.onSurface }}>
                <Save size={16} /> Save a note
              </h2>
              <textarea value={note}
                          onChange={(e) => setNote(e.target.value)}
                          rows={4}
                          placeholder='e.g. "Big backyard — quarterly service"'
                          className="w-full p-3 rounded-lg text-sm"
                          style={{ backgroundColor: colors.background,
                                   border: `1px solid ${colors.border}` }}
                          data-testid="prop-note-input" />
              <button onClick={saveNote}
                      disabled={!note.trim()}
                      className="mt-2 w-full px-4 py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: colors.brand,
                               color: "#fff", opacity: note.trim() ? 1 : 0.5 }}
                      data-testid="prop-note-save">
                {noteMsg || "Save note"}
              </button>
            </div>

            <div className="rounded-2xl p-4 text-xs"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.muted }}>
              Data via Zillow / OpenWebNinja.
              {result.cached ? " Cached." : " Fresh."}
              {isMocked ? " · Explicit-mocked response." : ""}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
