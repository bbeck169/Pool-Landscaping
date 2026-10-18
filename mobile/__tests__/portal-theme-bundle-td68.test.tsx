/**
 * TD-68 (web c782fd23a, dispatch label "TD-70") — portal theme bundle.
 * SR list, SR detail and the portal review-submit flow render their
 * content in a white rounded card on the deep-navy portal page bg
 * (`/portal/home` chassis #03002e).
 * TD-75 no-op guard: mobile SR list has NO free-text search input.
 */
import React from "react";
import { StyleSheet, ScrollView } from "react-native";
import { render, waitFor } from "@testing-library/react-native";

import { api } from "@/src/api";
import PortalServiceReports from "@/app/portal/service-reports";
import PortalServiceReportDetail from "@/app/portal/service-report/[id]";
import ReviewSubmit from "@/app/portal/review-submit";
import { PORTAL_PAGE_BG } from "@/src/components/portal/PortalPageShell";

jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn() },
  api_base: () => "https://be.test/api",
  getAuthToken: jest.fn(async () => "tok"),
}));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useFocusEffect: (cb: any) => React.useEffect(cb, [cb]),
    useLocalSearchParams: () => ({ id: "sr1", token: "rt1" }),
    useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  };
});
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/interactive", () => ({ ClickableAddress: () => null }));

const flat = (st: any) => StyleSheet.flatten(st) || {};
const WHITE_CARD = { backgroundColor: "#FFFFFF", borderRadius: 24, borderColor: "#E5E7EB" };

beforeEach(() => (api.get as jest.Mock).mockReset());

it("navy page constant matches portal home (#03002e)", () => {
  expect(PORTAL_PAGE_BG).toBe("#03002e");
});

it("SR list: list content is the white shell card on navy; no search input (TD-75)", async () => {
  (api.get as jest.Mock).mockResolvedValue([
    { id: "r1", job_title: "Weekly Pool", template: "pool", submitted_at: "2026-08-27T10:00:00Z" },
  ]);
  const q = render(<PortalServiceReports />);
  const list = await waitFor(() => q.getByTestId("portal-service-reports-grouped"));
  expect(flat(list.props.contentContainerStyle)).toMatchObject(WHITE_CARD);
  expect(flat(q.toJSON() && (q.toJSON() as any).props.style).backgroundColor).toBe("#03002e");
  expect(q.UNSAFE_queryAllByProps({ placeholder: "Search notes, name, address…" })).toHaveLength(0);
});

it("SR list: paginated {items} payload renders rows (web shape parity)", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    items: [{ id: "r9", job_title: "Weekly service", submitted_at: "2026-09-18T08:06:39Z" }],
    page: 1, page_size: 20, total: 1, total_pages: 1,
  });
  const q = render(<PortalServiceReports />);
  await waitFor(() => expect(q.getByTestId("portal-service-reports-item-r9")).toBeTruthy());
});

it("SR list: empty state is wrapped in the shell card", async () => {
  (api.get as jest.Mock).mockResolvedValue([]);
  const q = render(<PortalServiceReports />);
  await waitFor(() => q.getByTestId("portal-service-reports-empty"));
  expect(flat(q.getByTestId("portal-page-shell-card").props.style)).toMatchObject(WHITE_CARD);
});

it("SR detail: content inside the shell card on navy", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    id: "sr1", template: "pool", submitted_at: "2026-08-27T10:00:00Z", job: { title: "Pool" },
  });
  const q = render(<PortalServiceReportDetail />);
  const card = await waitFor(() => q.getByTestId("portal-page-shell-card"));
  expect(flat(card.props.style)).toMatchObject(WHITE_CARD);
  expect(flat((q.toJSON() as any).props.style).backgroundColor).toBe("#03002e");
});

it("Review submit (portal Reviews parallel): form sits in the white card on navy", async () => {
  (api.get as jest.Mock).mockResolvedValue({ company_name: "Aqua", tech_name: "Mike" });
  const q = render(<ReviewSubmit />);
  const root = await waitFor(() => q.getByTestId("review-submit-form"));
  expect(flat(root.props.style).backgroundColor).toBe("#03002e");
  const scroll = root.findByType(ScrollView);
  expect(flat(scroll.props.contentContainerStyle)).toMatchObject(WHITE_CARD);
});

it("Review submit: standalone state (expired) renders as a white card", async () => {
  (api.get as jest.Mock).mockResolvedValue({ expired: true });
  const q = render(<ReviewSubmit />);
  const root = await waitFor(() => q.getByTestId("review-submit-expired"));
  expect(flat(root.props.children.props.style)).toMatchObject(WHITE_CARD);
});
