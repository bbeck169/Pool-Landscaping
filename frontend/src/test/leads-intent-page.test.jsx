/**
 * LSP-1 · Feb-2026 — Lead-Sense visitor-intent page contract.
 *
 * Source-grep style (mirrors ``InvoicesList.defaultUnpaidFilter.test.jsx``).
 * The page hits two backend surfaces, has a filter bar with six inputs,
 * a paginated table with row drill-down, and a 4-tile summary panel —
 * this file locks each of those seams O(1) against JSX regressions.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const PAGE = read("src/pages/leads/LeadsIntentPage.jsx");


describe("LSP-1 · LeadsIntentPage", () => {
  // ── API contract ──────────────────────────────────────────────
  it("calls GET /lead-sense/intents with querystring", () => {
    expect(PAGE).toMatch(/api\.get\(`\/lead-sense\/intents\?\$\{buildQs\(\)\}`\)/);
  });

  it("calls GET /lead-sense/intents/summary", () => {
    expect(PAGE).toMatch(/api\.get\(`\/lead-sense\/intents\/summary\$\{suffix\}`\)/);
  });

  // ── Page shell ────────────────────────────────────────────────
  it("has root testid leads-intent-page and back-link to /leads", () => {
    expect(PAGE).toMatch(/data-testid="leads-intent-page"/);
    expect(PAGE).toMatch(/data-testid="leads-intent-back"/);
    expect(PAGE).toMatch(/to="\/leads"/);
  });

  // ── Summary tiles (all four) ──────────────────────────────────
  it("summary tile: total_sessions", () => {
    expect(PAGE).toMatch(/summary\?\.total_sessions/);
    expect(PAGE).toMatch(/data-testid="summary-total-sessions"/);
  });

  it("summary tile: conversion_rate_pct with % suffix", () => {
    expect(PAGE).toMatch(/summary\?\.conversion_rate_pct/);
    expect(PAGE).toMatch(/data-testid="summary-conversion-rate"/);
    expect(PAGE).toMatch(/\$\{summary\.conversion_rate_pct\}%/);
  });

  it("summary tile: top page + top referrer", () => {
    expect(PAGE).toMatch(/summary\?\.top_pages\?\.\[0\]\?\.page/);
    expect(PAGE).toMatch(/summary\?\.top_referrers\?\.\[0\]\?\.referrer/);
    expect(PAGE).toMatch(/data-testid="summary-top-page"/);
    expect(PAGE).toMatch(/data-testid="summary-top-referrer"/);
  });

  // ── Filter bar (six controls) ─────────────────────────────────
  it("filter controls: session_id + converted + since + until + sort + page_size", () => {
    expect(PAGE).toMatch(/data-testid="intent-filter-session-id"/);
    expect(PAGE).toMatch(/data-testid="intent-filter-converted"/);
    expect(PAGE).toMatch(/data-testid="intent-filter-since"/);
    expect(PAGE).toMatch(/data-testid="intent-filter-until"/);
    expect(PAGE).toMatch(/data-testid="intent-filter-sort"/);
    expect(PAGE).toMatch(/data-testid="intent-filter-page-size"/);
  });

  it("page_size options are exactly 25 / 50 / 100 / 200", () => {
    expect(PAGE).toMatch(/const PAGE_SIZE_OPTIONS = \[25, 50, 100, 200\]/);
  });

  it("converted select options are '' / 'true' / 'false'", () => {
    expect(PAGE).toMatch(/\{ value: "",\s*label: "All sessions" \}/);
    expect(PAGE).toMatch(/\{ value: "true",\s*label: "Converted only" \}/);
    expect(PAGE).toMatch(/\{ value: "false",\s*label: "Not yet converted" \}/);
  });

  it("sort options include created_at_desc + created_at_asc", () => {
    expect(PAGE).toMatch(/\{ value: "created_at_desc",\s*label: "Newest first" \}/);
    expect(PAGE).toMatch(/\{ value: "created_at_asc",\s*label: "Oldest first" \}/);
  });

  // ── Refetch on filter change ──────────────────────────────────
  it("list useEffect deps include every filter key + page + pageSize", () => {
    expect(PAGE).toMatch(
      /useEffect\(\(\)\s*=>\s*\{\s*refresh\(\);[\s\S]*?\},\s*\[\s*filters\.session_id,\s*filters\.converted,\s*filters\.since,\s*filters\.until,\s*filters\.sort,\s*page,\s*pageSize,?\s*\]/,
    );
  });

  it("summary useEffect deps include filters.since + filters.until", () => {
    expect(PAGE).toMatch(
      /useEffect\(\(\)\s*=>\s*\{\s*refreshSummary\(\);[\s\S]*?\},\s*\[\s*filters\.since,\s*filters\.until,?\s*\]/,
    );
  });

  it("changing a filter resets page to 1", () => {
    expect(PAGE).toMatch(/const setF = \(k, v\) => \{ setFilters\(\(f\) => \(\{ \.\.\.f, \[k\]: v \}\)\); setPage\(1\); \}/);
  });

  // ── Table + row drill-down ────────────────────────────────────
  it("row uses testid intent-row-{id} and toggles expansion", () => {
    expect(PAGE).toMatch(/data-testid=\{`intent-row-\$\{it\.id\}`\}/);
    expect(PAGE).toMatch(/onClick=\{\(\) => toggleExpand\(it\.id\)\}/);
  });

  it("expanded detail panel uses intent-detail-{id} testid and shows capture_mode + full URL + user_agent", () => {
    expect(PAGE).toMatch(/data-testid=\{`intent-detail-\$\{it\.id\}`\}/);
    expect(PAGE).toMatch(/Capture mode:/);
    expect(PAGE).toMatch(/User agent:/);
    expect(PAGE).toMatch(/Full URL:/);
  });

  it("converted rows link to the existing /leads/{lead_id} detail page", () => {
    expect(PAGE).toMatch(/to=\{`\/leads\/\$\{it\.converted_lead_id\}`\}/);
    expect(PAGE).toMatch(/data-testid=\{`intent-converted-link-\$\{it\.id\}`\}/);
  });

  it("shows Converted / Open badge per row", () => {
    expect(PAGE).toMatch(/data-testid=\{`intent-converted-badge-\$\{it\.id\}`\}/);
  });

  // ── Pagination ────────────────────────────────────────────────
  it("prev / next / indicator controls all present", () => {
    expect(PAGE).toMatch(/data-testid="intent-page-prev"/);
    expect(PAGE).toMatch(/data-testid="intent-page-next"/);
    expect(PAGE).toMatch(/data-testid="intent-page-indicator"/);
  });

  it("prev is disabled at page 1; next is disabled at last page", () => {
    expect(PAGE).toMatch(/disabled=\{page <= 1\}/);
    expect(PAGE).toMatch(/disabled=\{page >= totalPages\}/);
  });

  // ── Empty / loading / error states ────────────────────────────
  it("renders loading / error / empty states with dedicated testids", () => {
    expect(PAGE).toMatch(/data-testid="intent-loading"/);
    expect(PAGE).toMatch(/data-testid="intent-error"/);
    expect(PAGE).toMatch(/data-testid="intent-empty"/);
  });

  // ── Security: never leak the tenant's marco_lead_sense_id ────
  it("page source never references marco_lead_sense_id", () => {
    expect(PAGE).not.toMatch(/marco_lead_sense_id/);
  });
});
