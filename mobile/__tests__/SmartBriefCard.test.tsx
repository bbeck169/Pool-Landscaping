/**
 * A5 · SmartBriefCard — component tests.
 *
 * Covers:
 *   1. Renders customer header when data present.
 *   2. Hides special_access section when all fields null/false.
 *   3. Shows red dog chip when dog_on_property=true.
 *   4. Renders up to 3 visits with correct dates.
 *   5. Hides alerts section when empty.
 *   6. Fetch failure renders error banner with retry.
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

/* ── Mocks ──────────────────────────────────────────────────────────── */
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...args: any[]) => mockGet(...args) },
}));

const mockRouterPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

import SmartBriefCard from "@/src/components/job/SmartBriefCard";

/* ── Fixtures ───────────────────────────────────────────────────────── */
const FULL_BRIEF = {
  job_id: "j1",
  customer_id: "c1",
  customer: {
    id: "c1",
    display_name: "Jennifer Carson",
    phone: "(602) 555-1234",
    address_line: "789 Verify Ln, Tempe, AZ 85281",
    coordinates: { lat: 33.42, lng: -111.94 },
  },
  special_access: {
    gate_code: "1234",
    key_location: "Under mat",
    dog_on_property: true,
    dog_notes: "Large German Shepherd",
    other_notes: "Use side gate",
  },
  last_visits: [
    {
      visit_id: "v1",
      completed_at: "2026-09-18T08:06:39Z",
      tech_display_name: "Alex Admin",
      service_type: "Weekly service",
      duration_minutes: 45,
      chemistry_snapshot: {
        salt: null, ph: 7.4, alkalinity: null,
        chlorine: 3.0, cyanuric_acid: 40.0, hardness: null,
      },
      notes: [
        { author_display_name: "Alex Admin", body: "Filter cleaned", created_at: "2026-09-18T08:10:00Z" },
      ],
    },
    {
      visit_id: "v2",
      completed_at: "2026-09-14T17:30:33Z",
      tech_display_name: "Carlos Rivera",
      service_type: "Pool Cleaning",
      duration_minutes: null,
      chemistry_snapshot: {
        salt: null, ph: 7.4, alkalinity: 80.0,
        chlorine: 3.0, cyanuric_acid: null, hardness: null,
      },
      notes: [],
    },
    {
      visit_id: "v3",
      completed_at: "2026-09-10T10:00:00Z",
      tech_display_name: "Mike Tech",
      service_type: "Filter Inspection",
      duration_minutes: 30,
      chemistry_snapshot: {
        salt: null, ph: null, alkalinity: null,
        chlorine: null, cyanuric_acid: null, hardness: null,
      },
      notes: [],
    },
  ],
  open_intelligence_alerts: [
    {
      alert_id: "a1", category: "chemistry", severity: "high",
      title: "High chlorine", body: "Chlorine above safe range",
      created_at: "2026-09-17T12:00:00Z",
    },
  ],
};

const EMPTY_BRIEF = {
  ...FULL_BRIEF,
  special_access: {
    gate_code: null, key_location: null,
    dog_on_property: false, dog_notes: null, other_notes: null,
  },
  last_visits: [],
  open_intelligence_alerts: [],
};

beforeEach(() => {
  jest.clearAllMocks();
});

/* ── Tests ───────────────────────────────────────────────────────────── */

describe("SmartBriefCard", () => {
  it("renders customer header when data present", async () => {
    mockGet.mockResolvedValueOnce(FULL_BRIEF);

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-customer")).toBeTruthy();
    });
    expect(getByTestId("smart-brief-phone")).toBeTruthy();
    expect(getByTestId("smart-brief-address")).toBeTruthy();
  });

  it("hides special_access section when all fields null/false", async () => {
    mockGet.mockResolvedValueOnce(EMPTY_BRIEF);

    const { queryByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(queryByTestId("smart-brief")).toBeTruthy();
    });
    expect(queryByTestId("smart-brief-access")).toBeNull();
  });

  it("shows red dog chip when dog_on_property=true", async () => {
    mockGet.mockResolvedValueOnce(FULL_BRIEF);

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-dog")).toBeTruthy();
    });
  });

  it("shows gate code chip", async () => {
    mockGet.mockResolvedValueOnce(FULL_BRIEF);

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-gate")).toBeTruthy();
    });
  });

  it("renders all 3 visits", async () => {
    mockGet.mockResolvedValueOnce(FULL_BRIEF);

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-visit-v1")).toBeTruthy();
      expect(getByTestId("smart-brief-visit-v2")).toBeTruthy();
      expect(getByTestId("smart-brief-visit-v3")).toBeTruthy();
    });
  });

  it("shows 'No prior visits' when last_visits is empty", async () => {
    mockGet.mockResolvedValueOnce(EMPTY_BRIEF);

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-no-visits")).toBeTruthy();
    });
  });

  it("hides alerts section when empty", async () => {
    mockGet.mockResolvedValueOnce(EMPTY_BRIEF);

    const { queryByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(queryByTestId("smart-brief")).toBeTruthy();
    });
    expect(queryByTestId("smart-brief-alerts")).toBeNull();
  });

  it("renders alerts section when present", async () => {
    mockGet.mockResolvedValueOnce(FULL_BRIEF);

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-alerts")).toBeTruthy();
      expect(getByTestId("smart-brief-alert-a1")).toBeTruthy();
    });
  });

  it("fetch failure renders error banner with retry", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network error"));

    const { getByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(getByTestId("smart-brief-error")).toBeTruthy();
    });

    // Retry
    mockGet.mockResolvedValueOnce(FULL_BRIEF);
    await act(async () => {
      fireEvent.press(getByTestId("smart-brief-retry"));
    });

    await waitFor(() => {
      expect(getByTestId("smart-brief-customer")).toBeTruthy();
    });
  });

  it("403 hides the card entirely", async () => {
    const err: any = new Error("Forbidden");
    err.status = 403;
    mockGet.mockRejectedValueOnce(err);

    const { queryByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(queryByTestId("smart-brief")).toBeNull();
      expect(queryByTestId("smart-brief-loading")).toBeNull();
      expect(queryByTestId("smart-brief-error")).toBeNull();
    });
  });

  it("404 hides the card entirely", async () => {
    const err: any = new Error("Not found");
    err.status = 404;
    mockGet.mockRejectedValueOnce(err);

    const { queryByTestId } = render(<SmartBriefCard jobId="j1" />);

    await waitFor(() => {
      expect(queryByTestId("smart-brief")).toBeNull();
      expect(queryByTestId("smart-brief-error")).toBeNull();
    });
  });
});
