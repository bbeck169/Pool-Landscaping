/**
 * TD-96-g2-mobile · LeadLinkedQuotesPanel fetch gate on `linked_quotes_count`.
 * 0 → no GET, nothing rendered · > 0 → GET · absent → GET (back-compat;
 * deliberately NOT web's legacy `quotes_count` fallback, which ignores
 * reparented quotes).
 */
import React from "react";
import { render, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));

import LeadLinkedQuotesPanel from "@/src/components/leads/LeadLinkedQuotesPanel";

const URL = "/leads/L1/quotes?limit=10";
beforeEach(() => {
  mockGet.mockReset().mockResolvedValue({ items: [{ id: "q1", title: "Q", status: "draft", total: 5 }], total: 1, limit: 10 });
});

it("P1 · linked_quotes_count === 0 → no fetch, renders nothing", async () => {
  const q = render(<LeadLinkedQuotesPanel leadId="L1" linkedQuotesCount={0} />);
  await act(async () => {});
  expect(mockGet).not.toHaveBeenCalled();
  expect(q.queryByTestId("lead-linked-quotes-panel")).toBeNull();
});

it("P2 · linked_quotes_count > 0 → fetches and renders", async () => {
  const q = render(<LeadLinkedQuotesPanel leadId="L1" linkedQuotesCount={2} />);
  await waitFor(() => expect(q.getByTestId("lead-linked-quote-row-q1")).toBeTruthy());
  expect(mockGet).toHaveBeenCalledWith(URL);
});

it("P3 · field absent (undefined / null) → still fetches (back-compat, pre-TD-96-g2 payloads)", async () => {
  const a = render(<LeadLinkedQuotesPanel leadId="L1" />);
  await waitFor(() => expect(a.getByTestId("lead-linked-quotes-panel")).toBeTruthy());
  const b = render(<LeadLinkedQuotesPanel leadId="L1" linkedQuotesCount={null} />);
  await waitFor(() => expect(b.getByTestId("lead-linked-quotes-panel")).toBeTruthy());
  expect(mockGet).toHaveBeenCalledTimes(2);
});

it("P4 · count drops to 0 on refresh (quotes deleted) → panel clears without a new fetch", async () => {
  const q = render(<LeadLinkedQuotesPanel leadId="L1" linkedQuotesCount={1} />);
  await waitFor(() => expect(q.getByTestId("lead-linked-quotes-panel")).toBeTruthy());
  q.rerender(<LeadLinkedQuotesPanel leadId="L1" linkedQuotesCount={0} refreshKey={{}} />);
  await waitFor(() => expect(q.queryByTestId("lead-linked-quotes-panel")).toBeNull());
  expect(mockGet).toHaveBeenCalledTimes(1);
});
