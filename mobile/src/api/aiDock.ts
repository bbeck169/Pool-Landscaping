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
  action?: string;
  title?: string;
  summary?: string;
  status?: string; // pending | approved | rejected | executed | failed
  draft?: any;
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

export const createConversation = (eid: string, title?: string) =>
  api.post(`/ai-employees/${eid}/conversations`, { title: title || "New conversation" });

export const getMessages = (eid: string, cid: string) =>
  api.get(`/ai-employees/${eid}/conversations/${cid}/messages`);

export const sendConversationMessage = (
  eid: string,
  cid: string,
  text: string,
  action?: string,
  actionParams?: Record<string, any>,
) =>
  api.post(`/ai-employees/${eid}/conversations/${cid}/messages`, {
    text,
    ...(action ? { action, action_params: actionParams } : {}),
  });

export const listPendingActions = (employeeKey?: string): Promise<AIAction[]> =>
  api.get(`/ai-employees/actions${employeeKey ? `?status=pending&employee_key=${employeeKey}` : ""}`);

export const approveAction = (aid: string) =>
  api.post(`/ai-employees/actions/${aid}/approve`, {});

export const rejectAction = (aid: string) =>
  api.post(`/ai-employees/actions/${aid}/reject`, {});
