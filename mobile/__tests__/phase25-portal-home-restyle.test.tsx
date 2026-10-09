/**
 * Phase 25 · Portal home — dark-card restyle + dynamic tile colors
 * (mobile parity with web e2a0d8a2e · Phase 23 and 3a738ff11 · Phase 24).
 *
 *   3. Page bg #03002e; Concierge / Referral / Business-card sections and
 *      the KPI stat tiles share the dark chassis (#03002e + 1px #1E293B +
 *      radius 12 ≈ web rounded-xl)
 *   4. Each section carries a distinct accent (blue / green / navy)
 *   5. Past Due tile → #7F1D1D when > 0, default chassis when 0 / null
 *   6. Credit tile → #064E3B when > 0, default chassis when 0
 *   7. KPI tiles carry a STATIC soft white glow; Quick Action tiles glow
 *      on press (onPressIn) and clear on release
 *   8. Text flips to white on dynamic bgs
 */
import React from "react";
import { StyleSheet } from "react-native";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

import { colors } from "@/src/theme";

// Locked web hex values (Phase 23 / 24) — verbatim.
const PORTAL_DARK = "#03002e";
const PORTAL_BORDER = "#1E293B";

let mockDashboard: any = {};
let mockCreditCents = 0;
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async (url: string) => {
      if (url.startsWith("/customer-portal/credits/balance")) return { balance_cents: mockCreditCents };
      if (url.includes("ai-employees") || url.includes("/ai/")) return [{ id: "e1", key: "billy", name: "Billy", role: "Billing assistant" }];
      if (url.includes("config") || url.includes("settings")) return {};
      return mockDashboard;
    }),
  },
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "cu1", role: "customer", name: "Cust" }, logout: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
}));
jest.mock("@expo/vector-icons", () => {
  const { View } = require("react-native");
  return { Ionicons: (p: any) => <View testID={p.testID} accessibilityHint={p.color} /> };
});
jest.mock("expo-image", () => ({ Image: () => null }));
jest.mock("expo-linear-gradient", () => {
  const { View } = require("react-native");
  return { LinearGradient: ({ children, testID }: any) => <View testID={testID}>{children}</View> };
});
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => "1"), setItem: jest.fn(async () => {}), removeItem: jest.fn(async () => {}),
}));
jest.mock("@/src/components/widgets", () => ({ Header: () => null, NotificationBell: () => null }));
jest.mock("@/src/components/Tour", () => ({ __esModule: true, default: () => null }));
jest.mock("@/components/common/TechAvatar", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/personas/PersonaAvatar", () => ({ PersonaAvatar: () => null }));
jest.mock("@/src/components/portal/PaymentMethodPromptModal", () => ({ __esModule: true, default: () => null }));

import PortalHome from "@/app/portal/home";

const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
const BASE_DASH = { outstanding: 120, past_due: 0, active_jobs: 1, completed_jobs: 3, next_service: null, last_visit: null };

async function mount(dash: any = {}, creditCents = 0) {
  mockDashboard = { ...BASE_DASH, ...dash };
  mockCreditCents = creditCents;
  const r = render(<PortalHome />);
  await waitFor(() => r.getByTestId("portal-stat-circles"));
  return r;
}

describe("Phase 25 · portal home dark chassis (web Phase 23)", () => {
  it("3a. page background is dark navy #03002e", async () => {
    const r = await mount();
    expect(flat(r.getByTestId("portal-home-root")).backgroundColor).toBe(PORTAL_DARK);
  });

  it("3. KPI tiles + Concierge / Referral / Business card share the dark chassis", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("portal-ai-section"));
    for (const id of ["portal-stat-balance-tile", "portal-stat-past-due-tile", "portal-stat-credit-tile",
      "portal-ai-section", "portal-referral-section", "portal-card-business"]) {
      const st = flat(r.getByTestId(id));
      expect([id, st.backgroundColor]).toEqual([id, PORTAL_DARK]);
      expect([id, st.borderColor]).toEqual([id, PORTAL_BORDER]);
      expect([id, st.borderWidth]).toEqual([id, 1]);
      expect([id, st.borderRadius]).toEqual([id, 12]);
    }
  });

  it("3b. Quick Action tiles are rounded dark tiles too; text is light on navy", async () => {
    const r = await mount();
    const qa = r.getAllByTestId(/^portal-card-(?!business)/)[0];
    const st = flat(qa);
    expect(st.backgroundColor).toBe(PORTAL_DARK);
    expect(st.borderColor).toBe(PORTAL_BORDER);
    expect(st.borderRadius).toBe(12);
    expect(flat(r.getByTestId("portal-stat-balance")).color).toBe("#FFFFFF");
  });

  it("4. distinct accents: Concierge blue, Referral green, Business card navy", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("portal-ai-section-accent"));
    const blue = r.getByTestId("portal-ai-section-accent").props.accessibilityHint;
    const green = r.getByTestId("portal-referral-section-accent").props.accessibilityHint;
    const navy = flat(r.getByTestId("portal-card-business-accent")).backgroundColor;
    expect(blue).toBe(colors.brand);
    expect(green).toBe(colors.success);
    expect(navy).toBe("#1E3A8A");
    expect(new Set([blue, green, navy]).size).toBe(3);
    // Referral CTA flips to the green accent (was white-on-gradient).
    expect(flat(r.getByTestId("portal-referral-cta")).backgroundColor).toBe(colors.success);
  });
});

describe("Phase 25 · dynamic stat-tile colors + contrast", () => {
  it("5/8. Past Due > 0 → #7F1D1D with white text", async () => {
    const r = await mount({ past_due: 45 });
    expect(flat(r.getByTestId("portal-stat-past-due-tile")).backgroundColor).toBe("#7F1D1D");
    expect(flat(r.getByTestId("portal-stat-past-due")).color).toBe("#FFFFFF");
    expect(flat(r.getByTestId("portal-stat-past-due-label")).color).toBe("#FFFFFF");
  });

  it.each([0, null])("5. Past Due = %p → default navy chassis", async (v) => {
    const r = await mount({ past_due: v });
    expect(flat(r.getByTestId("portal-stat-past-due-tile")).backgroundColor).toBe(PORTAL_DARK);
    expect(flat(r.getByTestId("portal-stat-past-due-tile")).borderColor).toBe(PORTAL_BORDER);
  });

  it("6/8. Credit > 0 → #064E3B with white text", async () => {
    const r = await mount({}, 5500);
    await waitFor(() => expect(flat(r.getByTestId("portal-stat-credit-tile")).backgroundColor).toBe("#064E3B"));
    expect(flat(r.getByTestId("portal-stat-credit")).color).toBe("#FFFFFF");
    expect(flat(r.getByTestId("portal-stat-credit-label")).color).toBe("#FFFFFF");
  });

  it("6. Credit = 0 → default navy chassis", async () => {
    const r = await mount({}, 0);
    expect(flat(r.getByTestId("portal-stat-credit-tile")).backgroundColor).toBe(PORTAL_DARK);
    expect(flat(r.getByTestId("portal-stat-credit-tile")).borderColor).toBe(PORTAL_BORDER);
  });

  it("Balance Due tile chassis is untouched by dynamic colors", async () => {
    const r = await mount({ past_due: 99 }, 100);
    expect(flat(r.getByTestId("portal-stat-balance-tile")).backgroundColor).toBe(PORTAL_DARK);
  });
});

describe("Phase 25 · glow (web Phase 24 hover → mobile)", () => {
  it.each([[0, 0], [45, 5500]])("7a. every KPI tile carries the static soft white glow (past_due=%p, credit=%p)", async (pd, cr) => {
    const r = await mount({ past_due: pd }, cr);
    if (cr) await waitFor(() => expect(flat(r.getByTestId("portal-stat-credit-tile")).backgroundColor).toBe("#064E3B"));
    for (const id of ["portal-stat-balance-tile", "portal-stat-past-due-tile", "portal-stat-credit-tile"]) {
      const st = flat(r.getByTestId(id));
      expect([id, st.shadowColor, st.shadowOpacity, st.shadowRadius, st.elevation])
        .toEqual([id, "#FFFFFF", 0.6, 20, 8]);
    }
  });

  it("7. pressIn applies the white halo, pressOut clears it", async () => {
    const r = await mount();
    const tiles = r.getAllByTestId(/^portal-card-(?!business)/);
    expect(tiles.length).toBeGreaterThan(0);
    const t = tiles[0];
    expect(flat(t).shadowColor).toBeUndefined();
    fireEvent(t, "pressIn");
    const pressed = flat(r.getByTestId(t.props.testID));
    expect(pressed.shadowColor).toBe("#FFFFFF");
    expect(pressed.shadowOpacity).toBe(0.6);
    expect(pressed.shadowRadius).toBe(20);
    fireEvent(r.getByTestId(t.props.testID), "pressOut");
    expect(flat(r.getByTestId(t.props.testID)).shadowColor).toBeUndefined();
  });

  it("KPI glow is static (no press handlers on stat tiles)", async () => {
    const r = await mount({ past_due: 10 });
    expect(r.getByTestId("portal-stat-past-due-tile").props.onPressIn).toBeUndefined();
  });
});
