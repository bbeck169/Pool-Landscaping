/**
 * Phase I4 · Feb-2026 — Soshie brand-brain async ingest.
 *
 * Interaction test for the polling behavior on the BrandBrainTab
 * "Re-ingest from website" modal + the resume banner on mount.
 * We stub timers with vitest's fake-timer support so we can
 * fast-forward the 5s poll interval deterministically.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";

// Track the sequence of API calls so tests can drive
// queued → running → succeeded / failed transitions.
const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));
// Phase Hygiene B · Feb-2026 — use importActual so transitive consumers
// (e.g. @/components/ui-kit which reaches for ``gradients``) resolve
// against the real theme module rather than a partial hand-rolled stub.
vi.mock("@/theme", async () => {
  const actual = await vi.importActual("@/theme");
  return { ...actual };
});

// Silence sonner + capture toast calls.
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccess(...a),
    error: (...a) => toastError(...a),
  },
}));

import BrandBrainTab from "@/pages/soshie/BrandBrainTab";


const BRAND_BRAIN_POPULATED = {
  brand_brain: {
    tone: "Warm, practical, expert.",
    talking_points: ["We serve Phoenix pools."],
  },
  latest_ingest: {
    url: "https://vistancia.com",
    ingested_at: "2026-02-01T12:00:00Z",
  },
};

const JOB_QUEUED = {
  id: "job-abc123",
  tenant_id: "aquaterra",
  url: "https://example.com",
  extra_paths: [],
  status: "queued",
  started_at: "2026-02-14T09:00:00Z",
  finished_at: null,
  error: null,
  progress: {paths_crawled: 0, paths_total: 1, current_step: "queued"},
  result_summary: null,
};

const JOB_RUNNING = {
  ...JOB_QUEUED,
  status: "running",
  progress: {paths_crawled: 1, paths_total: 3, current_step: "crawling_and_parsing"},
};

const JOB_SUCCEEDED = {
  ...JOB_QUEUED,
  status: "succeeded",
  progress: {paths_crawled: 3, paths_total: 3, current_step: "succeeded"},
  result_summary: {pages_fetched: 3, bullets_added: 7, urls: []},
  finished_at: "2026-02-14T09:03:00Z",
};

const JOB_FAILED = {
  ...JOB_QUEUED,
  status: "failed",
  progress: {paths_crawled: 0, paths_total: 1, current_step: "crawling_and_parsing"},
  error: "home fetch timeout: connect ECONNREFUSED",
  finished_at: "2026-02-14T09:00:30Z",
};


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});


// Route mocked GETs based on the URL — mimics the two independent
// endpoints the tab hits (/soshie/brand-brain + /ingest/latest).
function routeGets(brandBrainResponse, latestResponse) {
  getMock.mockImplementation(async (path) => {
    if (path === "/soshie/brand-brain") return brandBrainResponse;
    if (path === "/soshie/brand-brain/ingest/latest") return latestResponse();
    return null;
  });
}


describe("BrandBrainTab · I4 async ingest", () => {
  it("resume banner renders on mount when a job is still running", async () => {
    let latestCallCount = 0;
    routeGets(BRAND_BRAIN_POPULATED, () => {
      latestCallCount += 1;
      return {job: JOB_RUNNING};
    });
    await act(async () => { render(<BrandBrainTab />); });
    // Both mount effects fire (brand-brain + ingest/latest).
    await waitFor(() => expect(screen.getByTestId(
      "brand-brain-content")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId(
      "brand-brain-resume-banner")).toBeInTheDocument());
    expect(screen.getByTestId("brand-brain-resume-banner"))
      .toHaveTextContent(/Ingest in progress/i);
    expect(latestCallCount).toBeGreaterThanOrEqual(1);
  });

  it("no banner when the latest job is terminal (succeeded)", async () => {
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: JOB_SUCCEEDED}));
    await act(async () => { render(<BrandBrainTab />); });
    await waitFor(() => expect(screen.getByTestId(
      "brand-brain-content")).toBeInTheDocument());
    expect(screen.queryByTestId("brand-brain-resume-banner")
    ).not.toBeInTheDocument();
  });

  it("clicking Ingest fires POST and shows the in-progress state", async () => {
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: null}));
    postMock.mockResolvedValue(JOB_QUEUED);
    await act(async () => { render(<BrandBrainTab />); });
    await waitFor(() => expect(screen.getByTestId(
      "brand-brain-reingest-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("brand-brain-reingest-btn"));
    // Modal open.
    await waitFor(() => expect(screen.getByTestId(
      "brand-brain-ingest-modal")).toBeInTheDocument());
    // Fill + submit.
    fireEvent.change(screen.getByTestId("ingest-url-input"),
      {target: {value: "https://example.com"}});
    // Re-route poll to return "running" so the progress indicator
    // sticks after submit.
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: JOB_RUNNING}));
    await act(async () => {
      fireEvent.click(screen.getByTestId("ingest-submit"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      "/soshie/brand-brain/ingest",
      {website_url: "https://example.com", extra_paths: []},
    ));
    // Progress indicator surfaces.
    await waitFor(() => expect(screen.getByTestId(
      "ingest-progress")).toBeInTheDocument());
    expect(screen.getByTestId("ingest-progress-body")
    ).toHaveTextContent(/Ingest in progress/i);
  });

  it("polling detects success, toasts, closes modal", async () => {
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: null}));
    postMock.mockResolvedValue(JOB_QUEUED);
    await act(async () => { render(<BrandBrainTab />); });
    fireEvent.click(await screen.findByTestId("brand-brain-reingest-btn"));
    fireEvent.change(await screen.findByTestId("ingest-url-input"),
      {target: {value: "https://example.com"}});
    // Poll returns "succeeded" immediately — pollOnce() fires
    // synchronously after submit, so success flips without
    // waiting for the setInterval tick.
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: JOB_SUCCEEDED}));
    await act(async () => {
      fireEvent.click(screen.getByTestId("ingest-submit"));
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith(
      "Brand memory ingest complete.",
    ));
    // Modal closes on success.
    await waitFor(() => expect(screen.queryByTestId(
      "brand-brain-ingest-modal")).not.toBeInTheDocument());
  });

  it("polling detects failure, modal stays open with Retry button", async () => {
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: null}));
    postMock.mockResolvedValue(JOB_QUEUED);
    await act(async () => { render(<BrandBrainTab />); });
    fireEvent.click(await screen.findByTestId("brand-brain-reingest-btn"));
    fireEvent.change(await screen.findByTestId("ingest-url-input"),
      {target: {value: "https://example.com"}});
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: JOB_FAILED}));
    await act(async () => {
      fireEvent.click(screen.getByTestId("ingest-submit"));
    });
    await waitFor(() => expect(screen.getByTestId(
      "ingest-progress-error")).toHaveTextContent(/home fetch timeout/i));
    // Modal stays open + Retry appears + no success toast fired.
    expect(screen.getByTestId("brand-brain-ingest-modal")
    ).toBeInTheDocument();
    expect(screen.getByTestId("ingest-retry")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("POST body forwards extra_paths from the textarea (newline-split, trimmed, empty-drop)", async () => {
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: null}));
    postMock.mockResolvedValue(JOB_QUEUED);
    await act(async () => { render(<BrandBrainTab />); });
    fireEvent.click(await screen.findByTestId("brand-brain-reingest-btn"));
    fireEvent.change(await screen.findByTestId("ingest-url-input"),
      {target: {value: "https://example.com"}});
    fireEvent.change(screen.getByTestId("ingest-extra-input"),
      {target: {value: "/services\n\n /about \n"}});
    await act(async () => {
      fireEvent.click(screen.getByTestId("ingest-submit"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock.mock.calls[0][1]).toEqual({
      website_url: "https://example.com",
      extra_paths: ["/services", "/about"],
    });
  });

  it("does NOT hit the legacy /soshie/ingest-website endpoint anymore", async () => {
    routeGets(BRAND_BRAIN_POPULATED, () => ({job: null}));
    postMock.mockResolvedValue(JOB_QUEUED);
    await act(async () => { render(<BrandBrainTab />); });
    fireEvent.click(await screen.findByTestId("brand-brain-reingest-btn"));
    fireEvent.change(await screen.findByTestId("ingest-url-input"),
      {target: {value: "https://example.com"}});
    await act(async () => {
      fireEvent.click(screen.getByTestId("ingest-submit"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock.mock.calls[0][0]).toBe("/soshie/brand-brain/ingest");
    // Regression guard against re-introducing the sync legacy path.
    const legacyCalls = postMock.mock.calls.filter(
      (c) => c[0] === "/soshie/ingest-website",
    );
    expect(legacyCalls).toHaveLength(0);
  });
});
