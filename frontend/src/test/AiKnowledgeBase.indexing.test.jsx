/**
 * KB IH-A · Feb-2026 — AiKnowledgeBase / AIBrainPage indexing UI.
 *
 * Note on filename: the user brief spec'd
 * ``AiKnowledgeBase.indexing.test.jsx`` but the actual FE page
 * file is ``AIBrainPage.jsx`` (verified at recon).  Test file
 * name follows the brief; component-under-test is the real
 * page module.
 *
 * Locks the FE contract shipped with IH-A:
 *
 *   1. ``IndexStatusPill`` renders all 4 states with the right
 *      ``data-status`` attribute + accessible tooltip on
 *      error.
 *   2. ``ReindexButton`` is admin-gated (renders when role ∈
 *      {admin, super_admin}; null otherwise).
 *   3. ``AskThisDocPanel`` renders top-3 hit cards with a
 *      ``Page N`` badge + ``figure_refs`` chips per hit;
 *      submits ``POST /api/kb/query`` on click.
 *   4. Non-status ("legacy" / unset ``index_status``) rows
 *      render NO pill (grandfather compat).
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  },
}));

// Mock the api module — we drive requests directly with
// canned responses. ``vi.hoisted`` lifts the mock object
// definition to the top so ``vi.mock`` (also hoisted) can
// reference it without a TDZ crash.
const { _apiMock } = vi.hoisted(() => ({
  _apiMock: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import {
  IndexStatusPill, ReindexButton, AskThisDocPanel,
} from "@/pages/settings/AIBrainPage";


// ══════════════════════════════════════════════════════════════
// IndexStatusPill — 4 status states + legacy no-render
// ══════════════════════════════════════════════════════════════
describe("KB IH-A · IndexStatusPill", () => {
  it("(pending) renders grey 'Queued' pill", () => {
    render(<IndexStatusPill item={{ id: "kb-1", index_status: "pending" }} />);
    const pill = screen.getByTestId("ai-brain-index-pill-kb-1");
    expect(pill).toHaveAttribute("data-status", "pending");
    expect(pill.textContent).toMatch(/Queued/);
  });

  it("(indexing) renders blue 'Indexing…' pill with spinner icon", () => {
    render(<IndexStatusPill item={{ id: "kb-2", index_status: "indexing" }} />);
    const pill = screen.getByTestId("ai-brain-index-pill-kb-2");
    expect(pill).toHaveAttribute("data-status", "indexing");
    expect(pill.textContent).toMatch(/Indexing/);
    // Loader2 icon rendered inside — svg element present.
    expect(pill.querySelector("svg")).not.toBeNull();
  });

  it("(ready) renders green 'Indexed: N pages / M chunks' pill", () => {
    render(<IndexStatusPill item={{
      id: "kb-3", index_status: "ready",
      pages_count: 12, chunks_count: 47,
    }} />);
    const pill = screen.getByTestId("ai-brain-index-pill-kb-3");
    expect(pill).toHaveAttribute("data-status", "ready");
    expect(pill.textContent).toMatch(/Indexed: 12p \/ 47c/);
    // Tooltip carries the human-readable descriptor.
    expect(pill).toHaveAttribute(
      "title",
      "Deep-indexed 47 chunks across 12 pages",
    );
  });

  it("(error) renders red 'Index failed' pill with index_error tooltip", () => {
    render(<IndexStatusPill item={{
      id: "kb-4", index_status: "error",
      index_error: "embed_call_failed: quota_exceeded",
    }} />);
    const pill = screen.getByTestId("ai-brain-index-pill-kb-4");
    expect(pill).toHaveAttribute("data-status", "error");
    expect(pill.textContent).toMatch(/Index failed/);
    expect(pill).toHaveAttribute(
      "title", "embed_call_failed: quota_exceeded",
    );
  });

  it("(legacy) unset index_status renders nothing (grandfather)", () => {
    const { container } = render(
      <IndexStatusPill item={{ id: "kb-5" }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("(unknown status) renders nothing (defensive)", () => {
    const { container } = render(
      <IndexStatusPill item={{ id: "kb-6", index_status: "quantum" }} />,
    );
    expect(container.firstChild).toBeNull();
  });
});


// ══════════════════════════════════════════════════════════════
// ReindexButton — admin-gated visibility + onReindex fires
// ══════════════════════════════════════════════════════════════
describe("KB IH-A · ReindexButton", () => {
  it("renders when isAdmin=true and fires onReindex with item", () => {
    const onReindex = vi.fn();
    render(<ReindexButton
      item={{ id: "kb-99", title: "Manual" }}
      isAdmin={true}
      onReindex={onReindex}
    />);
    const btn = screen.getByTestId("ai-brain-reindex-btn-kb-99");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-label", "Reindex document");
    fireEvent.click(btn);
    expect(onReindex).toHaveBeenCalledTimes(1);
    expect(onReindex.mock.calls[0][0]).toMatchObject({ id: "kb-99" });
  });

  it("renders NOTHING when isAdmin=false (admin-only per brief)", () => {
    const { container } = render(<ReindexButton
      item={{ id: "kb-100" }}
      isAdmin={false}
      onReindex={vi.fn()}
    />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("ai-brain-reindex-btn-kb-100")).toBeNull();
  });
});


// ══════════════════════════════════════════════════════════════
// AskThisDocPanel — top-3 hits with page + figure badges
// ══════════════════════════════════════════════════════════════
describe("KB IH-A · AskThisDocPanel", () => {
  it("submits POST /kb/query and renders top-3 hit cards with page + figure badges", async () => {
    _apiMock.post.mockResolvedValueOnce({
      hits: [
        {
          doc_id: "kb-A", doc_title: "Chlorine Manual",
          page_num: 4, score: 0.91,
          chunk_text: "The chlorine dosage table lives on page four...",
          figure_refs: [{ page_num: 4, figure_label: "Figure 7", bbox: null }],
        },
        {
          doc_id: "kb-B", doc_title: "Filter Manual",
          page_num: 9, score: 0.82,
          chunk_text: "Filter cartridge replacement schedule...",
          figure_refs: [],
        },
        {
          doc_id: "kb-C", doc_title: "Pump Manual",
          page_num: 2, score: 0.71,
          chunk_text: "Priming procedure for the variable-speed pump.",
          figure_refs: [
            { page_num: 2, figure_label: "Diagram 3", bbox: null },
            { page_num: 2, figure_label: "Figure 1", bbox: null },
          ],
        },
      ],
      query_ms: 42,
    });

    render(<AskThisDocPanel />);

    const input = screen.getByTestId("ai-brain-ask-input");
    fireEvent.change(input, { target: { value: "chlorine dosage" } });
    fireEvent.click(screen.getByTestId("ai-brain-ask-submit"));

    // Wait for the network round-trip + render.
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith("/kb/query", {
        query: "chlorine dosage",
        top_k: 3,
        min_score: 0.25,
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId("ai-brain-ask-hits")).toBeInTheDocument();
    });

    // Hit 0 · doc_title + Page 4 badge + Figure 7 chip.
    expect(screen.getByTestId("ai-brain-ask-hit-0-title"))
      .toHaveTextContent("Chlorine Manual");
    expect(screen.getByTestId("ai-brain-ask-hit-0-page"))
      .toHaveTextContent("Page 4");
    expect(screen.getByTestId("ai-brain-ask-hit-0-figure-0"))
      .toHaveTextContent("Figure 7");

    // Hit 1 · no figure_refs — no figure chips.
    expect(screen.getByTestId("ai-brain-ask-hit-1-title"))
      .toHaveTextContent("Filter Manual");
    expect(screen.getByTestId("ai-brain-ask-hit-1-page"))
      .toHaveTextContent("Page 9");
    expect(screen.queryByTestId("ai-brain-ask-hit-1-figure-0")).toBeNull();

    // Hit 2 · TWO figure chips.
    expect(screen.getByTestId("ai-brain-ask-hit-2-figure-0"))
      .toHaveTextContent("Diagram 3");
    expect(screen.getByTestId("ai-brain-ask-hit-2-figure-1"))
      .toHaveTextContent("Figure 1");
  });

  it("empty query does not fire a request", () => {
    _apiMock.post.mockClear();
    render(<AskThisDocPanel />);
    fireEvent.click(screen.getByTestId("ai-brain-ask-submit"));
    expect(_apiMock.post).not.toHaveBeenCalled();
  });

  it("surfaces backend error field as visible error message", async () => {
    _apiMock.post.mockResolvedValueOnce({
      hits: [],
      query_ms: 5,
      error: "embedding_call_failed: quota_exceeded",
    });
    render(<AskThisDocPanel />);
    fireEvent.change(
      screen.getByTestId("ai-brain-ask-input"),
      { target: { value: "boom" } },
    );
    fireEvent.click(screen.getByTestId("ai-brain-ask-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("ai-brain-ask-error"))
        .toHaveTextContent(/quota_exceeded/);
    });
  });

  it("clicking a hit card invokes onCitationSelect with the hit payload", async () => {
    _apiMock.post.mockResolvedValueOnce({
      hits: [{
        doc_id: "kb-X", doc_title: "Test",
        page_num: 5, chunk_text: "abc", figure_refs: [],
      }],
      query_ms: 3,
    });
    const onCitationSelect = vi.fn();
    render(<AskThisDocPanel onCitationSelect={onCitationSelect} />);
    fireEvent.change(
      screen.getByTestId("ai-brain-ask-input"),
      { target: { value: "any" } },
    );
    fireEvent.click(screen.getByTestId("ai-brain-ask-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("ai-brain-ask-hit-0")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("ai-brain-ask-hit-0"));
    expect(onCitationSelect).toHaveBeenCalledTimes(1);
    expect(onCitationSelect.mock.calls[0][0]).toMatchObject({
      doc_id: "kb-X", page_num: 5,
    });
  });
});
