/**
 * Reviews Subsystem · Phase 2 API client (Feb 2026).
 *
 * Thin wrapper over the FastAPI ``/api/reviews/*`` endpoints that
 * shipped in Phase 1. Uses the shared ``api`` helper from ``@/api`` so
 * bearer-token injection + ``REACT_APP_BACKEND_URL`` routing stay
 * uniform with the rest of the admin surface.
 *
 * Callers see raw arrays where the backend wraps them (``{platforms:
 * [...]}`` / ``{requests: [...]}`` / ``{leaderboard: [...]}``) — the
 * unwrapping happens here so page code stays terse.
 */
import { api } from "@/api";

// ─── Platforms ────────────────────────────────────────────────────────
export const listPlatforms = () =>
  api.get("/reviews/platforms").then((d) => d?.platforms || []);
export const createPlatform = (body) => api.post("/reviews/platforms", body);
export const updatePlatform = (id, body) =>
  api.patch(`/reviews/platforms/${encodeURIComponent(id)}`, body);
export const deletePlatform = (id) =>
  api.del(`/reviews/platforms/${encodeURIComponent(id)}`);

// ─── Requests ─────────────────────────────────────────────────────────
export const listRequests = (params = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null),
  ).toString();
  return api.get(`/reviews/requests${qs ? `?${qs}` : ""}`)
    .then((d) => d?.requests || []);
};
export const getRequest = (id) =>
  api.get(`/reviews/requests/${encodeURIComponent(id)}`);
export const createRequest = (body) => api.post("/reviews/requests", body);
export const resendRequest = (id) =>
  api.post(`/reviews/requests/${encodeURIComponent(id)}/resend`, {});

// ─── Reviews ──────────────────────────────────────────────────────────
export const listReviews = (params = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null),
  ).toString();
  return api.get(`/reviews/reviews${qs ? `?${qs}` : ""}`)
    .then((d) => d?.reviews || []);
};
export const getReview = (id) =>
  api.get(`/reviews/reviews/${encodeURIComponent(id)}`);
export const createReview = (body) => api.post("/reviews/reviews", body);
export const updateReview = (id, body) =>
  api.patch(`/reviews/reviews/${encodeURIComponent(id)}`, body);
export const deleteReview = (id) =>
  api.del(`/reviews/reviews/${encodeURIComponent(id)}`);

// ─── Analytics ────────────────────────────────────────────────────────
export const getStats = () => api.get("/reviews/stats");
export const getLeaderboard = (min_reviews = 3) =>
  api.get(`/reviews/leaderboard?min_reviews=${min_reviews}`)
    .then((d) => d?.leaderboard || []);

// ─── Public magic-link (no auth — used by the landing page) ──────────
export const fetchPublicLanding = (token) => {
  const base = process.env.REACT_APP_BACKEND_URL;
  return fetch(`${base}/api/reviews/public/r/${encodeURIComponent(token)}`, {
    headers: { "Accept": "application/json" },
  }).then((r) => r.json());
};
export const submitPublicRating = (token, star_rating) => {
  const base = process.env.REACT_APP_BACKEND_URL;
  return fetch(`${base}/api/reviews/public/r/${encodeURIComponent(token)}/rating`, {
    method: "POST",
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ star_rating }),
  }).then(async (r) => {
    const t = await r.text();
    let d = null; try { d = JSON.parse(t); } catch { /* noop */ }
    if (!r.ok) throw new Error(d?.detail || `Request failed (${r.status})`);
    return d;
  });
};
export const submitPublicPlatformClicked = (token, platform_code) => {
  const base = process.env.REACT_APP_BACKEND_URL;
  return fetch(`${base}/api/reviews/public/r/${encodeURIComponent(token)}/platform-clicked`, {
    method: "POST",
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ platform_code }),
  }).then(async (r) => {
    const t = await r.text();
    let d = null; try { d = JSON.parse(t); } catch { /* noop */ }
    if (!r.ok) throw new Error(d?.detail || `Request failed (${r.status})`);
    return d;
  });
};
export const submitPublicPrivateFeedback = (token, body_text) => {
  const base = process.env.REACT_APP_BACKEND_URL;
  return fetch(`${base}/api/reviews/public/r/${encodeURIComponent(token)}/private-feedback`, {
    method: "POST",
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ body_text }),
  }).then(async (r) => {
    const t = await r.text();
    let d = null; try { d = JSON.parse(t); } catch { /* noop */ }
    if (!r.ok) throw new Error(d?.detail || `Request failed (${r.status})`);
    return d;
  });
};

// ─── Public widget JSON (no auth) ─────────────────────────────────────
export const fetchWidgetJson = (tenant_slug, limit = 20) => {
  const base = process.env.REACT_APP_BACKEND_URL;
  return fetch(`${base}/api/reviews/public/widget/${encodeURIComponent(tenant_slug)}?limit=${limit}`, {
    headers: { "Accept": "application/json" },
  }).then((r) => r.json());
};

// ─── Enums / catalogs mirrored from backend ───────────────────────────
export const PLATFORMS = [
  { code: "google",   label: "Google" },
  { code: "facebook", label: "Facebook" },
  { code: "yelp",     label: "Yelp" },
  { code: "bbb",      label: "BBB" },
  { code: "custom",   label: "Custom" },
];

export const OUTCOMES = [
  { code: "pending",                    label: "Pending"                },
  { code: "public_posted_intent",       label: "Sent to platform"       },
  { code: "private_feedback_captured",  label: "Private feedback"       },
  { code: "expired",                    label: "Expired"                },
  { code: "opted_out",                  label: "Opted out"              },
];

export const SENT_VIA_OPTIONS = [
  { code: "email",     label: "Email"       },
  { code: "sms",       label: "SMS"         },
  { code: "both",      label: "Email + SMS" },
  { code: "link_only", label: "Copy link only" },
];
