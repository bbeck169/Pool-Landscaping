/**
 * Phase NAV-RIGHT-JUSTIFY · Feb-2026 — wide-branch right-cluster
 * is pushed to the far right via ``ml-auto`` on its container.
 *
 * Guards the following invariants on the wide (>=768px) branch:
 *
 *   1. The right-cluster container carries ``ml-auto`` so the
 *      Add Job / Add Customer / Mic / Settings / Bell / Sign Out
 *      group sits at the far right rather than immediately after
 *      the last nav category.
 *   2. The 6 buttons listed in the dispatch all render inside the
 *      right-cluster container.
 *   3. The narrow branch keeps its ``justify-between`` layout
 *      (hamburger left, right-cluster right) — unchanged.
 *   4. The right-cluster still carries ``shrink-0`` so a long
 *      nav category list that triggers ``overflow-x-auto`` on the
 *      parent does not squeeze the cluster.
 *   5. Cluster order within the right-cluster is preserved
 *      byte-for-byte: SettingsSprocket → NotificationBell →
 *      SignOutButton (ending with SignOut as the far-right
 *      control, per ``admin-topbar-cleanup-cluster-reorder``).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const TOPBAR = readFileSync(
  resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);


describe("AdminTopBar wide-branch right-justify (Phase NAV-RIGHT-JUSTIFY)",
         () => {
  it("right-cluster container on the wide branch carries ml-auto",
     () => {
    const wideWrapIdx = TOPBAR.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    expect(wideWrapIdx).toBeGreaterThan(-1);
    // Scope: everything between the wide-wrap testid and the next
    // closing ``</div>`` pair.  We only care about the first
    // right-cluster inside this branch.
    const wideWrapSlice = TOPBAR.slice(wideWrapIdx);
    const clusterIdx = wideWrapSlice.indexOf(
      'data-testid="admin-topbar-right-cluster"',
    );
    expect(clusterIdx).toBeGreaterThan(-1);
    // Grab the opening ``<div ...>`` whose attributes end at
    // the testid we just found.
    const openTagStart = wideWrapSlice.lastIndexOf(
      "<div", clusterIdx,
    );
    const openTag = wideWrapSlice.slice(openTagStart, clusterIdx + 50);
    expect(openTag).toMatch(/ml-auto/);
  });

  it("right-cluster retains shrink-0 so overflow doesn't squeeze it",
     () => {
    const wideWrapIdx = TOPBAR.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    const wideWrapSlice = TOPBAR.slice(wideWrapIdx);
    const clusterIdx = wideWrapSlice.indexOf(
      'data-testid="admin-topbar-right-cluster"',
    );
    const openTagStart = wideWrapSlice.lastIndexOf("<div", clusterIdx);
    const openTag = wideWrapSlice.slice(openTagStart, clusterIdx + 50);
    expect(openTag).toMatch(/shrink-0/);
  });

  it("narrow-branch wrap still uses justify-between (unchanged)",
     () => {
    const narrowIdx = TOPBAR.indexOf(
      'data-testid="admin-topbar-narrow-wrap"',
    );
    expect(narrowIdx).toBeGreaterThan(-1);
    const openTagStart = TOPBAR.lastIndexOf("<div", narrowIdx);
    const openTag = TOPBAR.slice(openTagStart, narrowIdx);
    expect(openTag).toMatch(/justify-between/);
  });

  it("all 6 action buttons live inside the wide right-cluster",
     () => {
    const wideWrapIdx = TOPBAR.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    const wideWrapSlice = TOPBAR.slice(wideWrapIdx);
    const clusterIdx = wideWrapSlice.indexOf(
      'data-testid="admin-topbar-right-cluster"',
    );
    // Find the matching closing </div> for the cluster by walking
    // from clusterIdx until depth returns to -1.  Simpler: slice
    // forward 2000 chars and assert all 6 names appear.  The wide
    // right-cluster isn't that long in practice.
    const clusterSlice = wideWrapSlice.slice(clusterIdx, clusterIdx + 2000);
    for (const name of [
      "<AddJobButton",
      "<AddCustomerButton",
      "<MicToggleButton",
      "<SettingsSprocket",
      "<NotificationBell",
      "<SignOutButton",
    ]) {
      expect(clusterSlice).toContain(name);
    }
  });

  it("cluster order preserves Settings → NotificationBell → SignOut",
     () => {
    const wideWrapIdx = TOPBAR.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    const wideWrapSlice = TOPBAR.slice(wideWrapIdx);
    const clusterIdx = wideWrapSlice.indexOf(
      'data-testid="admin-topbar-right-cluster"',
    );
    const clusterSlice = wideWrapSlice.slice(clusterIdx, clusterIdx + 2000);
    const settingsPos = clusterSlice.indexOf("<SettingsSprocket");
    const bellPos = clusterSlice.indexOf("<NotificationBell");
    const signOutPos = clusterSlice.indexOf("<SignOutButton");
    expect(settingsPos).toBeGreaterThan(-1);
    expect(bellPos).toBeGreaterThan(settingsPos);
    expect(signOutPos).toBeGreaterThan(bellPos);
  });

  it("Add Job button renders BEFORE Add Customer in the wide cluster",
     () => {
    const wideWrapIdx = TOPBAR.indexOf(
      'data-testid="admin-topbar-wide-wrap"',
    );
    const wideWrapSlice = TOPBAR.slice(wideWrapIdx);
    const clusterIdx = wideWrapSlice.indexOf(
      'data-testid="admin-topbar-right-cluster"',
    );
    const clusterSlice = wideWrapSlice.slice(clusterIdx, clusterIdx + 2000);
    const jobPos = clusterSlice.indexOf("<AddJobButton");
    const custPos = clusterSlice.indexOf("<AddCustomerButton");
    expect(jobPos).toBeGreaterThan(-1);
    expect(custPos).toBeGreaterThan(jobPos);
  });
});
