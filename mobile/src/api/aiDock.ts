/**
 * AI Dock API — Mobile Parity (admin + super_admin only).
 */
import { api } from "@/src/api";

export type AIEmployee = {
  id: string;
  key: string;
  name: string;
  role: string;
  description?: string;
  avatar?: string;
  icon?: string;
  active?: boolean;
};

export type AICreditBalance = {
  balance: number;
  plan?: string;
  monthly_budget?: number;
  used_this_month?: number;
};

export type AIAction = {
  id: string;
  employee_id?: string;
  employee_key?: string;
  action_type?: string;
  label?: string;
  description?: string;
  status?: string; // pending | approved | rejected
  payload?: any;
  created_at?: string;
};

export const listAIEmployees = (): Promise<AIEmployee[]> =>
  api.get("/ai-employees");

export const getAIEmployee = (eid: string): Promise<AIEmployee> =>
  api.get(`/ai-employees/${eid}`);

export const getAICreditsBalance = (): Promise<AICreditBalance> =>
  api.get("/ai-credits/balance");

export const listConversations = (eid: string) =>
  api.get(`/ai-employees/${eid}/conversations`);

export const createConversation = (eid: string) =>
  api.post(`/ai-employees/${eid}/conversations`, {});

export const getMessages = (eid: string, cid: string) =>
  api.get(`/ai-employees/${eid}/conversations/${cid}/messages`);

export const sendMessage = (
  eid: string,
  cid: string,
  message: string,
  action?: any
) =>
  api.post(`/ai-employees/${eid}/conversations/${cid}/messages`, {
    message,
    ...(action ? { action } : {}),
  });

export const chatSimple = (employeeId: string, message: string, sessionId?: string | null) =>
  api.post("/ai-employees/chat", {
    employee_id: employeeId,
    message,
    ...(sessionId ? { session_id: sessionId } : {}),
  });

export const listPendingActions = (): Promise<AIAction[]> =>
  api.get("/ai-employees/actions");

export const approveAction = (aid: string) =>
  api.post(`/ai-employees/actions/${aid}/approve`, {});

export const rejectAction = (aid: string) =>
  api.post(`/ai-employees/actions/${aid}/reject`, {});
