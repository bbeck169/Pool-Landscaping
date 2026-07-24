/**
 * Feb-2026 · Login welcome caption — must show the tenant welcome
 * copy and NOT the old "Run your crew like clockwork." string.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({ api: { post: vi.fn(), get: vi.fn() } }));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: null, login: vi.fn() }),
}));

import Login from "@/pages/Login";

describe("Login page welcome caption", () => {
  it("shows the Pool & Landscaping of Vistancia LLC welcome headline", () => {
    render(<MemoryRouter><Login /></MemoryRouter>);
    const h = screen.getByTestId("login-welcome-headline");
    expect(h.textContent).toMatch(/Welcome to Pool & Landscaping of Vistancia LLC/i);
  });

  it("does NOT render the old clockwork copy", () => {
    render(<MemoryRouter><Login /></MemoryRouter>);
    expect(screen.queryByText(/Run your crew like clockwork/i)).toBeNull();
    expect(screen.queryByText(/dispatch technicians, send quotes/i)).toBeNull();
  });
});
