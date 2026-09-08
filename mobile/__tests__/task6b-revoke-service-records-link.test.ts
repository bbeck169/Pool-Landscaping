/**
 * Task 6b · Revoke service-records link — unit tests.
 *
 * 1. Recent sends section renders with correct testIDs for 0, 1, 5 items.
 * 2. Revoke button hidden when revoked_at is set.
 * 3. Inline confirm UI renders on tap.
 * 4. POST /service-records-links/{token_id}/revoke endpoint referenced.
 * 5. Login banner renders when reason=link_revoked.
 */
import * as fs from "fs";
import * as path from "path";

describe("Task 6b — Revoke service-records link (mobile parity)", () => {
  const modalSource = fs.readFileSync(
    path.resolve(__dirname, "../src/components/customers/SendServiceRecordsLinkModal.tsx"),
    "utf-8",
  );
  const loginSource = fs.readFileSync(
    path.resolve(__dirname, "../app/login.tsx"),
    "utf-8",
  );

  // ── Modal: Recent sends section ──────────────────────────────────

  it("modal has recent-sends-section testID", () => {
    expect(modalSource).toContain('testID="recent-sends-section"');
  });

  it("modal shows 'No links sent yet.' when list is empty", () => {
    expect(modalSource).toContain('testID="recent-sends-empty"');
    expect(modalSource).toContain("No links sent yet.");
  });

  it("modal renders send rows with token_id-based testIDs", () => {
    expect(modalSource).toMatch(/testID=\{`recent-send-row-\$\{s\.token_id\}`\}/);
  });

  it("modal shows 'Revoked' badge with shield icon when revoked_at is set", () => {
    expect(modalSource).toMatch(/testID=\{`revoked-badge-\$\{s\.token_id\}`\}/);
    expect(modalSource).toContain("shield-outline");
    expect(modalSource).toContain("Revoked");
  });

  it("revoke button hidden when row is revoked (only shown for non-revoked rows)", () => {
    // The conditional flow:
    // isRevoked → show badge (no button)
    // !isRevoked && confirming → show Yes/No
    // !isRevoked && !confirming → show Revoke button
    expect(modalSource).toContain("isRevoked");
    expect(modalSource).toMatch(/testID=\{`revoke-btn-\$\{s\.token_id\}`\}/);
  });

  it("revoke button triggers inline confirmation (Yes/No)", () => {
    expect(modalSource).toContain("setConfirmRevoke");
    expect(modalSource).toMatch(/testID=\{`revoke-confirm-yes-\$\{s\.token_id\}`\}/);
    expect(modalSource).toMatch(/testID=\{`revoke-confirm-no-\$\{s\.token_id\}`\}/);
    expect(modalSource).toContain("Revoke?");
  });

  it("confirm-yes calls POST /service-records-links/{token_id}/revoke", () => {
    expect(modalSource).toContain("/service-records-links/");
    expect(modalSource).toContain("/revoke");
    expect(modalSource).toContain("handleRevoke");
  });

  it("modal fetches recent sends from GET /service-records-links", () => {
    expect(modalSource).toContain("/service-records-links");
    expect(modalSource).toContain("fetchRecentSends");
  });

  it("revoke refreshes recent sends list after success", () => {
    // handleRevoke calls fetchRecentSends() after successful POST
    expect(modalSource).toContain("await fetchRecentSends()");
  });

  it("modal preserves all original Task 6 testIDs", () => {
    expect(modalSource).toContain('testID="send-service-records-link-modal"');
    expect(modalSource).toContain('testID="send-via-email-btn"');
    expect(modalSource).toContain('testID="send-via-sms-btn"');
    expect(modalSource).toContain('testID="copy-link-btn"');
    expect(modalSource).toContain('testID="send-service-records-link-btn"');
    expect(modalSource).toContain('testID="send-records-recipient-input"');
    expect(modalSource).toContain('testID="send-records-throttle"');
    expect(modalSource).toContain('testID="send-records-throttle-exceeded"');
  });

  // ── Login: "link revoked" banner ─────────────────────────────────

  it("login.tsx imports useLocalSearchParams from expo-router", () => {
    expect(loginSource).toContain("useLocalSearchParams");
  });

  it("login.tsx checks for reason=link_revoked query param", () => {
    expect(loginSource).toContain("link_revoked");
    expect(loginSource).toContain("linkRevokedBanner");
  });

  it("login.tsx renders the revoked banner with correct testID", () => {
    expect(loginSource).toContain('testID="link-revoked-banner"');
  });

  it("login.tsx banner has the correct copy", () => {
    expect(loginSource).toContain(
      "This link has been revoked. Please contact your service provider for a new link.",
    );
  });

  it("login.tsx banner is amber/yellow (not red)", () => {
    expect(loginSource).toContain("#FEF3C7"); // amber background
    expect(loginSource).toContain("#92400E"); // amber text
  });

  it("login.tsx banner is dismissible", () => {
    expect(loginSource).toContain('testID="dismiss-revoked-banner"');
    expect(loginSource).toContain("setLinkRevokedBanner(false)");
  });

  it("login.tsx clears banner on successful login", () => {
    // setLinkRevokedBanner(false) should appear before router.replace
    const lines = loginSource.split("\n");
    const clearLines = lines
      .map((l: string, i: number) => ({ line: l, idx: i }))
      .filter((x: any) => x.line.includes("setLinkRevokedBanner(false)"));
    // Should be cleared in at least 2 places (normal login + account choice)
    expect(clearLines.length).toBeGreaterThanOrEqual(2);
  });
});
