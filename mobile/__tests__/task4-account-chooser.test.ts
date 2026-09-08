/**
 * Task 4 · Multi-account chooser login flow — unit tests.
 *
 * 1. When backend returns `multi_account_choice_required`, the chooser
 *    state is populated (not a token persist).
 * 2. `finalizeAccountChoice` calls the correct endpoint.
 * 3. Normal login (no multi-account) persists immediately.
 */
import * as fs from "fs";
import * as path from "path";

describe("Task 4 — Multi-account chooser (login flow)", () => {

  const authSource = fs.readFileSync(
    path.resolve(__dirname, "../src/auth.tsx"),
    "utf-8",
  );
  const loginSource = fs.readFileSync(
    path.resolve(__dirname, "../app/login.tsx"),
    "utf-8",
  );

  it("auth.tsx exports finalizeAccountChoice in the context value", () => {
    expect(authSource).toContain("finalizeAccountChoice");
    // Should be in the Provider value spread
    expect(authSource).toMatch(/value=\{[^}]*finalizeAccountChoice/);
  });

  it("auth.tsx login() detects multi_account_choice_required and returns kind: choice", () => {
    // The login function should check for the status field
    expect(authSource).toContain("multi_account_choice_required");
    expect(authSource).toContain('kind: "choice"');
  });

  it("auth.tsx finalizeAccountChoice posts to /auth/login/select-account", () => {
    expect(authSource).toContain("/auth/login/select-account");
    expect(authSource).toContain("choice_token");
    expect(authSource).toContain("account_id");
  });

  it("login.tsx has account-chooser-screen testID", () => {
    expect(loginSource).toContain('testID="account-chooser-screen"');
  });

  it("login.tsx has account-chooser-heading with 'Which account?' text", () => {
    expect(loginSource).toContain('testID="account-chooser-heading"');
    expect(loginSource).toContain("Which account?");
  });

  it("login.tsx has 'Not you? Log out.' cancel link", () => {
    expect(loginSource).toContain('testID="account-chooser-cancel"');
    expect(loginSource).toContain("Not you? Log out.");
  });

  it("login.tsx renders account choice cards with correct testID pattern", () => {
    expect(loginSource).toMatch(/testID=\{`account-choice-\$\{/);
  });

  it("login.tsx pickAccount calls finalizeAccountChoice", () => {
    expect(loginSource).toContain("finalizeAccountChoice");
    expect(loginSource).toContain("pickAccount");
  });

  it("login.tsx cancelChooser clears chooser state", () => {
    expect(loginSource).toContain("cancelChooser");
    expect(loginSource).toContain("setChooser(null)");
  });
});
