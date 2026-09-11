/**
 * Feb-2026 · Thumbnails + upload guardrails — frontend contract tests.
 *
 * Locks the four PhotoUploader invariants that ship alongside the
 * backend Pillow + S3 sibling upload:
 *
 *   1. List rows render <img src="/api/public/job-photo/.../thumb"
 *      loading="lazy"> — no base64 blob in the DOM.
 *   2. An 8 MB "compressed" File that STILL breaks the 5 MB gate
 *      surfaces the inline "too large after resizing" error and
 *      does NOT fire the POST.
 *   3. A non-image MIME (application/pdf) is rejected inline with
 *      the "Unsupported file type" error — no POST fires.
 *   4. A small file that fits under 5 MB after compression passes
 *      the gate and POSTs to /jobs/{jid}/photos.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const __stubs = {
  compressImageIfNeeded: vi.fn(),
  apiPost: vi.fn(),
};

vi.mock("@/lib/imageCompress", () => ({
  __esModule: true,
  compressImageIfNeeded: (...a) => __stubs.compressImageIfNeeded(...a),
  default: (...a) => __stubs.compressImageIfNeeded(...a),
}));
vi.mock("@/api", () => ({
  api: {
    post: (...a) => __stubs.apiPost(...a),
    del: async () => ({ photos: [] }),
    get: async () => ({}),
  },
  TOKEN_KEY: "auth_token",
}));

import PhotoUploader from "@/components/checklist/PhotoUploader";

function realFile(name, bytes, type) {
  const buf = new Uint8Array(bytes);
  return new File([buf], name, { type });
}

beforeEach(() => {
  __stubs.compressImageIfNeeded.mockReset();
  __stubs.apiPost.mockReset();
});


// ═══════════════════════════════════════════════════════════════════
// 1 · Thumb URL rendering — lazy, from public endpoint (not base64)
// ═══════════════════════════════════════════════════════════════════
describe("PhotoUploader · thumbnail rendering", () => {
  it("renders <img> with the /thumb URL and loading='lazy'", () => {
    const photos = [
      { id: "p-1", data: "data:image/jpeg;base64,AAAA", label: "one" },
      { id: "p-2", data: "data:image/jpeg;base64,BBBB", label: "two" },
    ];
    render(<PhotoUploader jobId="j-thumb" photos={photos}
                          onPhotosChange={() => {}} />);
    const img1 = screen.getByTestId("checklist-photo-img-p-1");
    const img2 = screen.getByTestId("checklist-photo-img-p-2");
    expect(img1.getAttribute("src")).toBe(
      "/api/public/job-photo/j-thumb/p-1/thumb",
    );
    expect(img1.getAttribute("loading")).toBe("lazy");
    expect(img2.getAttribute("src")).toBe(
      "/api/public/job-photo/j-thumb/p-2/thumb",
    );
    // The base64 blob from `photos[].data` must NOT leak into the DOM.
    expect(img1.getAttribute("src")).not.toMatch(/^data:image/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2 · Oversize post-compression → inline error, no POST
// ═══════════════════════════════════════════════════════════════════
describe("PhotoUploader · upload guardrails", () => {
  it("rejects a file that is > 5 MB after compression — no POST fires", async () => {
    // 8 MB blob — real bytes so FileReader produces a real b64 payload
    // of the right decoded size.
    const raw = realFile("huge.jpg", 8 * 1024 * 1024, "image/jpeg");
    // Compression "succeeds" but returns the same-size file (fallback).
    __stubs.compressImageIfNeeded.mockResolvedValueOnce(raw);
    __stubs.apiPost.mockResolvedValue({ photos: [] });

    render(<PhotoUploader jobId="j-big" photos={[]}
                          onPhotosChange={() => {}} />);
    const input = screen.getByTestId("checklist-photo-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [raw] } });
    });

    // Compression fired, but POST never did.
    await waitFor(() => {
      expect(__stubs.compressImageIfNeeded).toHaveBeenCalledTimes(1);
    });
    expect(__stubs.apiPost).not.toHaveBeenCalled();

    const errBox = await screen.findByTestId("checklist-photo-error");
    expect(errBox.textContent).toMatch(/too large after resizing/i);
  });

  it("rejects a non-image MIME up front — no compression + no POST", async () => {
    const pdf = realFile("doc.pdf", 100 * 1024, "application/pdf");
    __stubs.compressImageIfNeeded.mockResolvedValue(pdf);
    __stubs.apiPost.mockResolvedValue({ photos: [] });

    render(<PhotoUploader jobId="j-badmime" photos={[]}
                          onPhotosChange={() => {}} />);
    const input = screen.getByTestId("checklist-photo-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [pdf] } });
    });

    const errBox = await screen.findByTestId("checklist-photo-error");
    expect(errBox.textContent).toMatch(/unsupported file type/i);
    expect(__stubs.compressImageIfNeeded).not.toHaveBeenCalled();
    expect(__stubs.apiPost).not.toHaveBeenCalled();
  });

  it("uploads a file that fits under 5 MB after compression", async () => {
    const raw = realFile("phone.jpg", 6 * 1024 * 1024, "image/jpeg");
    const small = realFile("phone.jpg", 700 * 1024, "image/jpeg");
    __stubs.compressImageIfNeeded.mockResolvedValueOnce(small);
    __stubs.apiPost.mockResolvedValueOnce({
      photos: [{ id: "new-photo", label: "checklist" }],
    });
    const onChange = vi.fn();

    render(<PhotoUploader jobId="j-ok" photos={[]} onPhotosChange={onChange} />);
    const input = screen.getByTestId("checklist-photo-input");
    await act(async () => {
      fireEvent.change(input, { target: { files: [raw] } });
    });

    await waitFor(() => expect(__stubs.apiPost).toHaveBeenCalledTimes(1));
    const [url, body] = __stubs.apiPost.mock.calls[0];
    expect(url).toBe("/jobs/j-ok/photos");
    expect(typeof body.data).toBe("string");
    expect(body.data.startsWith("data:")).toBe(true);
    expect(onChange).toHaveBeenCalledWith([
      { id: "new-photo", label: "checklist" },
    ]);
  });
});
