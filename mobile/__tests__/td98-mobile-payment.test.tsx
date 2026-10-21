/**
 * TD-98-be-sources-mobile-payment · `payment` kind on the mobile customer timeline.
 * Mirrors BE 2f35d291d (invoice_auto_charged → kind=payment + numeric `total`) and
 * web 28bdef72c (_KIND_META.payment + payment in _BASE_CHIPS + DefaultRow `$X.XX` money chip).
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
let mockRole = "admin";
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));

import CommunicationTimeline from "@/src/components/customers/CommunicationTimeline";
import { TIMELINE_BASE_CHIPS, TIMELINE_ADMIN_CHIPS, normaliseTimelineItem } from "@/src/lib/customerTimeline";

// Shape as emitted by BE _audit_events_to_items + _normalise_existing_item (summary setdefault).
const PAY = {
  id: "aud-pk-1", kind: "payment", source_type: "payment", subject: "Invoice auto-charged",
  summary: "Invoice auto-charged · logged", body: "System charged $123.45 USD to card on file · pi_…234567",
  delivery_status: "logged", total: 123.45, url: "", ref_type: "audit_event", ref_id: "aud-pk-1",
  occurred_at: "2026-10-21T10:00:00+00:00", actor: null,
};
const NOTE = { id: "n1", kind: "note", summary: "Note", detail: { note_body: "Gate code 1234" }, occurred_at: "2026-10-20T00:00:00Z", actor: null };
const SMS = { id: "s1", kind: "sms", delivery_status: "delivered", body: "On my way!", occurred_at: "2026-10-19T00:00:00Z", actor: null };
const page = (items: any[]) => ({ items, page: 1, page_size: 20, total: items.length, total_pages: 1, next_before: null });

beforeEach(() => { mockRole = "admin"; mockGet.mockReset().mockResolvedValue(page([PAY, NOTE, SMS])); });

const mount = async (variant: "admin" | "portal" = "admin") => {
  const q = render(<CommunicationTimeline customerId="c1" variant={variant} />);
  await waitFor(() => q.getByTestId("communication-timeline-list"));
  return q;
};

it("P1 · payment is a BASE chip (not admin-only), placed after estimate like web _BASE_CHIPS", () => {
  expect(TIMELINE_BASE_CHIPS).toEqual(["all", "email", "sms", "invoice", "estimate", "payment"]);
  expect(TIMELINE_ADMIN_CHIPS).not.toContain("payment");
});

it.each([["admin", "admin"], ["customer", "portal"], ["technician", "admin"], ["manager", "admin"]] as const)(
  "P2 · %s sees the Payments chip", async (role, variant) => {
    mockRole = role;
    const q = render(<CommunicationTimeline customerId="c1" variant={variant} />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    const chip = await waitFor(() => q.getByTestId("communication-timeline-chip-payment"));
    expect(q.getByText("Payments")).toBeTruthy();
    expect(chip).toBeTruthy();
  });

it("P3 · admin-only chips stay gated: portal + technician do not see call/note", async () => {
  for (const [role, variant] of [["customer", "portal"], ["technician", "admin"]] as const) {
    mockRole = role;
    const q = render(<CommunicationTimeline customerId="c1" variant={variant} />);
    await waitFor(() => q.getByTestId("communication-timeline-chip-payment"));
    expect(q.queryByTestId("communication-timeline-chip-call")).toBeNull();
    expect(q.queryByTestId("communication-timeline-chip-note")).toBeNull();
    q.unmount();
  }
});

it("P4 · payment row: Payment pill + $123.45 money chip + summary headline + body; no link (url='')", async () => {
  const q = await mount();
  expect(q.getByTestId("timeline-pill-payment")).toBeTruthy();
  expect(q.getByText("Payment")).toBeTruthy();
  expect(q.getByTestId("timeline-money-aud-pk-1").props.children).toBe("$123.45");
  expect(q.getByTestId("timeline-summary-aud-pk-1").props.children).toBe("Invoice auto-charged · logged");
  expect(q.getByTestId("timeline-body-aud-pk-1").props.children).toBe("System charged $123.45 USD to card on file · pi_…234567");
  expect(q.queryByTestId("timeline-open-aud-pk-1")).toBeNull();
  expect(q.getByTestId("timeline-status-aud-pk-1")).toBeTruthy(); // doc-kind status (not message) → shown
});

it("P5 · money chip hidden when total is 0, missing, negative or non-numeric (web typeof number && > 0)", async () => {
  mockGet.mockResolvedValue(page([
    { ...PAY, id: "z0", total: 0 }, { ...PAY, id: "zm", total: undefined },
    { ...PAY, id: "zn", total: -5 }, { ...PAY, id: "zs", total: "12.00" },
  ]));
  const q = await mount();
  for (const id of ["z0", "zm", "zn", "zs"]) expect(q.queryByTestId(`timeline-money-${id}`)).toBeNull();
});

it("P6 · money formatting toFixed(2): 5 → $5.00, 0.5 → $0.50", async () => {
  mockGet.mockResolvedValue(page([{ ...PAY, id: "m5", total: 5 }, { ...PAY, id: "m05", total: 0.5 }]));
  const q = await mount();
  expect(q.getByTestId("timeline-money-m5").props.children).toBe("$5.00");
  expect(q.getByTestId("timeline-money-m05").props.children).toBe("$0.50");
});

it("P7 · money chip is kind-agnostic like web DefaultRow (invoice rows with numeric total also show it)", async () => {
  mockGet.mockResolvedValue(page([{ id: "i1", kind: "invoice", status: "draft", summary: "Invoice #INV-1 · draft", total: 420, url: "/invoices/i1", occurred_at: "2026-10-01T00:00:00Z" }]));
  const q = await mount();
  expect(q.getByTestId("timeline-money-i1").props.children).toBe("$420.00");
});

it("P8 · Payments chip → refetch with kind=payment", async () => {
  const q = await mount();
  fireEvent.press(q.getByTestId("communication-timeline-chip-payment"));
  await waitFor(() => expect(mockGet).toHaveBeenLastCalledWith("/customers/c1/timeline?page=1&page_size=20&kind=payment"));
});

it("P9 · regression: note + sms rows unchanged, no money chip on rows without total", async () => {
  const q = await mount();
  expect(q.getByTestId("timeline-pill-note")).toBeTruthy();
  expect(q.getByTestId("timeline-body-n1").props.children).toBe("Gate code 1234");
  expect(q.getByTestId("timeline-pill-sms")).toBeTruthy();
  expect(q.getByTestId("timeline-body-s1").props.children).toBe("On my way!");
  expect(q.queryByTestId("timeline-money-n1")).toBeNull();
  expect(q.queryByTestId("timeline-money-s1")).toBeNull();
});

it("P10 · adapter: total passes through when numeric, else 0", () => {
  expect(normaliseTimelineItem(PAY).total).toBe(123.45);
  expect(normaliseTimelineItem({ ...PAY, total: null }).total).toBe(0);
  expect(normaliseTimelineItem({ kind: "note" }).total).toBe(0);
  expect(normaliseTimelineItem(PAY).kind).toBe("payment");
});
