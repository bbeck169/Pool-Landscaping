/**
 * QuoteIQ Q4 · Public InstaQuote page — `/quote/:slug`.
 *
 * Unauthenticated. Rendered by the SAME React app but outside the
 * protected AppLayout — no sidebar, no nav. Tenant branding is
 * applied from the public config payload. Server recomputes the
 * total; the number rendered here is a *preview only* — the real
 * price is whatever comes back in the submit response.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Loader2 } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;

function fmt$(cents) {
  return `$${(Number(cents || 0) / 100).toFixed(2)}`;
}

export default function PublicInstaQuotePage() {
  const { slug } = useParams();
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState("");
  const [selections, setSelections] = useState({});
  const [contact, setContact] = useState({});
  const [hp, setHp] = useState("");   // Honeypot — must stay empty.
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    fetch(`${BASE}/api/public/instaquote/${slug}`)
      .then(async (r) => {
        if (r.ok) return r.json();
        throw new Error("Not found");
      })
      .then(setCfg)
      .catch((e) => setError(e.message || "Not found"));
  }, [slug]);

  // Client-side price preview. The server truth wins at submit.
  const preview = useMemo(() => {
    if (!cfg) return { total: 0, rows: [] };
    const svcMap = {}; (cfg.services || []).forEach((s) => (svcMap[s.id] = s));
    const addonMap = {}; (cfg.add_ons || []).forEach((a) => (addonMap[a.id] = a));
    const freqMap = {}; (cfg.frequencies || []).forEach((f) => (freqMap[f.id] = f));
    let total = 0;
    const rows = [];
    for (const [sid, sel] of Object.entries(selections)) {
      const s = svcMap[sid];
      if (!s || !sel.qty) continue;
      const qty = Math.max(s.min_qty || 0,
                            Math.min(s.max_qty || Number(sel.qty),
                                      Number(sel.qty)));
      const f = freqMap[sel.frequency_id] || { multiplier: 1, label: "" };
      let addonsSum = 0;
      const addons = [];
      for (const aid of sel.add_on_ids || []) {
        const a = addonMap[aid];
        if (!a) continue;
        addons.push(a); addonsSum += a.price_cents;
      }
      const line = Math.round(
          (s.base_price_cents * qty + addonsSum) * (f.multiplier || 1));
      total += line;
      rows.push({ label: s.name, qty, freq: f.label, addons, line });
    }
    return { total, rows };
  }, [cfg, selections]);

  const setSel = (sid, patch) => setSelections((s) => ({
    ...s, [sid]: { ...(s[sid] || {}), ...patch },
  }));
  const toggleAddOn = (sid, aid) => {
    const cur = selections[sid]?.add_on_ids || [];
    setSel(sid, {
      add_on_ids: cur.includes(aid)
        ? cur.filter((x) => x !== aid) : [...cur, aid],
    });
  };

  const submit = async () => {
    setBusy(true); setError("");
    try {
      const body = {
        contact,
        selections: Object.entries(selections)
          .filter(([, v]) => v?.qty)
          .map(([sid, v]) => ({
            service_id: sid,
            qty: Number(v.qty),
            frequency_id: v.frequency_id,
            add_on_ids: v.add_on_ids || [],
            custom_notes: v.custom_notes || "",
          })),
        _hp: hp,
      };
      const r = await fetch(`${BASE}/api/public/instaquote/${slug}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      if (data.success_redirect_url) {
        window.location.href = data.success_redirect_url;
        return;
      }
      setDone(data);
    } catch (e) {
      setError(e.message || "Submit failed");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", alignItems: "center",
        justifyContent: "center", flexDirection: "column",
        padding: 24, background: "#f4f4f5",
      }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>Not found</div>
        <div style={{ color: "#71717a", marginTop: 6 }}>{error}</div>
      </div>
    );
  }
  if (!cfg) {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", alignItems: "center",
        justifyContent: "center", background: "#f4f4f5",
      }}>
        <Loader2 className="animate-spin" size={24} />
      </div>
    );
  }
  if (done) {
    return (
      <div style={{
        minHeight: "100vh", background: "#f4f4f5",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24,
      }}
            data-testid="iq-done">
        <div style={{
          maxWidth: 480, background: "#fff", borderRadius: 16,
          padding: 32, borderTop: `4px solid ${cfg.brand_color || "#0284C7"}`,
          boxShadow: "0 8px 24px rgba(0,0,0,0.06)",
        }}>
          <CheckCircle2 color="#10b981" size={48} />
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: "12px 0 6px" }}>
            Thanks!
          </h1>
          <div style={{ color: "#52525b", marginBottom: 12 }}>
            Your estimate: <b>{fmt$(done.total_cents)}</b>
          </div>
          <div
              dangerouslySetInnerHTML={{ __html: cfg.thank_you_html || "" }}
              style={{ color: "#3f3f46" }}
          />
        </div>
      </div>
    );
  }

  const brand = cfg.brand_color || "#0284C7";
  const CF = cfg.collect_fields || {};

  return (
    <div style={{ minHeight: "100vh", background: "#f4f4f5" }}
          data-testid="iq-public-page">
      <div style={{
        maxWidth: 760, margin: "0 auto", padding: 24,
        background: "#fff", minHeight: "100vh",
        borderTop: `6px solid ${brand}`,
      }}>
        <header style={{ display: "flex", alignItems: "center", gap: 12,
                          marginBottom: 20 }}>
          {cfg.logo_url && (
            <img src={cfg.logo_url} alt="" style={{ height: 32 }} />
          )}
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 800, margin: 0 }}>
              {cfg.headline}
            </h1>
            {cfg.subheadline && (
              <div style={{ color: "#71717a", marginTop: 4 }}>
                {cfg.subheadline}
              </div>
            )}
          </div>
        </header>

        <div>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>
            1 · Choose your services
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {(cfg.services || []).map((s) => (
              <div key={s.id}
                    style={{ border: "1px solid #e4e4e7", borderRadius: 12,
                              padding: 14 }}
                    data-testid={`iq-svc-${s.id}`}>
                <div style={{ display: "flex", justifyContent: "space-between",
                                gap: 8, alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{s.name}</div>
                    {s.description && (
                      <div style={{ color: "#71717a", fontSize: 13,
                                     marginTop: 2 }}>
                        {s.description}
                      </div>
                    )}
                    <div style={{ color: "#71717a", fontSize: 12,
                                    marginTop: 2 }}>
                      {fmt$(s.base_price_cents)} / {s.unit}
                    </div>
                  </div>
                  <input type="number"
                          value={selections[s.id]?.qty || ""}
                          onChange={(e) => setSel(s.id, { qty: e.target.value })}
                          min={s.min_qty} max={s.max_qty}
                          placeholder="0"
                          style={{ width: 72, textAlign: "right",
                                    padding: 8, borderRadius: 8,
                                    border: "1px solid #d4d4d8" }}
                          data-testid={`iq-svc-qty-${s.id}`} />
                </div>
                {(cfg.frequencies || []).length > 0 && (
                  <div style={{ display: "flex", gap: 6, marginTop: 10,
                                  flexWrap: "wrap" }}>
                    {(cfg.frequencies || []).map((f) => {
                      const on = selections[s.id]?.frequency_id === f.id;
                      return (
                        <button key={f.id}
                                onClick={() => setSel(s.id, { frequency_id: f.id })}
                                style={{
                                  padding: "6px 12px", borderRadius: 999,
                                  border: `1px solid ${on ? brand : "#d4d4d8"}`,
                                  background: on ? brand : "#fff",
                                  color: on ? "#fff" : "#18181b",
                                  cursor: "pointer",
                                  fontSize: 13, fontWeight: 500,
                                }}
                                data-testid={`iq-freq-${s.id}-${f.id}`}>
                          {f.label} ×{f.multiplier}
                        </button>
                      );
                    })}
                  </div>
                )}
                {(cfg.add_ons || []).length > 0 && (
                  <div style={{ marginTop: 10, display: "flex", gap: 6,
                                  flexWrap: "wrap" }}>
                    {(cfg.add_ons || []).map((a) => {
                      const on = (selections[s.id]?.add_on_ids || []).includes(a.id);
                      return (
                        <button key={a.id}
                                onClick={() => toggleAddOn(s.id, a.id)}
                                style={{
                                  padding: "6px 10px", borderRadius: 8,
                                  border: `1px solid ${on ? brand : "#d4d4d8"}`,
                                  background: on ? `${brand}10` : "#fff",
                                  cursor: "pointer",
                                  fontSize: 12,
                                }}
                                data-testid={`iq-addon-${s.id}-${a.id}`}>
                          {on ? "✓ " : "+ "}
                          {a.name} ({fmt$(a.price_cents)})
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 24 }}>
          <h2 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>
            2 · Your contact info
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                          gap: 10 }}>
            {CF.name !== false && (
              <input placeholder="Name" value={contact.name || ""}
                      onChange={(e) => setContact({ ...contact, name: e.target.value })}
                      style={{ padding: 10, borderRadius: 8,
                                border: "1px solid #d4d4d8",
                                gridColumn: CF.email === false ? "span 2" : "auto" }}
                      data-testid="iq-contact-name" />
            )}
            {CF.email !== false && (
              <input placeholder="Email" type="email"
                      value={contact.email || ""}
                      onChange={(e) => setContact({ ...contact, email: e.target.value })}
                      style={{ padding: 10, borderRadius: 8,
                                border: "1px solid #d4d4d8" }}
                      data-testid="iq-contact-email" />
            )}
            {CF.phone !== false && (
              <input placeholder="Phone" type="tel"
                      value={contact.phone || ""}
                      onChange={(e) => setContact({ ...contact, phone: e.target.value })}
                      style={{ padding: 10, borderRadius: 8,
                                border: "1px solid #d4d4d8" }}
                      data-testid="iq-contact-phone" />
            )}
            {CF.address && (
              <input placeholder="Address" value={contact.address || ""}
                      onChange={(e) => setContact({ ...contact, address: e.target.value })}
                      style={{ padding: 10, borderRadius: 8,
                                border: "1px solid #d4d4d8",
                                gridColumn: "span 2" }} />
            )}
            {CF.notes && (
              <textarea placeholder="Notes (optional)"
                          value={contact.notes || ""}
                          rows={2}
                          onChange={(e) => setContact({ ...contact, notes: e.target.value })}
                          style={{ padding: 10, borderRadius: 8,
                                    border: "1px solid #d4d4d8",
                                    gridColumn: "span 2" }} />
            )}
          </div>
        </div>

        {/* Honeypot — hidden from real users, filled by bots */}
        <input value={hp} onChange={(e) => setHp(e.target.value)}
                autoComplete="off" tabIndex={-1}
                style={{ position: "absolute", left: -9999, opacity: 0 }}
                aria-hidden="true"
                name="_hp" />

        {preview.total > 0 && (
          <div style={{
            position: "sticky", bottom: 0, marginTop: 24,
            background: "#fff", borderTop: "1px solid #e4e4e7",
            padding: 12, display: "flex", justifyContent: "space-between",
            alignItems: "center",
          }} data-testid="iq-summary">
            <div>
              <div style={{ color: "#71717a", fontSize: 12 }}>Estimated total</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: brand }}>
                {fmt$(preview.total)}
              </div>
            </div>
            <button onClick={submit} disabled={busy}
                    style={{
                      background: brand, color: "#fff", border: "none",
                      padding: "12px 18px", borderRadius: 10,
                      fontWeight: 700, cursor: busy ? "wait" : "pointer",
                      opacity: busy ? 0.7 : 1,
                    }}
                    data-testid="iq-submit">
              {busy ? "Submitting…" : "Get my quote"}
            </button>
          </div>
        )}

        {error && (
          <div style={{ color: "#b91c1c", marginTop: 12 }}>{error}</div>
        )}
      </div>
    </div>
  );
}
