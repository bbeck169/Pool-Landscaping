import { api } from "@/src/api";

export type WorkstreamJob = {
  id: string;
  title?: string;
  status?: string;
  service_type?: string;
  scheduled_date?: string;
  scheduled_start?: string;
  scheduled_end?: string;
  customer_name?: string;
  customer_id?: string;
  technician_name?: string;
  technician_id?: string;
  property_label?: string;
  property_address?: string;
  notes_count?: number;
  line_items_count?: number;
  media?: {
    photos_count?: number;
    videos_count?: number;
    photo_thumbs?: { id: string }[];
    video_thumbs?: { id: string }[];
  };
  latest_activity?: string;
  created_at?: string;
  updated_at?: string;
};

export type WorkstreamFilters = {
  since?: string;
  until?: string;
  tech_id?: string;
  customer_id?: string;
  status?: string;
  sort?: string;
  limit?: number;
  offset?: number;
};

export const getWorkstreamJobs = (filters: WorkstreamFilters = {}): Promise<WorkstreamJob[]> => {
  const params = new URLSearchParams();
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.tech_id) params.set("tech_id", filters.tech_id);
  if (filters.customer_id) params.set("customer_id", filters.customer_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return api.get(`/workstream/jobs${qs ? `?${qs}` : ""}`);
};
