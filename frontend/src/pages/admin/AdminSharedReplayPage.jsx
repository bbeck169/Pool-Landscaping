// Phase 2 · Feb-2026 — Public read-only Route Replay page.
//
// Route: `/replay/:shareId` — unauthenticated. Hits
// `GET /api/gps/replay/share/{shareId}` and renders a stripped-down
// read-only view (polyline + stops + geofence events markers, no
// admin controls / no assign-job / no phone / no edit buttons).
//
// The Google Maps component here is intentionally lighter than the
// admin RouteReplayPanel — no @vis.gl/react-google-maps dep at the
// public route level (fewer transitive React contexts) — we render a
// simple map iframe via Google Maps Embed / a static polyline preview
// when the API key isn't public-safe. To keep scope tight this MVP
// public page shows: header, stops list with reverse-geocoded
// addresses, and a linear timeline. A follow-up can lift the animated
// Google Maps panel into the shared component tree.
import React from "react";
import { useParams } from "react-router-dom";
import { MapPin, Clock, Route as RouteIcon, ShieldAlert, Info } from "lucide-react";

import { api } from "@/api";

function _fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}
function _fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined,
      { year: "numeric", month: "short", day: "numeric" });
  } catch { return iso; }
}

function ErrorCard({ icon: Icon, title, body, testId }) {
  return (
    <div
      data-testid={testId}
      style={{
        maxWidth: 480, margin: "80px auto", padding: 32,
        background: "#FFFFFF", border: "1px solid #E2E8F0",
        borderRadius: 14, textAlign: "center",
        boxShadow: "0 4px 12px rgba(15,23,42,0.06)",
      }}
    >
      <Icon size={36} color="#DC2626" style={{ marginBottom: 12 }} />
      <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6, color: "#0F172A" }}>
        {title}
      </div>
      <div style={{ fontSize: 14, color: "#64748B" }}>{body}</div>
    </div>
  );
}

export default function AdminSharedReplayPage() {
  const { shareId } = useParams();
  const [state, setState] = React.useState({ loading: true, payload: null,
                                                error: null, status: 0 });

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await api.get(`/gps/replay/share/${encodeURIComponent(shareId)}`);
        if (cancelled) return;
        setState({ loading: false, payload, error: null, status: 200 });
      } catch (e) {
        if (cancelled) return;
        // `api` throws ApiHttpError with a numeric .status attribute.
        const status = e?.status || 0;
        const detail = e?.body?.detail || e?.message || `HTTP ${status || "unknown"}`;
        setState({ loading: false, payload: null, error: detail, status });
      }
    })();
    return () => { cancelled = true; };
  }, [shareId]);

  if (state.loading) {
    return (
      <div data-testid="public-replay-loading"
            style={{ maxWidth: 480, margin: "120px auto", textAlign: "center", color: "#64748B" }}>
        Loading replay…
      </div>
    );
  }
  if (state.status === 410) {
    return <ErrorCard testId="public-replay-gone"
                       icon={ShieldAlert}
                       title="This link has expired or been revoked."
                       body="Contact the sender to request a new share link." />;
  }
  if (state.status === 404) {
    return <ErrorCard testId="public-replay-notfound"
                       icon={Info}
                       title="Link not found."
                       body="Please double-check the URL and try again." />;
  }
  if (state.status === 403) {
    return <ErrorCard testId="public-replay-forbidden"
                       icon={ShieldAlert}
                       title="Admin access required."
                       body="Route replay share links are restricted to Admin and Super Admin users only." />;
  }
  if (state.status === 429) {
    return <ErrorCard testId="public-replay-throttled"
                       icon={Info}
                       title="Too many refreshes."
                       body="Please try again in a moment." />;
  }
  if (state.error) {
    return <ErrorCard testId="public-replay-error"
                       icon={Info} title="Something went wrong."
                       body={state.error} />;
  }

  const d = state.payload || {};
  const stops = d.stops || [];
  const fences = d.geofence_events || [];

  return (
    <div data-testid="public-replay-page"
          style={{ minHeight: "100vh", background: "#F8FAFC", color: "#0F172A" }}>
      {/* Header */}
      <div style={{
        background: "#FFFFFF", borderBottom: "1px solid #E2E8F0",
        padding: "16px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div>
          <div style={{ fontSize: 12, color: "#64748B", letterSpacing: 0.5, textTransform: "uppercase" }}>
            Route replay
          </div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>
            {d.user_name || "Technician"}
          </div>
          <div style={{ fontSize: 13, color: "#64748B" }}>
            {_fmtDate(d.replay_date)}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div data-testid="public-replay-view-count"
                style={{ fontSize: 12, color: "#64748B" }}>
            View {d.view_count ?? "—"}
          </div>
          <div style={{ fontSize: 11, color: "#94A3B8" }}>
            Read-only · Expires {_fmtDate(d.expires_at)}
          </div>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12, padding: 20, maxWidth: 960, margin: "0 auto",
      }}>
        <div style={{ background: "#FFFFFF", border: "1px solid #E2E8F0",
                       borderRadius: 12, padding: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#64748B", fontSize: 12 }}>
            <MapPin size={14} /> Stops
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{stops.length}</div>
        </div>
        <div style={{ background: "#FFFFFF", border: "1px solid #E2E8F0",
                       borderRadius: 12, padding: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#64748B", fontSize: 12 }}>
            <RouteIcon size={14} /> Pings
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>
            {d.pings_total ?? (d.pings || []).length}
          </div>
        </div>
        <div style={{ background: "#FFFFFF", border: "1px solid #E2E8F0",
                       borderRadius: 12, padding: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#64748B", fontSize: 12 }}>
            <Clock size={14} /> Duration
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>
            {Math.round((d.playback_duration_s || 0) / 60)} min
          </div>
        </div>
      </div>

      {/* Stops list */}
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 20px 24px" }}>
        <div style={{
          background: "#FFFFFF", border: "1px solid #E2E8F0",
          borderRadius: 12, overflow: "hidden",
        }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #E2E8F0",
                          fontSize: 14, fontWeight: 600 }}>
            Stops
          </div>
          {stops.length === 0 && (
            <div data-testid="public-replay-no-stops"
                  style={{ padding: 24, textAlign: "center", color: "#64748B", fontSize: 13 }}>
              No stops recorded on this day.
            </div>
          )}
          {stops.map((s, i) => (
            <div key={s.id || i}
                  data-testid={`public-replay-stop-${i}`}
                  style={{ padding: "12px 16px",
                            borderTop: i === 0 ? "none" : "1px solid #E2E8F0",
                            display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div style={{ minWidth: 32, height: 32, borderRadius: 16,
                              background: "#DBEAFE", color: "#1D4ED8",
                              display: "flex", alignItems: "center",
                              justifyContent: "center", fontWeight: 700, fontSize: 13 }}>
                {i + 1}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>
                  {(s.address && (s.address.formatted || s.address.display)) ||
                    (s.attributed_customer_name) ||
                    `${(s.center_lat ?? 0).toFixed(4)}, ${(s.center_lon ?? 0).toFixed(4)}`}
                </div>
                <div style={{ fontSize: 12, color: "#64748B", marginTop: 2 }}>
                  {_fmtTime(s.started_at)} – {_fmtTime(s.ended_at)}
                  {s.duration_s ? ` · ${Math.round(s.duration_s/60)} min` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Geofence timeline */}
      {fences.length > 0 && (
        <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 20px 24px" }}>
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E8F0",
                          borderRadius: 12, padding: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
              Site entries &amp; exits
            </div>
            {fences.map((f, i) => (
              <div key={i}
                    data-testid={`public-replay-fence-${i}`}
                    style={{ fontSize: 13, padding: "6px 0",
                              display: "flex", justifyContent: "space-between",
                              borderTop: i === 0 ? "none" : "1px solid #E2E8F0" }}>
                <span>
                  <b>{f.event === "entry" ? "Entered" : "Exited"}</b> {f.geofence_name || "site"}
                </span>
                <span style={{ color: "#64748B" }}>{_fmtTime(f.ts)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ textAlign: "center", padding: 24,
                      fontSize: 12, color: "#94A3B8" }}
            data-testid="public-replay-footer">
        {d.tenant_name || "Route replay"} · Read-only share · Expires {_fmtDate(d.expires_at)}
      </div>
    </div>
  );
}
