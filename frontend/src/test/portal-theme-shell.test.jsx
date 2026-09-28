/**
 * DTP-1 · Feb-2026 — PortalThemeShell contract.
 *
 * Renders the shell + a child, asserts:
 *   * The shell root carries both ``dark`` and ``portal-dark``
 *     classes so the CSS-variable overrides in ``portal-dark.css``
 *     activate.
 *   * The children mount inside the shell.
 *   * ``data-testid="portal-theme-shell"`` is present.
 */
import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import PortalThemeShell from "@/components/portal/PortalThemeShell";

afterEach(() => cleanup());

describe("PortalThemeShell", () => {
  it("adds 'dark portal-dark' classes to its root", () => {
    render(
      <PortalThemeShell>
        <div data-testid="shell-child">child</div>
      </PortalThemeShell>,
    );
    const shell = screen.getByTestId("portal-theme-shell");
    expect(shell.className).toContain("dark");
    expect(shell.className).toContain("portal-dark");
  });

  it("renders its children inside the scope", () => {
    render(
      <PortalThemeShell>
        <div data-testid="shell-child">child</div>
      </PortalThemeShell>,
    );
    const shell = screen.getByTestId("portal-theme-shell");
    expect(shell.contains(screen.getByTestId("shell-child"))).toBe(true);
  });
});
