/**
 * TD-98-be-cleanup b2 · CommunicationTimeline on the super-timeline
 * endpoints + guard that mobile never calls the legacy endpoint again.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPush = jest.fn();
let mockRole = "admin";

jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));

import CommunicationTimeline from "@/src/components/customers/CommunicationTimeline";

const err = (status: number, detail: any) => Object.assign(new Error(`HTTP ${status}`), { status, detail });
const ITEMS = [
  { id: "i1", kind: "invoice", source_type: "invoice", status: "draft", summary: "Invoice INV-1 · $120.00", url: "/invoices/i1", occurred_at: "2026-10-01T00:00:00Z", actor: null },
  { id: "s1", kind: "sms", delivery_status: "delivered", body: "On my way!", recipient: "+15550001111", occurred_at: "2026-09-30T00:00:00Z", actor: null },
  { id: "n1", kind: "note", source_type: "note", summary: "Note", detail: { note_body: "Gate code 1234" }, actor: { display_name: "Ada Admin", role: "admin" }, occurred_at: "2026-09-29T00:00:00Z" },
];
const page = (items: any[], p = 1, totalPages = 1) => ({ items, page: p, page_size: 20, total: items.length, total_pages: totalPages, next_before: null });

beforeEach(() => { mockRole = "admin"; mockPush.mockClear(); mockGet.mockReset().mockResolvedValue(page(ITEMS)); });

it("C1 · admin → /customers/{cid}/timeline page 1; 6-kind rows; invoice url row opens /quote/<id>; note body + actor object", async () => {
  const q = render(<CommunicationTimeline customerId="c1" variant="admin" />);
  await waitFor(() => q.getByTestId("communication-timeline-list"));
  expect(mockGet).toHaveBeenCalledWith("/customers/c1/timeline?page=1&page_size=20");
  expect(q.getByTestId("timeline-pill-invoice")).toBeTruthy();
  expect(q.getByTestId("timeline-status-s1")).toBeTruthy(); // admin sees delivery status
  expect(q.getByTestId("timeline-body-n1").props.children).toBe("Gate code 1234");
  expect(q.getByTestId("timeline-actor-n1").props.children).toBe("Ada Admin");
  fireEvent.press(q.getByTestId("timeline-open-i1"));
  expect(mockPush).toHaveBeenCalledWith("/quote/i1");
});

it("C2 · portal → /customers/me/timeline (page mode); base chips only; message delivery status hidden, doc status shown", async () => {
  mockRole = "customer";
  mockGet.mockResolvedValue(page([{ ...ITEMS[0], url: "/portal/invoices/i1" }, ITEMS[1]]));
  const q = render(<CommunicationTimeline customerId="cust-1" variant="portal" limit={20} />);
  await waitFor(() => q.getByTestId("communication-timeline-list"));
  expect(mockGet).toHaveBeenCalledWith("/customers/me/timeline?page=1&page_size=20");
  expect(q.queryByTestId("communication-timeline-chip-call")).toBeNull();
  expect(q.getByTestId("communication-timeline-chip-invoice")).toBeTruthy();
  expect(q.queryByTestId("timeline-status-s1")).toBeNull();
  expect(q.getByTestId("timeline-status-i1")).toBeTruthy();
  fireEvent.press(q.getByTestId("timeline-open-i1"));
  expect(mockPush).toHaveBeenCalledWith("/portal/invoices");
});

it("C3 · page-mode Load more appends page N+1 and disappears on the last page", async () => {
  mockGet.mockResolvedValueOnce(page([ITEMS[0]], 1, 2)).mockResolvedValueOnce(page([ITEMS[1]], 2, 2));
  const q = render(<CommunicationTimeline customerId="c1" />);
  await waitFor(() => q.getByTestId("communication-timeline-load-more"));
  await act(async () => { fireEvent.press(q.getByTestId("communication-timeline-load-more")); });
  expect(mockGet).toHaveBeenLastCalledWith("/customers/c1/timeline?page=2&page_size=20");
  expect(q.getByTestId("timeline-row-i1")).toBeTruthy();
  expect(q.getByTestId("timeline-row-s1")).toBeTruthy();
  expect(q.queryByTestId("communication-timeline-load-more")).toBeNull();
});

it("C4 · chip filter → refetch page 1 with kind=<chip>; 'All' drops the kind param", async () => {
  const q = render(<CommunicationTimeline customerId="c1" />);
  await waitFor(() => q.getByTestId("communication-timeline-list"));
  await act(async () => { fireEvent.press(q.getByTestId("communication-timeline-chip-sms")); });
  expect(mockGet).toHaveBeenLastCalledWith("/customers/c1/timeline?page=1&page_size=20&kind=sms");
  expect(q.getByTestId("communication-timeline-chip-sms").props.accessibilityState?.selected).toBe(true);
  await act(async () => { fireEvent.press(q.getByTestId("communication-timeline-chip-all")); });
  expect(mockGet).toHaveBeenLastCalledWith("/customers/c1/timeline?page=1&page_size=20");
});

it("C5 · admin + super_admin get call/note chips; manager does not", async () => {
  for (const [role, has] of [["super_admin", true], ["manager", false]] as const) {
    mockRole = role;
    const q = render(<CommunicationTimeline customerId="c1" />);
    await waitFor(() => q.getByTestId("communication-timeline-list"));
    expect(!!q.queryByTestId("communication-timeline-chip-note")).toBe(has);
    q.unmount();
  }
});

it("C6 · any 403 (insufficient_role_for_full_timeline or tech Forbidden) → silent empty state, no red error box", async () => {
  for (const e of [err(403, "insufficient_role_for_full_timeline"), err(403, "Forbidden")]) {
    mockGet.mockRejectedValueOnce(e);
    const q = render(<CommunicationTimeline customerId="c1" />);
    await waitFor(() => q.getByTestId("communication-timeline-empty"));
    expect(q.queryByTestId("communication-timeline-error")).toBeNull();
    q.unmount();
  }
});

it("C7 · non-403 failure still shows the error box", async () => {
  mockGet.mockRejectedValueOnce(err(500, "boom"));
  const q = render(<CommunicationTimeline customerId="c1" />);
  await waitFor(() => q.getByTestId("communication-timeline-error"));
});

it("G1 · guard: the legacy communication-timeline endpoint path appears nowhere in mobile/src or mobile/app", () => {
  const root = path.resolve(__dirname, "..");
  const hits: string[] = [];
  const walk = (dir: string) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) { if (ent.name !== "node_modules") walk(p); continue; }
      if (!/\.(tsx?|jsx?)$/.test(ent.name)) continue;
      if (/\/communication-timeline\b/.test(fs.readFileSync(p, "utf8"))) hits.push(path.relative(root, p));
    }
  };
  walk(path.join(root, "src"));
  walk(path.join(root, "app"));
  expect(hits).toEqual([]);
});
