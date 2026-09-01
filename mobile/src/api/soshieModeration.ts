/**
 * Soshie Moderation Queue API helpers — Phase H8 · F3 + H5.5 parity.
 * Mirrors web SoshieModerationQueue.jsx + ReviewQueueTab.jsx endpoints.
 */
import { api } from "@/src/api";

export type ModerationPost = {
  id: string;
  platform?: string;
  scheduled_at?: string;
  preview?: string;
  media_url?: string;
  moderation_decision?: string;
  moderation_reasons?: string[];
  status?: string;
  manual_only_platform?: string;
  manual_posted_at?: string;
  draft_text?: string;
  draft?: {
    text?: string;
    title?: string;
    media_url?: string;
    platform?: string;
  };
  summary?: string;
  created_at?: string;
};

/** Fetch moderation queue. status: "awaiting_review" | "blocked" | "rejected" | "all" */
export const getModerationQueue = (status: string) =>
  api.get(`/soshie/moderation/queue?status=${encodeURIComponent(status)}`) as Promise<{
    posts: ModerationPost[];
  }>;

/** Approve a moderation post. */
export const approveModerationPost = (id: string) =>
  api.post(`/soshie/moderation/${id}/approve`);

/** Reject a moderation post. */
export const rejectModerationPost = (id: string) =>
  api.post(`/soshie/moderation/${id}/reject`, { reason: "admin_reject" });

/** Mark a post as manually posted. */
export const markModerationPosted = (id: string) =>
  api.post(`/soshie/moderation/${id}/mark-posted`, {});
