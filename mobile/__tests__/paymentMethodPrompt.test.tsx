/**
 * paymentMethodPrompt.test.tsx — Phase K24
 *
 * Tests for PaymentMethodPromptModal + PaymentMethodPromptBanner.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Mocks ───────────────────────────────────────────── */

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush }),
}));

let mockIsImpersonating = false;
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ isImpersonating: mockIsImpersonating }),
}));

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
  },
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff",
    surfaceSecondary: "#f5f5f5",
    onSurface: "#111",
    muted: "#888",
    brand: "#2563EB",
    border: "#ddd",
    divider: "#eee",
    error: "#DC2626",
  },
  spacing: { sm: 4, md: 8, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { md: 8, lg: 12, pill: 100 },
  font: {
    regular: "System",
    medium: "System",
    semibold: "System",
    bold: "System",
  },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 18 },
}));

/* ── Import under test ───────────────────────────────── */

import PaymentMethodPromptModal, {
  _resetModalShown,
} from "@/src/components/portal/PaymentMethodPromptModal";
import PaymentMethodPromptBanner, {
  _resetBannerDismissed,
} from "@/src/components/portal/PaymentMethodPromptBanner";

/* ── Helpers ─────────────────────────────────────────── */

beforeEach(() => {
  mockIsImpersonating = false;
  mockGet.mockReset();
  mockPost.mockReset();
  mockPush.mockReset();
  _resetModalShown();
  _resetBannerDismissed();
});

/* ═══════════════════════════════════════════════════════
   Modal tests
   ═══════════════════════════════════════════════════════ */

describe("PaymentMethodPromptModal", () => {
  it("renders 'Add a payment method' modal when prompt_kind=missing", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
      expiring_cards: [],
    });

    const { findByTestId, getByText } = render(<PaymentMethodPromptModal />);
    const title = await findByTestId("pm-prompt-modal-title");
    expect(title).toBeTruthy();
    expect(getByText("Add a payment method")).toBeTruthy();
  });

  it("renders 'Update your card' modal with expiring card details", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "expiring",
      original_prompt_kind: "expiring",
      expiring_cards: [
        { brand: "Visa", last4: "4242", exp_month: 10, exp_year: 2026, days_until_expiry: 15 },
      ],
    });

    const { findByTestId, getByText } = render(<PaymentMethodPromptModal />);
    await findByTestId("pm-prompt-modal-title");
    expect(getByText("Update your card")).toBeTruthy();
    expect(getByText(/Visa ending 4242/)).toBeTruthy();
    expect(getByText(/15d left/)).toBeTruthy();
  });

  it("does NOT render when prompt_kind=none", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "none",
      original_prompt_kind: "none",
    });

    const { queryByTestId } = render(<PaymentMethodPromptModal />);
    // Wait for the effect to run
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(queryByTestId("pm-prompt-modal-card")).toBeNull();
  });

  it("navigates to payment-method on primary button press", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
    });

    const { findByTestId } = render(<PaymentMethodPromptModal />);
    const btn = await findByTestId("pm-prompt-primary-btn");
    fireEvent.press(btn);
    expect(mockPush).toHaveBeenCalledWith("/portal/payment-method");
  });

  it("POSTs snooze on 'Remind me tomorrow' press", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
    });
    mockPost.mockResolvedValue({});

    const { findByTestId } = render(<PaymentMethodPromptModal />);
    const btn = await findByTestId("pm-prompt-snooze-btn");
    await act(async () => { fireEvent.press(btn); });
    expect(mockPost).toHaveBeenCalledWith(
      "/portal/payment-method/prompt-snooze",
      {},
    );
  });

  it("does NOT render when impersonating (K13 interlock)", async () => {
    mockIsImpersonating = true;
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
    });

    const { queryByTestId } = render(<PaymentMethodPromptModal />);
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(queryByTestId("pm-prompt-modal-card")).toBeNull();
    // Should not even call the endpoint
    expect(mockGet).not.toHaveBeenCalled();
  });
});

/* ═══════════════════════════════════════════════════════
   Banner tests
   ═══════════════════════════════════════════════════════ */

describe("PaymentMethodPromptBanner", () => {
  it("renders missing banner from original_prompt_kind", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "none", // snoozed
      original_prompt_kind: "missing",
    });

    const { findByTestId, getByText } = render(<PaymentMethodPromptBanner />);
    const banner = await findByTestId("pm-prompt-banner");
    expect(banner).toBeTruthy();
    expect(getByText(/Add a payment method/)).toBeTruthy();
  });

  it("renders expiring banner with card details", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "expiring",
      original_prompt_kind: "expiring",
      expiring_cards: [
        { brand: "Mastercard", last4: "1234", exp_month: 11, exp_year: 2026, days_until_expiry: 5 },
      ],
    });

    const { findByTestId, getByText } = render(<PaymentMethodPromptBanner />);
    await findByTestId("pm-prompt-banner");
    expect(getByText(/Mastercard ending 1234/)).toBeTruthy();
  });

  it("navigates on tap", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
    });

    const { findByTestId } = render(<PaymentMethodPromptBanner />);
    const banner = await findByTestId("pm-prompt-banner");
    fireEvent.press(banner);
    expect(mockPush).toHaveBeenCalledWith("/portal/payment-method");
  });

  it("dismisses on × press (session-scoped)", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
    });

    const { findByTestId, queryByTestId } = render(<PaymentMethodPromptBanner />);
    const dismiss = await findByTestId("pm-prompt-banner-dismiss");
    fireEvent.press(dismiss);
    await waitFor(() => {
      expect(queryByTestId("pm-prompt-banner")).toBeNull();
    });
  });

  it("does NOT render when impersonating", async () => {
    mockIsImpersonating = true;
    mockGet.mockResolvedValue({
      prompt_kind: "missing",
      original_prompt_kind: "missing",
    });

    const { queryByTestId } = render(<PaymentMethodPromptBanner />);
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(queryByTestId("pm-prompt-banner")).toBeNull();
  });

  it("does NOT render when original_prompt_kind=none", async () => {
    mockGet.mockResolvedValue({
      prompt_kind: "none",
      original_prompt_kind: "none",
    });

    const { queryByTestId } = render(<PaymentMethodPromptBanner />);
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(queryByTestId("pm-prompt-banner")).toBeNull();
  });
});
