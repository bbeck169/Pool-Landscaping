/**
 * Feb 2026 · Customer Merge Phase 2 · MergeCustomersModal vitest.
 *
 * Coverage:
 *   1. Renders one side-by-side card per selected customer id.
 *   2. Detection banner scans on open + surfaces auto-detect result.
 *   3. Selecting a primary triggers a debounced dry-run POST.
 *   4. Merge button gated on (primary + preview + typed "MERGE").
 *   5. Successful merge → onDone called with the API result.
 *   6. Error path — modal stays open, ``onError`` fires.
 *   7. Cancel button — closes without side-effects.
 */
import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    del: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: mockApi }));

// Silence sonner in tests — the modal itself doesn't toast, but a
// stray import chain could pull it in.
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), message: vi.fn(),
  }),
}));

// eslint-disable-next-line import/first
import MergeCustomersModal from "@/components/customers/MergeCustomersModal";


const CUSTOMERS = [
  {
    id: "c-alice", name: "Alice Adams",
    email: "alice@example.com", phone: "+1 (623) 555-0100",
    address: "1 Main St", updated_at: "2026-02-20T00:00:00Z",
    tags: ["vip"],
  },
  {
    id: "c-alicia", name: "Alicia Adams",
    email: "alice@example.com", phone: "6235550100",
    address: "1 Main St", updated_at: "2026-02-01T00:00:00Z",
  },
];

const DRY_RUN_OK = {
  primary_id: "c-alice",
  secondary_ids: ["c-alicia"],
  fields_reconciled: { name: "Alice Adams" },
  empty_fields_filled: { phone: "+1 (623) 555-0100" },
  related_records_rewired: {
    jobs: 2, invoices: 1, payments: 0,
    service_reports: 3, estimates: 0, leads: 1,
  },
  audit_id: null,
  dry_run: true,
};


beforeEach(() => {
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});


function _mockDetectAndDryRun() {
  mockApi.post.mockImplementation((path, body) => {
    if (path.includes("detect-duplicates")) {
      return Promise.resolve({
        count: 1,
        duplicate_groups: [{
          match_type: "exact_email", confidence: "high", score: 1.0,
          customer_ids: ["c-alice", "c-alicia"],
          match_field_values: { email: "alice@example.com" },
        }],
      });
    }
    if (path.includes("/customers/merge")) {
      return Promise.resolve({
        ...DRY_RUN_OK, dry_run: !!body?.dry_run,
        audit_id: body?.dry_run ? null : "audit_abc123",
      });
    }
    return Promise.resolve({});
  });
}


describe("MergeCustomersModal", () => {
  it("01 · renders one card per selected customer", async () => {
    _mockDetectAndDryRun();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={() => {}} onDone={() => {}} />,
    );
    expect(screen.getByTestId("merge-card-c-alice")).toBeInTheDocument();
    expect(screen.getByTestId("merge-card-c-alicia")).toBeInTheDocument();
    expect(screen.getByTestId("merge-card-c-alice-name"))
      .toHaveTextContent("Alice Adams");
  });

  it("02 · detection banner scans on open + shows the matched group", async () => {
    _mockDetectAndDryRun();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={() => {}} onDone={() => {}} />,
    );
    // Scanning frame first.
    expect(screen.getByTestId("merge-detection-scanning")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("merge-detection-matched")).toBeInTheDocument();
    });
    expect(mockApi.post).toHaveBeenCalledWith(
      "/customers/detect-duplicates",
      { filters: { customer_ids: ["c-alice", "c-alicia"] } },
    );
  });

  it("03 · picking a primary triggers a debounced dry-run POST", async () => {
    _mockDetectAndDryRun();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={() => {}} onDone={() => {}} />,
    );
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    mockApi.post.mockClear();
    _mockDetectAndDryRun();

    fireEvent.click(screen.getByTestId("merge-card-c-alice-primary-radio"));
    // Debounce is 500ms — advance timers.
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() => {
      const calls = mockApi.post.mock.calls;
      const mergeCall = calls.find((c) => c[0].includes("/customers/merge"));
      expect(mergeCall).toBeTruthy();
      expect(mergeCall[1]).toMatchObject({
        primary_id: "c-alice",
        secondary_ids: ["c-alicia"],
        dry_run: true,
      });
    });
    // Preview surfaces the reconciled shape.
    await waitFor(() => {
      expect(screen.getByTestId("merge-preview")).toBeInTheDocument();
    });
  });

  it("04 · merge button disabled until primary + preview + typed confirmation", async () => {
    _mockDetectAndDryRun();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={() => {}} onDone={() => {}} />,
    );
    const btn = screen.getByTestId("merge-modal-confirm");
    expect(btn).toBeDisabled();
    // Pick primary — button still disabled (no preview yet + no confirm text).
    fireEvent.click(screen.getByTestId("merge-card-c-alice-primary-radio"));
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() =>
      expect(screen.getByTestId("merge-preview")).toBeInTheDocument());
    expect(btn).toBeDisabled();
    // Type wrong token — still disabled.
    fireEvent.change(screen.getByTestId("merge-modal-confirm-input"), {
      target: { value: "delete" },
    });
    expect(btn).toBeDisabled();
    // Type correct token — enabled.
    fireEvent.change(screen.getByTestId("merge-modal-confirm-input"), {
      target: { value: "MERGE" },
    });
    expect(btn).not.toBeDisabled();
  });

  it("05 · successful merge posts dry_run:false and calls onDone", async () => {
    _mockDetectAndDryRun();
    const onDone = vi.fn();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={() => {}} onDone={onDone} />,
    );
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("merge-card-c-alice-primary-radio"));
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() =>
      expect(screen.getByTestId("merge-preview")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("merge-modal-confirm-input"), {
      target: { value: "MERGE" },
    });
    fireEvent.click(screen.getByTestId("merge-modal-confirm"));
    await waitFor(() => {
      expect(onDone).toHaveBeenCalledTimes(1);
      const arg = onDone.mock.calls[0][0];
      expect(arg.audit_id).toBe("audit_abc123");
      expect(arg.dry_run).toBe(false);
      expect(arg.primary_name).toBe("Alice Adams");
      expect(arg.merged_count).toBe(1);
    });
    // The live-merge call went with dry_run: false.
    const liveCall = mockApi.post.mock.calls.find(
      (c) => c[0].includes("/customers/merge") && c[1]?.dry_run === false,
    );
    expect(liveCall).toBeTruthy();
    expect(liveCall[1]).toMatchObject({
      primary_id: "c-alice",
      secondary_ids: ["c-alicia"],
      dry_run: false,
    });
  });

  it("06 · error path keeps modal open + fires onError", async () => {
    mockApi.post.mockImplementation((path, body) => {
      if (path.includes("detect-duplicates")) {
        return Promise.resolve({ count: 0, duplicate_groups: [] });
      }
      if (path.includes("/customers/merge") && body?.dry_run) {
        return Promise.resolve(DRY_RUN_OK);
      }
      if (path.includes("/customers/merge")) {
        return Promise.reject(new Error("Backend exploded"));
      }
      return Promise.resolve({});
    });
    const onDone = vi.fn();
    const onError = vi.fn();
    const onClose = vi.fn();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={onClose} onDone={onDone}
                            onError={onError} />,
    );
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("merge-card-c-alice-primary-radio"));
    await act(async () => { vi.advanceTimersByTime(600); });
    await waitFor(() =>
      expect(screen.getByTestId("merge-preview")).toBeInTheDocument());
    fireEvent.change(screen.getByTestId("merge-modal-confirm-input"), {
      target: { value: "MERGE" },
    });
    fireEvent.click(screen.getByTestId("merge-modal-confirm"));
    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith("Backend exploded");
    });
    // Modal stayed open — inline error banner shows.
    expect(screen.getByTestId("merge-modal-error")).toBeInTheDocument();
    expect(screen.getByTestId("merge-modal-error"))
      .toHaveTextContent("Backend exploded");
    // ``onDone`` never called; ``onClose`` never called.
    expect(onDone).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("07 · Cancel button closes without merging", async () => {
    _mockDetectAndDryRun();
    const onClose = vi.fn();
    const onDone = vi.fn();
    render(
      <MergeCustomersModal open customers={CUSTOMERS}
                            onClose={onClose} onDone={onDone} />,
    );
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("merge-modal-cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    // No POST to /customers/merge with dry_run:false was fired.
    const liveMergeCall = mockApi.post.mock.calls.find(
      (c) => c[0].includes("/customers/merge") && c[1]?.dry_run === false,
    );
    expect(liveMergeCall).toBeFalsy();
  });
});
