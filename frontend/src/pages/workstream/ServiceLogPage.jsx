/**
 * Phase 5A.2 · Service Log — Workstream job detail view.
 *
 * Route: /workstream/:id (admin only, gated at App.js AND at the API layer).
 *
 * Three-column desktop layout matching the reference screenshot:
 *
 *   ┌─────────────────────┬─────────────────────┬─────────────────────┐
 *   │  Log Details        │  Water Test Results │  Service Images     │
 *   │  Customer → Address │  (pool only)        │  carousel           │
 *   │  Service date/time  │  Chemical Used +    │  prev/next chevrons │
 *   │  Employee           │  Chemical Cost pill │  dot pagination     │
 *   │  Checklist ✓        │                     │                     │
 *   │  Previous Service   │  For landscape jobs │                     │
 *   │  Email Door Hanger  │  → Service Notes    │                     │
 *   └─────────────────────┴─────────────────────┴─────────────────────┘
 *
 * Data source: GET /api/jobs/{id}/service-log — a single aggregated call.
 * On mobile / narrow viewports the columns stack vertically.
 *
 * Media carousel: unified images + videos, keyboard-navigable with
 * Left/Right arrows once focused, dot pagination bottom-center.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight, CalendarClock, ChevronLeft, ChevronRight,
  Check, Circle, Play, Loader2, Mail, Droplet, TestTube2,
  AlertTriangle,
} from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { colors } from "@/theme";
import { toast } from "sonner";
import ClickToCallButton from "@/components/telephony/ClickToCallButton";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const BLUE = "#2563EB";

function formatDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const date = d.toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric",
    });
    const time = d.toLocaleTimeString("en-US", {
      hour: "numeric", minute: "2-digit",
    });
    return `${date} --> ${time.toLowerCase()}`;
  } catch { return String(iso); }
}

function Avatar({ name, size = 32 }) {
  const initials = (name || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div
      style={{
        width: size, height: size, borderRadius: "50%",
        background: colors.brandTertiary || "#E0F2FE",
        color: colors.brand || BLUE,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        fontSize: size / 2.4, fontWeight: 600, flexShrink: 0,
      }}
    >
      {initials}
    </div>
  );
}

function Card({ children, testid, style }) {
  return (
    <div
      data-testid={testid}
      style={{
        background: "white",
        border: `1px solid ${colors.border || "#E2E8F0"}`,
        borderRadius: 14,
        padding: 20,
        boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function CardTitle({ children, testid }) {
  return (
    <div
      data-testid={testid}
      style={{
        fontSize: 13, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.06em", color: colors.muted || "#64748B",
        marginBottom: 12,
      }}
    >
      {children}
    </div>
  );
}

function Row({ children, style }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, ...style }}>
      {children}
    </div>
  );
}

// ── Media carousel ──────────────────────────────────────────────────
function MediaCarousel({ items = [] }) {
  const [idx, setIdx] = useState(0);
  const containerRef = useRef(null);
  const token = localStorage.getItem(TOKEN_KEY) || "";

  const total = items.length;
  const cur = items[idx];

  const next = useCallback(() => {
    if (total <= 1) return;
    setIdx((i) => (i + 1) % total);
  }, [total]);
  const prev = useCallback(() => {
    if (total <= 1) return;
    setIdx((i) => (i - 1 + total) % total);
  }, [total]);

  useEffect(() => {
    const onKey = (e) => {
      if (document.activeElement !== containerRef.current) return;
      if (e.key === "ArrowRight") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev]);

  if (total === 0) {
    return (
      <Card testid="service-log-media-empty" style={{ minHeight: 320 }}>
        <CardTitle>Service Images</CardTitle>
        <div style={{
          height: 260, display: "flex", alignItems: "center", justifyContent: "center",
          borderRadius: 10, background: colors.surfaceSecondary || "#F1F5F9",
          color: colors.muted, fontSize: 13,
        }} data-testid="service-log-media-empty-text">
          No service images uploaded
        </div>
      </Card>
    );
  }

  const url = cur?.url ? (cur.url.startsWith("http") ? cur.url : `${BACKEND}${cur.url}`) : "";
  const isVideo = cur?.kind === "video";

  return (
    <Card testid="service-log-media">
      <CardTitle>Service Images</CardTitle>
      <div
        ref={containerRef}
        tabIndex={0}
        role="region"
        aria-label="Service images carousel"
        style={{
          position: "relative", borderRadius: 12, overflow: "hidden",
          background: "#0F172A", outline: "none",
          aspectRatio: "16 / 10",
        }}
        data-testid="service-log-media-viewport"
      >
        {isVideo ? (
          <video
            key={cur?.id}
            src={url + (token ? `?token=${encodeURIComponent(token)}` : "")}
            controls
            autoPlay
            muted
            playsInline
            style={{ width: "100%", height: "100%", objectFit: "contain", background: "#000" }}
            data-testid="service-log-media-video"
          />
        ) : (
          <img
            src={url + (token ? `?token=${encodeURIComponent(token)}` : "")}
            alt=""
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
            data-testid="service-log-media-image"
          />
        )}
        {total > 1 ? (
          <>
            <button
              type="button"
              onClick={prev}
              aria-label="Previous"
              data-testid="service-log-media-prev"
              style={{
                position: "absolute", top: "50%", left: 8,
                transform: "translateY(-50%)",
                background: "rgba(15,23,42,0.55)", color: "white",
                border: "none", borderRadius: "50%", width: 32, height: 32,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
              }}
            >
              <ChevronLeft size={18} />
            </button>
            <button
              type="button"
              onClick={next}
              aria-label="Next"
              data-testid="service-log-media-next"
              style={{
                position: "absolute", top: "50%", right: 8,
                transform: "translateY(-50%)",
                background: "rgba(15,23,42,0.55)", color: "white",
                border: "none", borderRadius: "50%", width: 32, height: 32,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
              }}
            >
              <ChevronRight size={18} />
            </button>
          </>
        ) : null}
      </div>
      {total > 1 ? (
        <div
          style={{ display: "flex", justifyContent: "center", gap: 6, marginTop: 12 }}
          data-testid="service-log-media-dots"
        >
          {items.map((it, i) => {
            const active = i === idx;
            const isVid = it.kind === "video";
            return (
              <button
                key={it.id || i}
                onClick={() => setIdx(i)}
                aria-label={`Go to item ${i + 1}`}
                data-testid={`service-log-media-dot-${i}`}
                style={{
                  width: active ? 22 : 8, height: 8, borderRadius: 8,
                  border: "none", cursor: "pointer",
                  background: active ? BLUE : (colors.border || "#CBD5E1"),
                  position: "relative", padding: 0,
                  transition: "width 150ms ease",
                }}
              >
                {isVid ? (
                  <Play
                    size={7}
                    style={{
                      position: "absolute", top: "50%", left: "50%",
                      transform: "translate(-50%, -50%)",
                      color: active ? "white" : "#0F172A",
                    }}
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </Card>
  );
}

// ── Main page ──────────────────────────────────────────────────────
export default function ServiceLogPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, data: null, err: "" });
  const [emailing, setEmailing] = useState(false);

  useEffect(() => {
    let cancel = false;
    setState({ loading: true, data: null, err: "" });
    api.get(`/jobs/${id}/service-log`)
      .then((d) => { if (!cancel) setState({ loading: false, data: d, err: "" }); })
      .catch((e) => {
        if (cancel) return;
        setState({ loading: false, data: null, err: e?.message || "Failed to load service log." });
      });
    return () => { cancel = true; };
  }, [id]);

  const emailDoorHanger = async () => {
    setEmailing(true);
    try {
      const res = await api.post(`/jobs/${id}/email-door-hanger`);
      if (res?.ok) {
        toast.success(`Door hanger emailed to ${res.recipient}`);
      } else if (res?.reason === "cooldown") {
        toast(`Please wait ${res.cooldown_seconds || 60}s before re-sending.`);
      }
    } catch (e) {
      // 429 is thrown as an error by the api client; extract cleanly.
      if ((e?.status || 0) === 429) {
        toast("Please wait 60s before re-sending.");
      } else {
        toast.error(e?.message || "Could not send door hanger.");
      }
    } finally {
      setEmailing(false);
    }
  };

  if (state.loading) {
    return (
      <div style={{ padding: 32, display: "flex", alignItems: "center", gap: 8, color: colors.muted }} data-testid="service-log-loading">
        <Loader2 className="animate-spin" size={18} /> Loading service log…
      </div>
    );
  }
  if (state.err || !state.data) {
    return (
      <div style={{ padding: 32 }} data-testid="service-log-error">
        <div style={{
          padding: 16, borderRadius: 10,
          background: "#FEE2E2", color: "#991B1B",
          display: "flex", gap: 8, alignItems: "center",
        }}>
          <AlertTriangle size={16} /> {state.err || "Could not load."}
        </div>
      </div>
    );
  }

  const d = state.data;
  const isPool = d.service_line === "pool";

  return (
    <div style={{
      padding: "20px 24px",
      background: colors.surfaceSecondary || "#F8FAFC",
      minHeight: "100%",
    }} data-testid="service-log-page">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 20 }}>
        <button
          type="button"
          onClick={() => navigate(-1)}
          style={{
            fontSize: 13, color: colors.muted,
            background: "transparent", border: "none", cursor: "pointer",
            padding: 0,
          }}
          data-testid="service-log-back"
        >
          ← Back
        </button>
        <div style={{ fontSize: 22, fontWeight: 700, color: colors.onSurface }}>
          Service Log
        </div>
        <div style={{ fontSize: 12, color: colors.muted, marginLeft: "auto" }}>
          {d.service_line?.toUpperCase()}
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr)",
        gap: 20,
      }} data-testid="service-log-columns">
        {/* LEFT — Log Details */}
        <div style={{ minWidth: 0 }}>
          <Card testid="service-log-details">
            <CardTitle>Log Details</CardTitle>
            <Row style={{ marginBottom: 14 }}>
              <Avatar name={d.log_details?.customer_name} />
              <div style={{
                display: "flex", alignItems: "center", gap: 6,
                fontSize: 14, minWidth: 0, flex: 1,
              }} data-testid="service-log-customer-row">
                <b style={{ color: colors.onSurface, whiteSpace: "nowrap" }}>
                  {d.log_details?.customer_name || "—"}
                </b>
                <ArrowRight size={14} color={colors.muted} style={{ flexShrink: 0 }} />
                <span style={{
                  color: colors.muted, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                }} data-testid="service-log-address">
                  {d.log_details?.property_address || "—"}
                </span>
              </div>
            </Row>

            {/* Phase 6B · Feb 2026 — one-click call to service log's customer. */}
            {d.log_details?.customer_phone ? (
              <Row style={{ marginBottom: 14 }} data-testid="service-log-click-to-call-wrapper">
                <ClickToCallButton
                  phoneNumber={d.log_details.customer_phone}
                  entityKind="workstream"
                  entityId={d.log_details?.id || id}
                  label="Call customer"
                  size="sm"
                  testIdPrefix="service-log-click-to-call"
                />
              </Row>
            ) : null}

            <Row style={{ marginBottom: 14 }}>
              <CalendarClock size={20} color={BLUE} />
              <div style={{ fontSize: 13, lineHeight: 1.35 }}>
                <div style={{ fontWeight: 600, color: colors.onSurface }} data-testid="service-log-service-at">
                  {formatDateTime(d.log_details?.service_at)}
                </div>
                {d.log_details?.time_spent_minutes != null ? (
                  <div style={{ color: colors.muted, fontSize: 12 }} data-testid="service-log-time-spent">
                    Time spent: {d.log_details.time_spent_minutes} min.
                  </div>
                ) : null}
              </div>
            </Row>

            <Row style={{ marginBottom: 18 }}>
              <Avatar name={d.log_details?.employee_name} />
              <div style={{ fontSize: 14, fontWeight: 600, color: colors.onSurface }} data-testid="service-log-employee">
                {d.log_details?.employee_name || "Unassigned"}
              </div>
            </Row>

            <CardTitle testid="service-log-checklist-title">Checklist</CardTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 18 }}
                  data-testid="service-log-checklist">
              {(d.checklist_state?.items || []).map((it) => (
                <div
                  key={it.key}
                  style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}
                  data-testid={`service-log-checklist-item-${it.key}`}
                >
                  {it.completed ? (
                    <div style={{
                      width: 20, height: 20, borderRadius: "50%",
                      background: BLUE, color: "white",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <Check size={13} strokeWidth={3} />
                    </div>
                  ) : (
                    <Circle size={20} color={colors.muted} />
                  )}
                  <span style={{
                    color: it.completed ? colors.onSurface : colors.muted,
                    textDecoration: it.completed ? "none" : "none",
                  }}>{it.label}</span>
                </div>
              ))}
            </div>

            <CardTitle testid="service-log-previous-title">Previous Service</CardTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 18 }}
                  data-testid="service-log-previous">
              {(d.previous_service || []).length === 0 ? (
                <div style={{ fontSize: 12, color: colors.muted }}>
                  No prior completed service for this property.
                </div>
              ) : null}
              {(d.previous_service || []).map((p) => (
                <div key={p.job_id} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "6px 0",
                  borderBottom: `1px solid ${colors.border || "#E2E8F0"}`,
                }} data-testid={`service-log-previous-row-${p.job_id}`}>
                  <div style={{ fontSize: 13, color: colors.onSurface }}>
                    {formatDateTime(p.completed_at)}
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(`/workstream/${p.job_id}`)}
                    data-testid={`service-log-previous-view-${p.job_id}`}
                    style={{
                      background: "transparent", border: `1px solid ${BLUE}`,
                      color: BLUE, borderRadius: 999,
                      padding: "3px 12px", fontSize: 11, fontWeight: 700,
                      letterSpacing: "0.04em", cursor: "pointer",
                    }}
                  >
                    VIEW
                  </button>
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={emailDoorHanger}
              disabled={emailing}
              data-testid="service-log-email-door-hanger"
              style={{
                width: "100%", padding: "12px 16px",
                background: emailing ? "#94A3B8" : BLUE,
                color: "white", border: "none", borderRadius: 10,
                fontSize: 13, fontWeight: 700, letterSpacing: "0.04em",
                textTransform: "uppercase", cursor: emailing ? "wait" : "pointer",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              }}
            >
              {emailing ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />}
              {emailing ? "Sending…" : "Email Door Hanger"}
            </button>
          </Card>
        </div>

        {/* MIDDLE — Water Test / Chemicals (pool) OR Service Notes (landscape) */}
        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 20 }}>
          {isPool ? (
            <>
              <Card testid="service-log-water-test">
                <CardTitle>Water Test Results</CardTitle>
                {(d.water_test || []).length === 0 ? (
                  <div style={{ fontSize: 12, color: colors.muted }}>
                    No water test recorded on this job.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {d.water_test.map((r) => (
                      <div key={r.key} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        fontSize: 14,
                      }} data-testid={`service-log-water-test-${r.key}`}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, color: colors.onSurface }}>
                          <TestTube2 size={16} color={BLUE} />
                          <span>{r.label}</span>
                        </div>
                        <div style={{ fontWeight: 600, color: colors.onSurface }}>
                          {r.value}{r.unit ? ` ${r.unit}` : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card testid="service-log-chemicals-used">
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  marginBottom: 12,
                }}>
                  <CardTitle>Chemical Used</CardTitle>
                  <div style={{
                    background: "#FEE2E2", color: "#991B1B",
                    padding: "3px 10px", borderRadius: 999,
                    fontSize: 11, fontWeight: 700, letterSpacing: "0.02em",
                  }} data-testid="service-log-chem-cost">
                    Chemical Cost ${(d.chemical_cost_usd || 0).toFixed(2)}
                  </div>
                </div>
                {(d.chemicals_used || []).length === 0 ? (
                  <div style={{ fontSize: 12, color: colors.muted }}>
                    No chemicals recorded on this job.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {d.chemicals_used.map((c, i) => (
                      <div key={i} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        fontSize: 14,
                      }} data-testid={`service-log-chem-row-${i}`}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, color: colors.onSurface }}>
                          <Droplet size={16} color={BLUE} />
                          <span>{c.name}</span>
                        </div>
                        <div style={{ fontWeight: 600, color: colors.onSurface }}>
                          {c.display}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </>
          ) : (
            <Card testid="service-log-landscape-notes">
              <CardTitle>Service Notes</CardTitle>
              <div style={{
                fontSize: 13, color: colors.onSurface,
                lineHeight: 1.5, whiteSpace: "pre-wrap",
                minHeight: 60,
              }} data-testid="service-log-notes-body">
                {d.service_notes || <span style={{ color: colors.muted }}>No notes recorded.</span>}
              </div>
              {(d.materials_used || []).length > 0 ? (
                <>
                  <div style={{ marginTop: 20 }}>
                    <CardTitle>Materials Used</CardTitle>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {d.materials_used.map((m, i) => (
                      <div key={i} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        fontSize: 14,
                      }} data-testid={`service-log-material-${i}`}>
                        <span style={{ color: colors.onSurface }}>
                          {m.description || m.name || `Material #${i + 1}`}
                        </span>
                        <span style={{ color: colors.muted }}>
                          {m.quantity || m.qty || ""}
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}
            </Card>
          )}
        </div>

        {/* RIGHT — Service Images */}
        <div style={{ minWidth: 0 }}>
          <MediaCarousel items={d.service_images || []} />
        </div>
      </div>

      {/* Mobile stack: media class rules */}
      <style>{`
        @media (max-width: 900px) {
          [data-testid="service-log-columns"] {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
