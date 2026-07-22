import { api } from "@/src/api";

export type ServiceLogData = {
  job_id: string;
  service_line: string;
  log_details: {
    customer_name: string;
    customer_id?: string | null;
    customer_email?: string | null;
    property_address: string;
    property_id?: string | null;
    service_at?: string | null;
    time_spent_minutes?: number | null;
    employee_name: string;
    employee_id?: string | null;
  };
  employee: {
    id?: string | null;
    name: string;
    phone?: string | null;
    department?: string | null;
  };
  customer?: {
    id: string;
    name: string;
    email?: string;
    phone?: string;
  } | null;
  property?: {
    id: string;
    label: string;
    address?: {
      line1?: string;
      line2?: string | null;
      city?: string;
      state?: string;
      postal_code?: string;
      country?: string;
    };
  } | null;
  checklist_state: {
    service_line: string;
    items: { key: string; label: string; completed: boolean }[];
  };
  water_test: { label: string; value: number | string | null; unit?: string }[];
  chemicals_used: { name: string; amount: number | string; unit?: string }[];
  chemical_cost_cents: number;
  chemical_cost_usd: number;
  service_notes?: string;
  materials_used?: { name: string; quantity?: number; unit?: string }[];
  service_images: { url: string; kind: "image" | "video" }[];
  previous_service: { job_id: string; completed_at?: string }[];
};

export const getServiceLog = (jid: string): Promise<ServiceLogData> =>
  api.get(`/jobs/${jid}/service-log`);

export const emailDoorHanger = (jid: string): Promise<any> =>
  api.post(`/jobs/${jid}/email-door-hanger`, {});

export type DailyChecklistResponse = {
  service_line: string;
  items: { key: string; label: string }[];
};

export const getDailyChecklist = (serviceLine?: string): Promise<DailyChecklistResponse> => {
  const qs = serviceLine ? `?service_line=${serviceLine}` : "";
  return api.get(`/checklists/daily${qs}`);
};
