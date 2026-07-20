/**
 * Reviews Subsystem · Phase 3 mobile parity — API client (Feb 2026).
 *
 * Mirrors the web ``frontend/src/api/reviews.js`` surface. Uses the
 * shared ``api`` helper so bearer-token injection + backend base URL
 * stay uniform with the rest of the mobile app.
 *
 * Response unwrapping matches the web client (``{platforms:[...]}`` →
 * ``[...]`` etc.) so screen code doesn't have to think about it.
 */
import { api } from "@/src/api";

// ─── Platforms ────────────────────────────────────────────────────────
export const listPlatforms = () =>
  api.get("/reviews/platforms").then((d: any) => d?.platforms || []);
export const updatePlatform = (id: string, body: any) =>
  api.patch(`/reviews/platforms/${encodeURIComponent(id)}`, body);

// ─── Requests ─────────────────────────────────────────────────────────
export const listRequests = (params: Record<string, string | undefined> = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(
      ([, v]) => v !== undefined && v !== "" && v !== null
    ) as [string, string][]
  ).toString();
  return api
    .get(`/reviews/requests${qs ? `?${qs}` : ""}`)
    .then((d: any) => d?.requests || []);
};
export const getRequest = (id: string) =>
  api.get(`/reviews/requests/${encodeURIComponent(id)}`);
export const createRequest = (body: any) => api.post("/reviews/requests", body);
export const resendRequest = (id: string) =>
  api.post(`/reviews/requests/${encodeURIComponent(id)}/resend`, {});

// ─── Reviews ──────────────────────────────────────────────────────────
export const listReviews = (params: Record<string, string | undefined> = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(
      ([, v]) => v !== undefined && v !== "" && v !== null
    ) as [string, string][]
  ).toString();
  return api
    .get(`/reviews/reviews${qs ? `?${qs}` : ""}`)
    .then((d: any) => d?.reviews || []);
};
export const updateReview = (id: string, body: any) =>
  api.patch(`/reviews/reviews/${encodeURIComponent(id)}`, body);

// ─── Analytics ────────────────────────────────────────────────────────
export const getStats = () => api.get("/reviews/stats");
export const getLeaderboard = (min_reviews: number = 3) =>
  api
    .get(`/reviews/leaderboard?min_reviews=${min_reviews}`)
    .then((d: any) => d?.leaderboard || []);

// ─── Phase 3 · external sync surface ─────────────────────────────────
export const syncPlatformNow = (platform: string) =>
  api.post(
    `/reviews/sync/${encodeURIComponent(platform)}/sync-now`,
    {}
  );
export const listSyncEvents = (platform?: string, limit: number = 50) => {
  const qs = new URLSearchParams();
  if (platform) qs.append("platform", platform);
  qs.append("limit", String(limit));
  return api.get(`/reviews/sync/events?${qs.toString()}`);
};
export const getLatestSyncPerPlatform = () => api.get("/reviews/sync/latest");

// ─── Static catalogs ─────────────────────────────────────────────────
export const PLATFORMS = [
  { code: "google", label: "Google" },
  { code: "facebook", label: "Facebook" },
  { code: "yelp", label: "Yelp" },
  { code: "bbb", label: "BBB" },
  { code: "custom", label: "Custom" },
];

export const OUTCOMES = [
  { code: "pending", label: "Pending" },
  { code: "public_posted_intent", label: "Sent to platform" },
  { code: "private_feedback_captured", label: "Private feedback" },
  { code: "expired", label: "Expired" },
  { code: "opted_out", label: "Opted out" },
];

export const SENT_VIA_OPTIONS = [
  { code: "email", label: "Email" },
  { code: "sms", label: "SMS" },
  { code: "both", label: "Email + SMS" },
  { code: "link_only", label: "Copy link only" },
];
