/**
 * M2 · Lead Profile parity (web Z1) — Requested Service card, created-at, address line.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: jest.fn(), patch: jest.fn() } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "L1" }),
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(cb, [cb]); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/customer", () => {
  const { Text } = require("react-native");
  return { PhoneLink: (p: any) => <Text testID={p.testID}>{p.phone}</Text>, AddressLink: (p: any) => <Text testID={p.testID}>{p.address}</Text> };
});
jest.mock("@/src/components/leads/LeadLinkedQuotesPanel", () => () => null);
jest.mock("@/src/components/leads/LeadCommunicationTimeline", () => () => null);
jest.mock("@/src/components/leads/LeadComposeSheet", () => () => null);
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

import LeadDetailScreen from "@/app/leads/[id]";
import { pickRequestedService } from "@/src/lib/leadRequestedService";

const LEAD = { id: "L1", name: "Widget Lead", status: "new", source: "website_form", phone: "6025550187",
  address: "22 Widget St, Peoria AZ 85383", created_at: "2026-08-26T17:03:40Z", timeline: [] };
const route = (lead: any, sub?: any) => (url: string) => {
  if (url === "/leads/L1") return Promise.resolve(lead);
  if (url === "/leads/L1/raw-submission") return sub ? Promise.resolve(sub) : Promise.reject(Object.assign(new Error("No linked submission"), { status: 404 }));
  return Promise.resolve([]);
};
beforeEach(() => mockGet.mockReset());

it("R1 · ladder: services_requested wins; message → inquiry → description fallbacks; all-strings join; empty → ''", () => {
  expect(pickRequestedService({ values: { message: "m", services_requested: "Pool opening" } })).toBe("Pool opening");
  expect(pickRequestedService({ values: { message: "  weekly service  ", inquiry: "i" } })).toBe("weekly service");
  expect(pickRequestedService({ values: { inquiry: "i", description: "d" } })).toBe("i");
  expect(pickRequestedService({ values: { description: "d" } })).toBe("d");
  expect(pickRequestedService({ values: { name: "N", zip: "85383", n: 3 } })).toBe("name: N\nzip: 85383");
  expect(pickRequestedService({ values: {} })).toBe("");
  expect(pickRequestedService(null)).toBe("");
});

it("R2 · lead with submission_id → fetches raw-submission and shows the verbatim text", async () => {
  mockGet.mockImplementation(route({ ...LEAD, meta: { submission_id: "S1" } }, { values: { name: "Widget Lead", message: "widget submission raw test" } }));
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-requested-service-text").props.children).toBe("widget submission raw test"));
  expect(mockGet).toHaveBeenCalledWith("/leads/L1/raw-submission");
});

it("R3 · legacy lead (no submission_id) → no fetch, card shows '—'", async () => {
  mockGet.mockImplementation(route(LEAD));
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-requested-service-empty")).toBeTruthy());
  expect(mockGet).not.toHaveBeenCalledWith("/leads/L1/raw-submission");
});

it("R4 · raw-submission 404 → '—', screen intact", async () => {
  mockGet.mockImplementation(route({ ...LEAD, meta: { submission_id: "S1" } }));
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-requested-service-empty")).toBeTruthy());
  expect(q.getByTestId("lead-name")).toBeTruthy();
});

it("R5 · header: address line under the name (service_address preferred) + 'Created <date>' in the source row", async () => {
  mockGet.mockImplementation(route({ ...LEAD, service_address: "1 Service Rd" }));
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-address-sub").props.children).toBe("1 Service Rd"));
  expect(q.getByTestId("lead-created-at").props.children.join("")).toContain(`Created ${new Date(LEAD.created_at).toLocaleDateString()}`);
  expect(q.getByTestId("lead-address").props.children).toBe("1 Service Rd"); // existing tappable address preserved
});

it("R6 · no address / no created_at → neither line renders", async () => {
  mockGet.mockImplementation(route({ ...LEAD, address: "", created_at: undefined }));
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-name")).toBeTruthy());
  expect(q.queryByTestId("lead-address-sub")).toBeNull();
  expect(q.queryByTestId("lead-created-at")).toBeNull();
});
