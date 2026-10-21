/**
 * TD-96-mobile-timeline b1 · LeadCommunicationTimeline (web LeadDetail.jsx parity).
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockToast = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));

import LeadCommunicationTimeline, { truncateBody } from "@/src/components/leads/LeadCommunicationTimeline";

const SMS = { id: "c1", type: "sms", direction: "outbound", status: "sent", body: "E2E tester ping", created_at: "2026-09-15T04:53:03+00:00" };
const INBOUND = { id: "i1", type: "sms", direction: "inbound", status: "received", body: "Yes please", created_at: "2026-09-15T05:00:00+00:00" };
const EMAIL = { id: "e1", type: "email", direction: "outbound", status: "sent", subject: "Your quote", body: "Hi there", created_at: "2026-09-14T05:00:00+00:00" };
const STATUS = { id: "status:2026-09-16T11:28:40+00:00", type: "status_change", direction: null, status: "contacted", body: null, created_at: "2026-09-16T11:28:40+00:00" };
const page = (items: any[], extra: any = {}) => ({ items, next_cursor: null, has_more: false, ...extra });
const BASE = "/leads/L1/communications?limit=50";

beforeEach(() => { mockGet.mockReset(); mockToast.mockReset(); });

const mount = async (props: any = {}) => {
  const q = render(<LeadCommunicationTimeline leadId="L1" {...props} />);
  await waitFor(() => expect(mockGet).toHaveBeenCalled());
  await act(async () => {});
  return q;
};

it("T1 · mount → GET limit=50 (no cursor); Loading… until resolve", async () => {
  let resolve: any;
  mockGet.mockReturnValue(new Promise((r) => { resolve = r; }));
  const q = render(<LeadCommunicationTimeline leadId="L1" />);
  expect(mockGet).toHaveBeenCalledWith(BASE);
  expect(q.getByTestId("lead-communication-timeline-loading")).toBeTruthy();
  await act(async () => { resolve(page([SMS])); });
  expect(q.queryByTestId("lead-communication-timeline-loading")).toBeNull();
});

it("T2 · empty → 'No communications yet.'; no Load more", async () => {
  mockGet.mockResolvedValue(page([]));
  const q = await mount();
  expect(q.getByTestId("lead-communication-timeline-empty").props.children).toBe("No communications yet.");
  expect(q.queryByTestId("lead-communication-timeline-load-more")).toBeNull();
});

it("T3 · outbound SMS row → SMS pill (no inbound suffix), status, body", async () => {
  mockGet.mockResolvedValue(page([SMS]));
  const q = await mount();
  expect(q.getByTestId("lead-comm-item-sms")).toBeTruthy();
  expect(q.getByText("SMS")).toBeTruthy();
  expect(q.getByText("sent")).toBeTruthy();
  expect(q.getByText("E2E tester ping")).toBeTruthy();
});

it("T4 · inbound SMS → 'SMS · inbound' pill", async () => {
  mockGet.mockResolvedValue(page([INBOUND]));
  const q = await mount();
  expect(q.getByText("SMS · inbound")).toBeTruthy();
  expect(q.getByText("received")).toBeTruthy();
});

it("T5 · email row → Email pill + subject + body", async () => {
  mockGet.mockResolvedValue(page([EMAIL]));
  const q = await mount();
  expect(q.getByTestId("lead-comm-item-email")).toBeTruthy();
  expect(q.getByText("Email")).toBeTruthy();
  expect(q.getByText("Your quote")).toBeTruthy();
  expect(q.getByText("Hi there")).toBeTruthy();
});

it("T6 · status_change row → 'Status change' pill + target status, no body", async () => {
  mockGet.mockResolvedValue(page([STATUS]));
  const q = await mount();
  expect(q.getByTestId("lead-comm-item-status_change")).toBeTruthy();
  expect(q.getByText("Status change")).toBeTruthy();
  expect(q.getByText("contacted")).toBeTruthy();
});

it("T7 · body cut at 400 chars + ellipsis; exactly 400 untouched", async () => {
  expect(truncateBody("x".repeat(400))).toBe("x".repeat(400));
  expect(truncateBody("y".repeat(401))).toBe("y".repeat(400) + "…");
  mockGet.mockResolvedValue(page([{ ...SMS, body: "z".repeat(450) }]));
  const q = await mount();
  expect(q.getByText("z".repeat(400) + "…")).toBeTruthy();
});

it("T8 · error field → 'Error: …'", async () => {
  mockGet.mockResolvedValue(page([{ ...SMS, status: "failed", error: "invalid_phone" }]));
  const q = await mount();
  expect(q.getByText("Error: invalid_phone")).toBeTruthy();
});

it("T9 · unknown type → label falls back to the raw type; missing type → status_change", async () => {
  mockGet.mockResolvedValue(page([{ id: "x1", type: "call", created_at: null }, { id: "x2" }]));
  const q = await mount();
  expect(q.getByTestId("lead-comm-item-call")).toBeTruthy();
  expect(q.getByText("call")).toBeTruthy();
  expect(q.getByTestId("lead-comm-item-status_change")).toBeTruthy();
});

it("T10 · has_more → Load more sends the URL-encoded cursor and APPENDS the page", async () => {
  const cur = "2026-09-15T04:53:03+00:00|c1";
  mockGet.mockResolvedValueOnce(page([SMS], { has_more: true, next_cursor: cur })).mockResolvedValueOnce(page([EMAIL]));
  const q = await mount();
  await act(async () => { fireEvent.press(q.getByTestId("lead-communication-timeline-load-more")); });
  expect(mockGet).toHaveBeenLastCalledWith(`${BASE}&cursor=${encodeURIComponent(cur)}`);
  expect(q.getByTestId("lead-comm-item-sms")).toBeTruthy();
  expect(q.getByTestId("lead-comm-item-email")).toBeTruthy();
  expect(q.queryByTestId("lead-communication-timeline-load-more")).toBeNull();
});

it("T11 · Refresh → refetch WITHOUT cursor and REPLACE the list", async () => {
  mockGet.mockResolvedValueOnce(page([SMS])).mockResolvedValueOnce(page([EMAIL]));
  const q = await mount();
  await act(async () => { fireEvent.press(q.getByTestId("lead-communication-timeline-refresh")); });
  expect(mockGet).toHaveBeenLastCalledWith(BASE);
  expect(q.queryByTestId("lead-comm-item-sms")).toBeNull();
  expect(q.getByTestId("lead-comm-item-email")).toBeTruthy();
});

it("T12 · refreshKey change → refetch; same key → no extra fetch", async () => {
  mockGet.mockResolvedValue(page([SMS]));
  const q = await mount({ refreshKey: 0 });
  q.rerender(<LeadCommunicationTimeline leadId="L1" refreshKey={0} />);
  await act(async () => {});
  expect(mockGet).toHaveBeenCalledTimes(1);
  q.rerender(<LeadCommunicationTimeline leadId="L1" refreshKey={1} />);
  await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
});

it("T13 · fetch rejects → error toast (web 'Failed to load communications'), card intact", async () => {
  mockGet.mockRejectedValue(new Error("boom"));
  const q = await mount();
  expect(mockToast).toHaveBeenCalledWith("Failed to load communications — boom", "error");
  expect(q.getByTestId("lead-communication-timeline")).toBeTruthy();
  expect(q.getByTestId("lead-communication-timeline-empty")).toBeTruthy();
});

it("T14 · stale response dropped: Refresh while the first page is in flight", async () => {
  let first: any;
  mockGet.mockReturnValueOnce(new Promise((r) => { first = r; })).mockResolvedValueOnce(page([EMAIL]));
  const q = render(<LeadCommunicationTimeline leadId="L1" />);
  await act(async () => { fireEvent.press(q.getByTestId("lead-communication-timeline-refresh")); });
  await act(async () => { first(page([SMS])); });
  expect(q.queryByTestId("lead-comm-item-sms")).toBeNull();
  expect(q.getByTestId("lead-comm-item-email")).toBeTruthy();
});

it("T15 · no 'View details' affordance this ship (TD-96-mobile-comm-detail)", async () => {
  mockGet.mockResolvedValue(page([SMS, EMAIL, STATUS]));
  const q = await mount();
  expect(q.queryAllByTestId(/^lead-comm-view-detail-/)).toHaveLength(0);
  expect(q.queryByText("View details")).toBeNull();
});
