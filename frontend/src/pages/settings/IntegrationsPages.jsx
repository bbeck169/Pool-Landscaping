import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

function Card({ children, testid, className = "" }) {
  return (
    <div
      className={`rounded-2xl bg-white p-5 ${className}`}
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      {children}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Integrations status
   ═══════════════════════════════════════════════════════════════════ */
export function IntegrationsHub() {
  const [rows, setRows] = useState(null);
  const [backfillState, setBackfillState] = useState({ running: false, result: null, error: null });
  const [health, setHealth] = useState({});
  const user = (() => {
    try { return JSON.parse(localStorage.getItem("user") || "null"); }
    catch { return null; }
  })();
  const isSuperAdmin = user?.role === "super_admin";
  useEffect(() => { api.get("/settings/integrations").then(setRows).catch(() => setRows({})); }, []);
  const runBackfill = async () => {
    setBackfillState({ running: true, result: null, error: null });
    try {
      const r = await api.post("/admin/geocode-addresses");
      setBackfillState({ running: false, result: r, error: null });
    } catch (e) {
      setBackfillState({ running: false, result: null, error: e.message });
    }
  };
  const checkHealth = async (k) => {
    setHealth((h) => ({ ...h, [k]: { running: true } }));
    try {
      const r = await api.get(`/settings/integrations/health/${k}`);
      setHealth((h) => ({ ...h, [k]: { running: false, ...r } }));
    } catch (e) {
      setHealth((h) => ({ ...h, [k]: { running: false, ok: false, message: e.message } }));
    }
  };
  const INTEGRATIONS = [
    { k: "emergent_llm", label: "Emergent LLM", desc: "OpenAI · Claude · Gemini via Emergent" },
    { k: "google", label: "Google", desc: "Places autocomplete · Geocoding · Maps tiles" },
    { k: "openweb_ninja", label: "OpenWeb Ninja", desc: "Zillow sold-lead data for D2D" },
    { k: "resend", label: "Resend", desc: "Transactional email" },
    { k: "stripe", label: "Stripe", desc: "Card payments" },
    { k: "stripe_webhook", label: "Stripe Webhook", desc: "Webhook signing secret" },
    { k: "wordpress", label: "WordPress", desc: "SEO article publishing" },
    { k: "gbp", label: "Google Business Profile", desc: "OAuth Client ID" },
    { k: "ringcentral", label: "RingCentral", desc: "SMS delivery + inbound call tracking" },
  ];

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6" data-testid="integrations-hub">
      <div>
        <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>Integrations</h1>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Wired third-party services · API keys are masked for security.</p>
      </div>

      <Card testid="integrations-grid">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
          {rows && INTEGRATIONS.map((i) => {
            const s = rows[i.k] || { configured: false, preview: "", note: "" };
            const h = health[i.k];
            const chipBg = s.configured
              ? (h?.ok === false ? "#FEF3C7" : "#DCFCE7")
              : "#FEE2E2";
            const chipFg = s.configured
              ? (h?.ok === false ? "#854D0E" : "#166534")
              : "#991B1B";
            const chipLabel = !s.configured ? "Not configured"
              : h?.running ? "Checking…"
              : h?.ok === false ? "Fallback"
              : h?.ok ? "Live"
              : "Configured";
            return (
              <div key={i.k} className="rounded-xl p-3 flex items-start gap-3"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid={`integration-${i.k}`}>
                <div className="w-2.5 h-2.5 rounded-full mt-1.5" style={{ backgroundColor: s.configured ? colors.brandSecondary : colors.error }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-semibold text-sm">{i.label}</div>
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                          style={{ backgroundColor: chipBg, color: chipFg }}
                          data-testid={`integration-chip-${i.k}`}>{chipLabel}</span>
                  </div>
                  <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{i.desc}</div>
                  {s.configured
                    ? <div className="text-xs mt-1 font-mono" style={{ color: colors.onSurface }}>{s.preview}</div>
                    : <div className="text-xs mt-1" style={{ color: colors.error }}>Set the env var in /app/backend/.env</div>
                  }
                  {h && !h.running && (
                    <div className="text-[11px] mt-1" style={{ color: h.ok ? "#166534" : "#991B1B" }}>
                      {h.ok ? "✓" : "✗"} {h.message}
                    </div>
                  )}
                </div>
                {s.configured && (
                  <button onClick={() => checkHealth(i.k)} disabled={h?.running}
                          className="px-2 py-1 rounded-lg text-[10px] font-semibold self-start"
                          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
                          data-testid={`integration-check-${i.k}`}>
                    {h?.running ? "…" : "Check"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {isSuperAdmin ? (
        <Card testid="supercool-tile-card">
          <div className="flex items-start gap-3">
            <div
              className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0"
              style={{ background: brandGradientCss, color: "#fff" }}
            >
              <Sparkles size={20} />
            </div>
            <div className="flex-1">
              <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                Supercool AI (Image + Video)
              </h2>
              <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
                Model-agnostic MCP integration — one OAuth handshake unlocks
                every image + video model Supercool supports. Managed here.
              </p>
            </div>
            <Link
              to="/settings/integrations/supercool"
              className="px-3 py-2 rounded-lg text-sm font-bold text-white shrink-0"
              style={{ background: brandGradientCss }}
              data-testid="supercool-tile-open-btn"
            >
              Open
            </Link>
          </div>
        </Card>
      ) : null}

      <Card testid="geocode-backfill-card">
        <h2 className="text-lg font-bold mb-1">Geocode backfill</h2>
        <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>
          One-time backfill: fetches Google Geocoding for every customer/job that has an address but no coordinates.
          Rate-limited to ~8 req/sec. New records created via address autocomplete already carry coordinates.
        </p>
        <button
          onClick={runBackfill}
          disabled={backfillState.running}
          className="px-4 py-2 rounded-xl text-sm font-semibold text-white"
          style={{ backgroundColor: colors.brand, opacity: backfillState.running ? 0.6 : 1 }}
          data-testid="geocode-backfill-run"
        >
          {backfillState.running ? "Running…" : "Run backfill"}
        </button>
        {backfillState.result && (
          <div className="mt-3 rounded-xl p-3 text-sm" style={{ backgroundColor: "#DCFCE7", color: "#166534" }} data-testid="geocode-backfill-result">
            Processed <strong>{backfillState.result.processed}</strong> ·
            Updated <strong>{backfillState.result.updated}</strong> ·
            Skipped <strong>{backfillState.result.skipped}</strong>
            {backfillState.result.error_count > 0 && ` · ${backfillState.result.error_count} errors`}
          </div>
        )}
        {backfillState.error && (
          <div className="mt-3 rounded-xl p-3 text-sm" style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
            {backfillState.error}
          </div>
        )}
      </Card>

      <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
        <Link to="/settings/maps" className="font-semibold" style={{ color: colors.brand }}>Map provider settings →</Link>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Map settings — provider toggle
   ═══════════════════════════════════════════════════════════════════ */
export function MapSettings() {
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  useEffect(() => { api.get("/settings/maps").then(setSettings); }, []);
  const update = async (patch) => {
    setSaving(true);
    try {
      const r = await api.put("/settings/maps", patch);
      setSettings(r);
      setToast("Saved");
      setTimeout(() => setToast(""), 1800);
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };
  if (!settings) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>;

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto space-y-4" data-testid="map-settings-page">
      <h1 className="text-2xl font-bold">Map & autocomplete</h1>
      <Card>
        <div className="text-sm font-semibold mb-2">Map provider</div>
        <div className="space-y-2">
          {[
            { k: "openstreetmap", label: "OpenStreetMap", desc: "Free · No API key needed · Default" },
            { k: "google", label: "Google Maps", desc: settings.google_configured ? "Live · Requires GOOGLE_API_KEY (configured)" : "Requires GOOGLE_API_KEY (not configured)" },
          ].map((opt) => (
            <label key={opt.k} className="flex items-start gap-3 p-3 rounded-xl cursor-pointer"
                   style={{ border: `1px solid ${settings.map_provider === opt.k ? colors.brand : colors.border}` }}
                   data-testid={`map-provider-${opt.k}`}>
              <input type="radio" checked={settings.map_provider === opt.k}
                     onChange={() => update({ map_provider: opt.k })}
                     disabled={saving || (opt.k === "google" && !settings.google_configured)} />
              <div>
                <div className="font-semibold text-sm">{opt.label}</div>
                <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{opt.desc}</div>
              </div>
            </label>
          ))}
        </div>
      </Card>

      <Card>
        <label className="flex items-center gap-3">
          <input type="checkbox" checked={!!settings.autocomplete_enabled}
                 onChange={(e) => update({ autocomplete_enabled: e.target.checked })}
                 disabled={saving}
                 data-testid="autocomplete-toggle" />
          <div>
            <div className="font-semibold text-sm">Address autocomplete</div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
              Google Places suggestions on customer + job address fields. Structured components + lat/lng are stored on save.
            </div>
          </div>
        </label>
      </Card>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg" style={{ backgroundColor: colors.onSurface }} data-testid="map-settings-toast">
          {toast}
        </div>
      )}
    </div>
  );
}
