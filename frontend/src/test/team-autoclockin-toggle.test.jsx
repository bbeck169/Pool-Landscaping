/**
 * Feb-2026 · Team page Auto Clock-In toggle.
 *
 * Covers:
 * * Non-technician row → inert dash (data-value="unavailable"), does
 *   not call PATCH on click.
 * * Technician row → clickable switch, PATCH ``/users/{id}`` fires
 *   with ``{auto_clockin_enabled: bool}``.
 * * Failure path reverts the optimistic flip.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const applied = vi.fn();

// Import the isolated toggle component. We test the component in
// isolation to keep the harness small; the parent wire-up is covered
// by the pytest suite for the PATCH endpoint.
import { TechAutoClockinToggle } from "@/pages/ops/OpsHub";

beforeEach(() => {
  applied.mockReset();
});

describe("TechAutoClockinToggle", () => {
  it("renders inert dash for non-technician rows", () => {
    render(
      <TechAutoClockinToggle
        user={{ id: "u1", role: "admin", name: "Admin One" }}
        editable={true}
        onChange={applied}
      />
    );
    const el = screen.getByTestId("team-row-autoclockin-toggle-u1");
    expect(el.getAttribute("data-value")).toBe("unavailable");
    fireEvent.click(el);
    expect(applied).not.toHaveBeenCalled();
  });

  it("technician row is clickable and calls onChange with next boolean", async () => {
    applied.mockResolvedValueOnce(undefined);
    render(
      <TechAutoClockinToggle
        user={{
          id: "t1",
          role: "technician",
          name: "Mike Rivera",
          auto_clockin_enabled: false,
        }}
        editable={true}
        onChange={applied}
      />
    );
    const el = screen.getByTestId("team-row-autoclockin-toggle-t1");
    expect(el.getAttribute("data-value")).toBe("off");
    fireEvent.click(el);
    await waitFor(() => expect(applied).toHaveBeenCalledWith(true));
    // Optimistic flip after resolved onChange.
    expect(el.getAttribute("data-value")).toBe("on");
  });

  it("reverts optimistic state when onChange rejects", async () => {
    applied.mockRejectedValueOnce(new Error("boom"));
    render(
      <TechAutoClockinToggle
        user={{
          id: "t2",
          role: "technician",
          name: "Tech Two",
          auto_clockin_enabled: true,
        }}
        editable={true}
        onChange={applied}
      />
    );
    const el = screen.getByTestId("team-row-autoclockin-toggle-t2");
    expect(el.getAttribute("data-value")).toBe("on");
    fireEvent.click(el);
    await waitFor(() => expect(applied).toHaveBeenCalledWith(false));
    // Revert to on because the PATCH failed.
    await waitFor(() =>
      expect(el.getAttribute("data-value")).toBe("on")
    );
  });

  it("editable=false renders switch as disabled (still shows current value)", () => {
    render(
      <TechAutoClockinToggle
        user={{
          id: "t3",
          role: "technician",
          name: "Tech Three",
          auto_clockin_enabled: true,
        }}
        editable={false}
        onChange={applied}
      />
    );
    const el = screen.getByTestId("team-row-autoclockin-toggle-t3");
    expect(el).toBeDisabled();
    fireEvent.click(el);
    expect(applied).not.toHaveBeenCalled();
  });
});
