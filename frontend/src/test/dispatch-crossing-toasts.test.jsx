// Phase G5a · Feb-2026 — Dispatch crossing toasts (Vitest).
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

// Mock sonner BEFORE importing the hook — vi.mock is hoisted, so
// the mock factory must use vi.hoisted() to safely reference the
// spy object at module-init time.
const { _toast } = vi.hoisted(() => {
  return {
    _toast: {
      success: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
      info: vi.fn(),
    },
  };
});
vi.mock("sonner", () => ({ toast: _toast }));

import useCrossingToasts from "@/hooks/useCrossingToasts";

function Harness({ crossings, enabled = true }) {
  useCrossingToasts(crossings, { enabled });
  return null;
}

describe("useCrossingToasts · G5a dispatch integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("fires one toast per new crossing on first render", () => {
    const crossings = [
      { id: "c1", user_name: "Ana", geofence_name: "Depot",
        crossing: "enter", detected_at: "2026-02-14T09:00:00Z" },
      { id: "c2", user_name: "Ben", geofence_name: "No-go",
        crossing: "exit", detected_at: "2026-02-14T09:01:00Z" },
    ];
    render(<Harness crossings={crossings} />);
    expect(_toast.success).toHaveBeenCalledTimes(1);
    expect(_toast.warning).toHaveBeenCalledTimes(1);
    // Sonner "success" args: (title, {description, ...})
    const successArgs = _toast.success.mock.calls[0];
    expect(successArgs[0]).toBe("Ana");
    expect(successArgs[1].description).toMatch(/entered Depot/i);
  });

  it("dedupes crossings by id across re-renders", () => {
    const c1 = { id: "c1", user_name: "Ana", geofence_name: "Depot",
                 crossing: "enter", detected_at: "2026-02-14T09:00:00Z" };
    const { rerender } = render(<Harness crossings={[c1]} />);
    rerender(<Harness crossings={[c1]} />);
    rerender(<Harness crossings={[c1]} />);
    expect(_toast.success).toHaveBeenCalledTimes(1);
  });

  it("dedupes across mounts via localStorage", () => {
    const c1 = { id: "c1", user_name: "Ana", geofence_name: "Depot",
                 crossing: "enter", detected_at: "2026-02-14T09:00:00Z" };
    const first = render(<Harness crossings={[c1]} />);
    first.unmount();
    render(<Harness crossings={[c1]} />);
    expect(_toast.success).toHaveBeenCalledTimes(1);
  });

  it("no toast fires when disabled", () => {
    render(<Harness crossings={[
      { id: "c1", user_name: "Ana", geofence_name: "Depot",
        crossing: "enter", detected_at: "2026-02-14T09:00:00Z" },
    ]} enabled={false} />);
    expect(_toast.success).not.toHaveBeenCalled();
    expect(_toast.warning).not.toHaveBeenCalled();
  });

  it("handles empty/missing arrays gracefully", () => {
    render(<Harness crossings={[]} />);
    render(<Harness crossings={null} />);
    render(<Harness crossings={undefined} />);
    expect(_toast.success).not.toHaveBeenCalled();
    expect(_toast.warning).not.toHaveBeenCalled();
  });
});
