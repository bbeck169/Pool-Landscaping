/**
 * Phase AIM0 · Feb-2026 — AI Measurement Tool (POC).
 *
 * Admin-only satellite → GPT-4o + Claude vision → pool/deck/yard
 * polygon overlays with pixel-shoelace area readouts in sq ft / yd.
 *
 * Guardrails
 * ----------
 *  • Role guard: admin / super_admin / owner. Techs redirect home.
 *  • No persistence. History list is in-memory only for the tab.
 *  • Custom `<canvas>` overlay on top of the raw `<img>` — no
 *    third-party map SDK.
 *  • Colour + geometry palette is locked (spec):
 *      pool  → rgba(37, 99, 235, 0.35) / #2563EB
 *      deck  → rgba(217, 119, 6, 0.35) / #D97706
 *      yard  → rgba(22, 163, 74, 0.35) / #16A34A
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import AddressAutocomplete from "@/components/AddressAutocomplete";

const FEATURE_STYLE = Object.freeze({
  pool: { fill: "rgba(37, 99, 235, 0.35)", stroke: "#2563EB", label: "Pool" },
  deck: { fill: "rgba(217, 119, 6, 0.35)", stroke: "#D97706", label: "Deck" },
  yard: { fill: "rgba(22, 163, 74, 0.35)", stroke: "#16A34A", label: "Yard" },
});
const FEATURE_ORDER = ["pool", "deck", "yard"];
const ZOOM_OPTIONS = [18, 19, 20, 21];

export function AiMeasurePageRoleGuard({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "owner";
  if (!user || !allowed) {
    return (
      <div className="p-8" data-testid="ai-measure-forbidden">
        <div className="max-w-lg rounded-2xl border p-6"
              style={{ borderColor: colors.border, background: colors.surface }}>
          <div className="text-sm font-semibold mb-1"
                style={{ color: colors.onSurface }}>Restricted</div>
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            AI Measure is only available to admin, super-admin, and owner accounts.
          </div>
          <div className="mt-4">
            <Navigate to="/" replace />
          </div>
        </div>
      </div>
    );
  }
  return children;
}

function ProviderCanvas({
  provider, imageDataUrl, features, imageSize,
}) {
  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const drawn = useRef(false);

  useEffect(() => {
    if (!imageDataUrl || !canvasRef.current) return;
    drawn.current = false;
  }, [imageDataUrl, features]);

  const handleImgLoad = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;
    const w = imageSize?.[0] || img.naturalWidth || 640;
    const h = imageSize?.[1] || img.naturalHeight || 640;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    for (const feat of features || []) {
      const style = FEATURE_STYLE[feat.type];
      if (!style || !Array.isArray(feat.polygon) || feat.polygon.length < 3) continue;
      ctx.beginPath();
      const [x0, y0] = feat.polygon[0];
      ctx.moveTo(x0, y0);
      for (let i = 1; i < feat.polygon.length; i++) {
        const [x, y] = feat.polygon[i];
        ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = style.fill;
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.strokeStyle = style.stroke;
      ctx.stroke();
    }
    drawn.current = true;
  }, [features, imageSize]);

  return (
    <div className="rounded-2xl overflow-hidden"
         style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
         data-testid={`ai-measure-canvas-${provider}`}>
      <div className="flex items-center justify-between px-4 py-2"
           style={{ background: colors.surfaceTertiary }}>
        <div className="text-sm font-semibold uppercase tracking-wider"
             style={{ color: colors.onSurface, letterSpacing: "0.08em" }}>
          {provider === "openai_gpt-4o" ? "GPT-4o" : "Claude"}
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {(features || []).length} feature{(features || []).length === 1 ? "" : "s"}
        </div>
      </div>
      <div className="relative"
           style={{ width: "100%", aspectRatio: "1 / 1", background: "#000" }}>
        {imageDataUrl ? (
          <>
            <img
              ref={imgRef}
              src={imageDataUrl}
              alt={`Satellite tile (${provider})`}
              onLoad={handleImgLoad}
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain" }}
            />
            <canvas
              ref={canvasRef}
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm"
               style={{ color: "rgba(255,255,255,0.5)" }}>
            No image yet — run a detection to preview.
          </div>
        )}
      </div>
    </div>
  );
}

function FeatureReadoutCard({
  provider, feature, onThumb,
}) {
  const style = FEATURE_STYLE[feature.type] || FEATURE_STYLE.pool;
  const confPct = feature.confidence != null ? Math.round(feature.confidence * 100) : null;
  return (
    <div className="rounded-xl p-3 mb-3"
         style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={`ai-measure-result-${provider}-${feature.type}`}>
      <div className="flex items-center gap-2 mb-2">
        <div style={{ width: 10, height: 10, borderRadius: 2, background: style.stroke }} />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{style.label}</div>
      </div>
      <div className="text-2xl font-semibold leading-tight" style={{ color: colors.onSurface }}>
        {feature.area_sqft?.toLocaleString(undefined, { maximumFractionDigits: 1 }) || "—"} <span className="text-sm font-medium" style={{ color: colors.muted }}>sq ft</span>
      </div>
      <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
        {feature.area_sqyd?.toLocaleString(undefined, { maximumFractionDigits: 2 }) || "—"} sq yd
      </div>
      {confPct != null && (
        <div className="mt-2">
          <div className="text-[10px] uppercase tracking-wider mb-1"
               style={{ color: colors.muted, letterSpacing: "0.08em" }}>
            Confidence
          </div>
          <div className="h-1.5 rounded-full overflow-hidden"
               style={{ background: colors.surfaceTertiary }}>
            <div style={{
              width: `${confPct}%`,
              height: "100%",
              background: style.stroke,
            }} />
          </div>
          <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>{confPct}%</div>
        </div>
      )}
      <div className="mt-3 flex items-center gap-2">
        <button type="button"
                className="text-xs px-2.5 py-1 rounded-full border"
                style={{ borderColor: colors.border, color: colors.onSurfaceSecondary, background: colors.surface }}
                onClick={() => onThumb(feature, "up")}
                data-testid={`ai-measure-feedback-up-${provider}-${feature.type}`}>
          👍 Good
        </button>
        <button type="button"
                className="text-xs px-2.5 py-1 rounded-full border"
                style={{ borderColor: colors.border, color: colors.onSurfaceSecondary, background: colors.surface }}
                onClick={() => onThumb(feature, "down")}
                data-testid={`ai-measure-feedback-down-${provider}-${feature.type}`}>
          👎 Bad
        </button>
      </div>
    </div>
  );
}

export default function AiMeasurePage() {
  return (
    <AiMeasurePageRoleGuard>
      <AiMeasurePageInner />
    </AiMeasurePageRoleGuard>
  );
}

function AiMeasurePageInner() {
  const [address, setAddress] = useState("");
  const [coords, setCoords] = useState({ lat: null, lng: null });
  const [zoom, setZoom] = useState(20);
  const [features, setFeatures] = useState({ pool: true, deck: true, yard: true });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);      // in-memory only
  const [feedback, setFeedback] = useState([]);    // in-memory only

  const enabledFeatures = useMemo(
    () => FEATURE_ORDER.filter((k) => features[k]),
    [features],
  );

  const onSelectAddress = useCallback((parsed) => {
    setAddress(parsed?.formatted || parsed?.address || address);
    setCoords({ lat: parsed?.lat ?? null, lng: parsed?.lng ?? null });
  }, [address]);

  const run = useCallback(async () => {
    if (busy) return;
    if (!address && (coords.lat == null || coords.lng == null)) {
      setError("Enter an address or coordinates first.");
      return;
    }
    if (enabledFeatures.length === 0) {
      setError("Select at least one feature type.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = {
        zoom,
        feature_types: enabledFeatures,
      };
      if (coords.lat != null && coords.lng != null) {
        body.lat = coords.lat;
        body.lng = coords.lng;
      } else {
        body.address = address;
      }
      const res = await api.post("/tools/ai-measure/preview", body, 90_000);
      setResult(res);
      setHistory((h) => [
        {
          id: `run-${Date.now()}`,
          at: new Date().toISOString(),
          address: res.address_resolved,
          zoom: res.zoom,
          features: enabledFeatures,
        },
        ...h,
      ].slice(0, 12));
    } catch (e) {
      const msg = e?.data?.detail || e?.message || "Detection failed";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setBusy(false);
    }
  }, [address, coords, zoom, enabledFeatures, busy]);

  const onThumb = useCallback((feature, direction) => {
    // eslint-disable-next-line no-console
    console.info("[ai-measure] feedback", { direction, feature });
    setFeedback((f) => [
      { at: Date.now(), direction, type: feature.type, area_sqft: feature.area_sqft },
      ...f,
    ]);
  }, []);

  const providers = result?.providers || [];
  const imageDataUrl = result?.satellite_image_data_url || "";
  const imageSize = result?.image_size;

  return (
    <div className="min-h-screen" style={{ background: colors.surfaceSecondary }}
         data-testid="ai-measure-page">
      {/* Header */}
      <div className="px-6 pt-6 pb-3"
           style={{ background: colors.surface, borderBottom: `1px solid ${colors.border}` }}>
        <div className="text-[11px] uppercase tracking-widest mb-1"
             style={{ color: colors.muted, letterSpacing: "0.14em" }}>
          Admin tools · POC
        </div>
        <div className="text-2xl font-semibold" style={{ color: colors.onSurface }}>
          AI Measure
        </div>
        <div className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
          Overhead satellite → dual-provider polygon detection · nothing is saved
        </div>
      </div>

      <div className="flex flex-col lg:flex-row gap-4 p-4">
        {/* LEFT — inputs + history */}
        <aside className="lg:w-[300px] flex-shrink-0 space-y-4">
          <div className="rounded-2xl p-4"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <label className="text-xs font-medium uppercase tracking-wider block mb-1"
                    style={{ color: colors.muted, letterSpacing: "0.08em" }}>
              Address
            </label>
            <AddressAutocomplete
              value={address}
              onChange={setAddress}
              onSelect={onSelectAddress}
              testid="ai-measure-address"
              placeholder="Search a property…"
            />
            {(coords.lat != null && coords.lng != null) ? (
              <div className="text-xs mt-2" style={{ color: colors.muted }}>
                {coords.lat.toFixed(5)}, {coords.lng.toFixed(5)}
              </div>
            ) : null}

            <div className="mt-4">
              <label className="text-xs font-medium uppercase tracking-wider block mb-1"
                      style={{ color: colors.muted, letterSpacing: "0.08em" }}>
                Zoom
              </label>
              <select
                value={zoom}
                onChange={(e) => setZoom(parseInt(e.target.value, 10))}
                className="w-full rounded-lg px-3 py-2 text-sm"
                style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="ai-measure-zoom-select">
                {ZOOM_OPTIONS.map((z) => (
                  <option key={z} value={z}>{z}{z === 20 ? " (default)" : ""}</option>
                ))}
              </select>
            </div>

            <div className="mt-4">
              <div className="text-xs font-medium uppercase tracking-wider mb-2"
                   style={{ color: colors.muted, letterSpacing: "0.08em" }}>
                Features
              </div>
              {FEATURE_ORDER.map((k) => (
                <label key={k} className="flex items-center gap-2 text-sm py-1"
                        style={{ color: colors.onSurface }}>
                  <input
                    type="checkbox"
                    checked={!!features[k]}
                    onChange={(e) => setFeatures((f) => ({ ...f, [k]: e.target.checked }))}
                    data-testid={`ai-measure-feature-${k}`}
                  />
                  <span className="inline-block w-2 h-2 rounded"
                         style={{ background: FEATURE_STYLE[k].stroke }} />
                  {FEATURE_STYLE[k].label}
                </label>
              ))}
            </div>

            <button type="button"
                    onClick={run}
                    disabled={busy}
                    className="w-full mt-4 py-2.5 rounded-xl text-sm font-semibold"
                    style={{
                      background: busy ? colors.surfaceTertiary : colors.onSurface,
                      color: busy ? colors.muted : "#FFFFFF",
                      cursor: busy ? "wait" : "pointer",
                    }}
                    data-testid="ai-measure-run">
              {busy ? "Detecting…" : "Run detection"}
            </button>
            {error ? (
              <div className="text-xs mt-2" style={{ color: "#B91C1C" }}
                   data-testid="ai-measure-error">
                {error}
              </div>
            ) : null}
          </div>

          <div className="rounded-2xl p-4"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid="ai-measure-history">
            <div className="text-xs font-medium uppercase tracking-wider mb-2"
                 style={{ color: colors.muted, letterSpacing: "0.08em" }}>
              History (this tab)
            </div>
            {history.length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}>No runs yet.</div>
            ) : history.map((h) => (
              <div key={h.id} className="py-1.5 text-xs" style={{ color: colors.onSurface }}>
                <div className="truncate" title={h.address}>{h.address}</div>
                <div style={{ color: colors.muted }}>
                  z{h.zoom} · {h.features.join(", ")}
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* CENTER — canvases */}
        <section className="flex-1 min-w-0 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ProviderCanvas provider="openai_gpt-4o"
              imageDataUrl={imageDataUrl}
              features={providers.find((p) => p.provider === "openai_gpt-4o")?.features || []}
              imageSize={imageSize} />
            <ProviderCanvas provider="anthropic_claude"
              imageDataUrl={imageDataUrl}
              features={providers.find((p) => p.provider === "anthropic_claude")?.features || []}
              imageSize={imageSize} />
          </div>
          {result ? (
            <div className="rounded-xl px-4 py-3 text-xs"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurfaceSecondary }}
                 data-testid="ai-measure-meta">
              <div><span style={{ color: colors.muted }}>Address:</span> {result.address_resolved}</div>
              <div><span style={{ color: colors.muted }}>Coords:</span> {result.lat?.toFixed?.(6)}, {result.lng?.toFixed?.(6)}</div>
              <div><span style={{ color: colors.muted }}>Zoom:</span> {result.zoom} · <span style={{ color: colors.muted }}>MPP:</span> {result.mpp_effective?.toFixed?.(4)} m/px</div>
            </div>
          ) : null}
        </section>

        {/* RIGHT — numeric readouts */}
        <aside className="lg:w-[300px] flex-shrink-0 space-y-4"
               data-testid="ai-measure-readouts">
          {providers.length === 0 ? (
            <div className="rounded-2xl p-4 text-sm"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
              Numeric readouts appear here once a detection finishes.
            </div>
          ) : providers.map((p) => (
            <div key={p.provider} className="rounded-2xl p-4"
                 style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                 data-testid={`ai-measure-readout-${p.provider}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {p.provider === "openai_gpt-4o" ? "GPT-4o" : "Claude"}
                </div>
                <div className="text-[11px]" style={{ color: colors.muted }}>
                  {p.latency_ms}ms
                </div>
              </div>
              {p.error ? (
                <div className="text-xs" style={{ color: "#B91C1C" }}>
                  Error: {p.error}
                </div>
              ) : null}
              {p.features.length === 0 ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  {p.error ? "" : "No features detected."}
                </div>
              ) : p.features.map((feat, idx) => (
                <FeatureReadoutCard key={`${feat.type}-${idx}`}
                  provider={p.provider}
                  feature={feat}
                  onThumb={onThumb}
                />
              ))}
            </div>
          ))}
          {feedback.length > 0 ? (
            <div className="rounded-2xl p-4"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
                 data-testid="ai-measure-feedback-log">
              <div className="text-xs uppercase tracking-wider mb-2"
                   style={{ color: colors.muted, letterSpacing: "0.08em" }}>
                Feedback (this tab)
              </div>
              {feedback.slice(0, 6).map((f, i) => (
                <div key={i} className="text-xs py-0.5"
                     style={{ color: colors.onSurfaceSecondary }}>
                  {f.direction === "up" ? "👍" : "👎"} {f.type} · {f.area_sqft} sq ft
                </div>
              ))}
            </div>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
