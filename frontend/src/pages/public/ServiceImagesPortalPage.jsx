/**
 * Feb 2026 · Public Service Images Portal.
 *
 * Unauthenticated page rendered at ``/portal/service/:uuid``. Fetches the
 * ``/api/public/service/{uuid}`` endpoint (no login) and displays the
 * business identity, service date/type, tech first name, and a grid of
 * full-size images with a click-to-lightbox interaction.
 *
 * NEVER shows customer name, address, phone, email, chemistry readings,
 * invoice info, or any other PII. Backend enforces this — frontend does
 * not attempt to pull any PII field even if present.
 */
import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";

const API_ROOT = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

export default function ServiceImagesPortalPage() {
  const { uuid } = useParams();
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const [lightboxIndex, setLightboxIndex] = useState(null);

  useEffect(() => {
    let cancel = false;
    async function load() {
      try {
        const res = await fetch(`${API_ROOT}/api/public/service/${uuid}`, {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) {
          const detail = res.status === 429
            ? "Too many requests — please try again in a moment."
            : res.status === 404
              ? "This service link is invalid or has expired."
              : res.status === 410
                ? "This service report is no longer available."
                : `Unable to load service (HTTP ${res.status}).`;
          if (!cancel) setState({ loading: false, error: detail, data: null });
          return;
        }
        const data = await res.json();
        if (!cancel) setState({ loading: false, error: null, data });
      } catch (_e) {
        if (!cancel) {
          setState({
            loading: false,
            error: "Network error — please check your connection.",
            data: null,
          });
        }
      }
    }
    load();
    return () => { cancel = true; };
  }, [uuid]);

  const closeLightbox = useCallback(() => setLightboxIndex(null), []);

  useEffect(() => {
    if (lightboxIndex === null) return;
    const total = ((state.data?.images?.length || 0)
                    + (state.data?.videos?.length || 0));
    function onKey(e) {
      if (e.key === "Escape") closeLightbox();
      else if (e.key === "ArrowRight") {
        setLightboxIndex((i) =>
          i === null ? null : Math.min(i + 1, total - 1));
      } else if (e.key === "ArrowLeft") {
        setLightboxIndex((i) => (i === null ? null : Math.max(i - 1, 0)));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightboxIndex, state.data, closeLightbox]);

  if (state.loading) {
    return (
      <div
        data-testid="service-portal-loading"
        style={rootStyle}
      >
        <div style={{ opacity: 0.6, fontSize: 14 }}>Loading service report…</div>
      </div>
    );
  }

  if (state.error) {
    return (
      <div style={rootStyle}>
        <div
          data-testid="service-portal-error"
          style={{
            maxWidth: 480, padding: 24, textAlign: "center",
            background: "#fff", borderRadius: 12,
            boxShadow: "0 2px 12px rgba(0,0,0,.06)",
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 8 }}>·</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
            Service report unavailable
          </div>
          <div style={{ fontSize: 14, color: "#555" }}>{state.error}</div>
        </div>
      </div>
    );
  }

  const data = state.data || {};
  const images = data.images || [];
  const videos = data.videos || [];
  const chemicalsAdded = data.chemicals_added || [];
  const chemicalReadings = data.chemical_readings || [];
  const checklist = data.checklist || [];
  const media = [
    ...images.map((i) => ({ ...i, __kind: "photo" })),
    ...videos.map((v) => ({ ...v, __kind: "video" })),
  ];

  return (
    <div data-testid="service-portal-root" style={rootStyle}>
      <div style={cardStyle}>
        <header
          data-testid="service-portal-header"
          style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}
        >
          {data.logo_url ? (
            <img
              src={data.logo_url}
              alt={data.business_name}
              data-testid="service-portal-logo"
              style={{ maxHeight: 56, maxWidth: 180 }}
              onError={(e) => { e.currentTarget.style.display = "none"; }}
            />
          ) : null}
          <div>
            <div
              data-testid="service-portal-business-name"
              style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.3 }}
            >
              {data.business_name}
            </div>
            <div style={{ fontSize: 13, color: "#666" }}>Service Visit Report</div>
          </div>
        </header>

        <section
          data-testid="service-portal-meta"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 12,
            marginBottom: 24,
            paddingBottom: 20,
            borderBottom: "1px solid #eee",
          }}
        >
          {data.service_date ? (
            <MetaRow label="Date" value={data.service_date} testid="service-portal-date" />
          ) : null}
          {data.service_type ? (
            <MetaRow label="Service" value={data.service_type} testid="service-portal-type" />
          ) : null}
          {data.tech_first_name ? (
            <MetaRow
              label="Technician"
              value={data.tech_first_name}
              testid="service-portal-tech"
            />
          ) : null}
        </section>

        {chemicalReadings.length > 0 ? (
          <PortalSection title="Chemical Readings" testid="service-portal-readings-section">
            <table cellSpacing="0" style={{ borderCollapse: "collapse" }}
                   data-testid="service-portal-readings-table">
              <tbody>
                {chemicalReadings.map((r, i) => (
                  <tr key={i}>
                    <td style={{ padding: "6px 16px 6px 0", color: "#555" }}>
                      {r.name}
                    </td>
                    <td style={{ padding: "6px 0", fontWeight: 600 }}
                        data-testid={`service-portal-reading-${r.key || i}`}>
                      {r.value}{r.unit ? ` ${r.unit}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </PortalSection>
        ) : null}

        {chemicalsAdded.length > 0 ? (
          <PortalSection title="Chemicals Added" testid="service-portal-chemicals-section">
            <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.6 }}
                data-testid="service-portal-chemicals-list">
              {chemicalsAdded.map((c, i) => {
                const label = c.raw_label
                  ? `${c.raw_label}${c.name ? ` of ${c.name}` : ""}`
                  : [c.quantity, c.unit, c.name && `of ${c.name}`]
                      .filter(Boolean).join(" ");
                return <li key={i}>{label}</li>;
              })}
            </ul>
          </PortalSection>
        ) : null}

        {checklist.length > 0 ? (
          <PortalSection title="Completed Checklist" testid="service-portal-checklist-section">
            <ul style={{ margin: 0, paddingLeft: 0, listStyle: "none", lineHeight: 1.7 }}
                data-testid="service-portal-checklist-list">
              {checklist.map((it, i) => (
                <li key={i} style={{ color: "#333" }}>
                  <span style={{ color: "#059669", fontWeight: 700, marginRight: 6 }}>✓</span>
                  {it.label}
                </li>
              ))}
            </ul>
          </PortalSection>
        ) : null}

        <h2
          style={{
            fontSize: 15, fontWeight: 600, marginBottom: 12,
            color: "#333", textTransform: "uppercase", letterSpacing: 0.6,
          }}
        >
          Photos & Videos
        </h2>
        {media.length === 0 ? (
          <div
            data-testid="service-portal-empty"
            style={{ padding: 32, textAlign: "center", color: "#888", fontSize: 14 }}
          >
            No photos or videos were shared for this visit.
          </div>
        ) : (
          <div
            data-testid="service-portal-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: 10,
            }}
          >
            {media.map((m, idx) => (
              <button
                type="button"
                key={idx}
                data-testid={m.__kind === "video"
                  ? `service-portal-video-${idx}`
                  : `service-portal-thumb-${idx}`}
                onClick={() => setLightboxIndex(idx)}
                style={{
                  padding: 0, border: 0, background: "transparent",
                  cursor: "pointer", borderRadius: 8, overflow: "hidden",
                  aspectRatio: "1", position: "relative",
                }}
              >
                <img
                  src={m.__kind === "video"
                    ? (m.poster_url || m.thumbnail_url || "")
                    : (m.thumbnail_url || m.url)}
                  alt={m.__kind === "video"
                    ? `Service video ${idx + 1}`
                    : `Service photo ${idx + 1}`}
                  style={{
                    width: "100%", height: "100%", objectFit: "cover",
                    display: "block", background: "#3a3a3a",
                    transition: "transform 200ms ease",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.transform = "scale(1.02)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.transform = "scale(1)"; }}
                />
                {m.__kind === "video" ? (
                  <span
                    data-testid={`service-portal-video-play-${idx}`}
                    style={{
                      position: "absolute", top: "50%", left: "50%",
                      transform: "translate(-50%,-50%)",
                      width: 48, height: 48, borderRadius: "50%",
                      background: "rgba(0,0,0,.65)", color: "#fff",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 22, pointerEvents: "none",
                    }}
                  >▶</span>
                ) : null}
              </button>
            ))}
          </div>
        )}

        <footer style={{ marginTop: 32, fontSize: 12, color: "#999", textAlign: "center" }}>
          Powered by {data.business_name}
        </footer>
      </div>

      {lightboxIndex !== null && media[lightboxIndex] ? (
        <div
          data-testid="service-portal-lightbox"
          onClick={closeLightbox}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,.9)",
            display: "flex", alignItems: "center", justifyContent: "center",
            zIndex: 9999, padding: 20,
          }}
        >
          <button
            type="button"
            data-testid="service-portal-lightbox-close"
            onClick={closeLightbox}
            aria-label="Close"
            style={{
              position: "absolute", top: 16, right: 16, fontSize: 32,
              color: "#fff", background: "transparent", border: 0,
              cursor: "pointer", lineHeight: 1,
            }}
          >
            ×
          </button>
          {media[lightboxIndex].__kind === "video" ? (
            <video
              src={media[lightboxIndex].url}
              controls
              autoPlay
              playsInline
              data-testid="service-portal-lightbox-video"
              onClick={(e) => e.stopPropagation()}
              style={{
                maxHeight: "90vh", maxWidth: "90vw", borderRadius: 4,
                background: "#000",
              }}
            />
          ) : (
            <img
              src={media[lightboxIndex].url}
              alt={`Service photo ${lightboxIndex + 1}`}
              data-testid="service-portal-lightbox-image"
              onClick={(e) => e.stopPropagation()}
              style={{
                maxHeight: "90vh", maxWidth: "90vw", objectFit: "contain",
                borderRadius: 4,
              }}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}

function PortalSection({ title, testid, children }) {
  return (
    <section data-testid={testid} style={{ marginBottom: 24 }}>
      <h3 style={{
        fontSize: 13, fontWeight: 700, marginBottom: 10, color: "#333",
        textTransform: "uppercase", letterSpacing: 0.6,
      }}>{title}</h3>
      {children}
    </section>
  );
}

function MetaRow({ label, value, testid }) {
  return (
    <div data-testid={testid}>
      <div style={{ fontSize: 11, color: "#888", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, color: "#222" }}>{value}</div>
    </div>
  );
}

const rootStyle = {
  minHeight: "100vh",
  background: "#f5f6f8",
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "center",
  padding: "40px 16px",
  fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
};

const cardStyle = {
  width: "100%",
  maxWidth: 780,
  background: "#fff",
  padding: 28,
  borderRadius: 14,
  boxShadow: "0 2px 20px rgba(0,0,0,.05)",
};
