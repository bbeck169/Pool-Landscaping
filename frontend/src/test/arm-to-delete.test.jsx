/**
 * ArmToDelete · Feb-2026 · state-machine + accessibility tests.
 *
 * Covers:
 *   1. Non-catastrophic path (``count < threshold``): single-click
 *      Delete N button, one click fires ``onConfirm``.
 *   2. Catastrophic path (``count >= threshold``):
 *        - "Arm delete" label + disabled during the cooldown.
 *        - Cooldown label surfaces integer seconds via
 *          Math.ceil(remainingMs / 1000).
 *        - Button enables + shows "Delete N" once cooldown hits 0.
 *        - Second click fires ``onConfirm``.
 *        - ``onConfirm`` rejection returns to ``armed`` (not idle).
 *        - Escape cancels back to ``idle`` at any pre-execute state.
 *   3. Data-testid + data-state contract for external drivers.
 *   4. aria-live announcement text for state transitions.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import ArmToDelete from "@/components/ui/ArmToDelete";


describe("ArmToDelete · non-catastrophic (single-click) path", () => {
  it("renders the `Delete N` label when count is below the threshold", () => {
    render(<ArmToDelete count={5} onConfirm={() => {}} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    expect(btn.textContent).toContain("Delete 5");
    expect(btn.getAttribute("data-catastrophic")).toBe("0");
    expect(btn.disabled).toBe(false);
  });

  it("clicking once calls onConfirm exactly once", async () => {
    const spy = vi.fn().mockResolvedValue(undefined);
    render(<ArmToDelete count={5} onConfirm={spy} />);
    fireEvent.click(screen.getByTestId("arm-to-delete-btn"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
  });

  it("`disabled` prop from the parent disables the button", () => {
    render(<ArmToDelete count={5} onConfirm={() => {}} disabled />);
    expect(screen.getByTestId("arm-to-delete-btn").disabled).toBe(true);
  });

  it("uses the custom `label` prop for the button copy", () => {
    render(<ArmToDelete count={7} onConfirm={() => {}} label="Void" />);
    expect(screen.getByTestId("arm-to-delete-btn").textContent).toContain("Void 7");
  });
});


describe("ArmToDelete · catastrophic (arm-and-execute) path", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("renders `Arm delete` at rest for count >= threshold", () => {
    render(<ArmToDelete count={750} onConfirm={() => {}} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    expect(btn.textContent).toContain("Arm delete");
    expect(btn.getAttribute("data-catastrophic")).toBe("1");
    expect(btn.getAttribute("data-state")).toBe("idle");
    expect(btn.disabled).toBe(false);
  });

  it("first click arms + starts the cooldown; button disables and "
      + "surfaces `Confirm again in 3s`", () => {
    render(<ArmToDelete count={750} onConfirm={() => {}} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    act(() => { fireEvent.click(btn); });
    expect(btn.getAttribute("data-state")).toBe("arming");
    expect(btn.getAttribute("data-cooldown")).toBe("3");
    expect(btn.textContent).toContain("Confirm again in 3s");
    expect(btn.disabled).toBe(true);
    // Click during cooldown must NOT fire.
    const spy = vi.fn();
    render(<ArmToDelete count={750} onConfirm={spy} cooldownMs={3000} />);
    // No opConfirm call from this second render's arm click either.
    expect(spy).not.toHaveBeenCalled();
  });

  it("cooldown label counts down every second", () => {
    render(<ArmToDelete count={600} onConfirm={() => {}} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    act(() => { fireEvent.click(btn); });
    expect(btn.textContent).toContain("Confirm again in 3s");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(btn.textContent).toContain("Confirm again in 2s");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(btn.textContent).toContain("Confirm again in 1s");
  });

  it("after cooldown, button enables with `Delete N` label", () => {
    render(<ArmToDelete count={600} onConfirm={() => {}} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    act(() => { fireEvent.click(btn); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(btn.getAttribute("data-state")).toBe("armed");
    expect(btn.textContent).toContain("Delete 600");
    expect(btn.disabled).toBe(false);
  });

  it("second click after cooldown fires onConfirm exactly once", async () => {
    const spy = vi.fn().mockResolvedValue(undefined);
    render(<ArmToDelete count={600} onConfirm={spy} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    act(() => { fireEvent.click(btn); });
    act(() => { vi.advanceTimersByTime(3000); });
    act(() => { fireEvent.click(btn); });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("Escape at any pre-execute state resets to idle", () => {
    render(<ArmToDelete count={600} onConfirm={() => {}} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    // Arm.
    act(() => { fireEvent.click(btn); });
    expect(btn.getAttribute("data-state")).toBe("arming");
    // Escape during cooldown.
    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(btn.getAttribute("data-state")).toBe("idle");
    expect(btn.textContent).toContain("Arm delete");
    // Re-arm + advance to armed + Escape again.
    act(() => { fireEvent.click(btn); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(btn.getAttribute("data-state")).toBe("armed");
    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(btn.getAttribute("data-state")).toBe("idle");
  });
});


describe("ArmToDelete · onConfirm rejection returns to `armed`", () => {
  it("catastrophic path — rejection re-enables the button in armed state", async () => {
    vi.useFakeTimers();
    const err = new Error("boom");
    const onErr = vi.fn();
    const spy = vi.fn().mockRejectedValue(err);
    render(<ArmToDelete count={600} onConfirm={spy} onError={onErr} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    act(() => { fireEvent.click(btn); });         // arm
    act(() => { vi.advanceTimersByTime(3000); }); // cooldown done
    act(() => { fireEvent.click(btn); });          // execute
    vi.useRealTimers();
    await waitFor(() => expect(spy).toHaveBeenCalled());
    await waitFor(() => expect(btn.getAttribute("data-state")).toBe("armed"));
    expect(btn.textContent).toContain("Delete 600");
    expect(btn.disabled).toBe(false);
    expect(onErr).toHaveBeenCalledWith(err);
  });

  it("non-catastrophic path — rejection returns to idle", async () => {
    const spy = vi.fn().mockRejectedValue(new Error("boom"));
    render(<ArmToDelete count={5} onConfirm={spy} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    fireEvent.click(btn);
    await waitFor(() => expect(btn.getAttribute("data-state")).toBe("idle"));
    expect(btn.disabled).toBe(false);
  });
});


describe("ArmToDelete · accessibility announcements", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("aria-live region announces the armed + ready + in-progress states", async () => {
    let resolveFn;
    const spy = vi.fn(() => new Promise((r) => { resolveFn = r; }));
    render(<ArmToDelete count={600} onConfirm={spy} cooldownMs={3000} />);
    const btn = screen.getByTestId("arm-to-delete-btn");
    const region = screen.getByTestId("arm-to-delete-announce");
    // Idle — empty announcement.
    expect(region.textContent).toBe("");
    // Arm.
    act(() => { fireEvent.click(btn); });
    expect(region.textContent).toContain("Delete armed");
    expect(region.textContent).toContain("3 seconds");
    // Ready.
    act(() => { vi.advanceTimersByTime(3000); });
    expect(region.textContent).toContain("ready");
    // Executing.
    act(() => { fireEvent.click(btn); });
    expect(region.textContent).toContain("Delete in progress");
    // Cleanup.
    resolveFn && resolveFn();
  });
});


describe("ArmToDelete · testIdPrefix contract for external drivers", () => {
  it("respects a custom testIdPrefix for both button + announce", () => {
    render(<ArmToDelete count={5} onConfirm={() => {}} testIdPrefix="custom-prefix" />);
    expect(screen.getByTestId("custom-prefix-btn")).toBeTruthy();
    expect(screen.getByTestId("custom-prefix-announce")).toBeTruthy();
  });
});
