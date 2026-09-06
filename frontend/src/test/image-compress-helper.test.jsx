/**
 * Feb 2026 — Unit tests for the iOS field-upload compression helper
 * (`src/lib/imageCompress.js`). Covers the four contract points from
 * the audit:
 *   1. Non-image files pass through UNCHANGED.
 *   2. Image files ≤ 1 MB pass through UNCHANGED.
 *   3. Image files > 1 MB are compressed and returned as a new File.
 *   4. Compression throw → original file is returned (last-line
 *      defense — the caller's existing size gate still applies).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock `browser-image-compression` BEFORE importing the helper so
// every code path sees the stub.
const __mock = {
  compress: vi.fn(),
};
vi.mock("browser-image-compression", () => ({
  __esModule: true,
  default: (...a) => __mock.compress(...a),
}));

import { compressImageIfNeeded } from "../lib/imageCompress";

function mockFile(name, size, type) {
  const blob = new Blob([new Uint8Array(1)], { type });
  Object.defineProperty(blob, "size", { value: size });
  Object.defineProperty(blob, "name", { value: name });
  // Blob is a File-shaped object in JSDOM (has .type, .size, .name);
  // real File is a Blob subclass so this is fine for our contract.
  return blob;
}

beforeEach(() => {
  __mock.compress.mockReset();
});

describe("compressImageIfNeeded", () => {
  it("returns non-image files unchanged (PDF)", async () => {
    const pdf = mockFile("doc.pdf", 5 * 1024 * 1024, "application/pdf");
    const out = await compressImageIfNeeded(pdf);
    expect(out).toBe(pdf);
    expect(__mock.compress).not.toHaveBeenCalled();
  });

  it("returns non-image files unchanged (mp4 video)", async () => {
    const video = mockFile("clip.mp4", 10 * 1024 * 1024, "video/mp4");
    const out = await compressImageIfNeeded(video);
    expect(out).toBe(video);
    expect(__mock.compress).not.toHaveBeenCalled();
  });

  it("returns small (≤1MB) images unchanged", async () => {
    const small = mockFile("thumb.jpg", 512 * 1024, "image/jpeg");
    const out = await compressImageIfNeeded(small);
    expect(out).toBe(small);
    expect(__mock.compress).not.toHaveBeenCalled();
  });

  it("compresses images > 1 MB and returns a smaller File", async () => {
    // Simulate a modern iPhone HEIC-converted-JPEG upload.
    const big = mockFile("iphone.jpg", 6 * 1024 * 1024, "image/jpeg");
    const compressedBlob = new Blob([new Uint8Array(1)], { type: "image/jpeg" });
    Object.defineProperty(compressedBlob, "size", { value: 1.1 * 1024 * 1024 });
    __mock.compress.mockResolvedValueOnce(compressedBlob);

    const out = await compressImageIfNeeded(big);

    expect(__mock.compress).toHaveBeenCalledTimes(1);
    // Options object — must set useWebWorker + a hard maxSizeMB target.
    const opts = __mock.compress.mock.calls[0][1];
    expect(opts.useWebWorker).toBe(true);
    expect(typeof opts.maxSizeMB).toBe("number");
    expect(opts.maxSizeMB).toBeLessThanOrEqual(2);

    expect(out).not.toBe(big);
    expect(out.size).toBeLessThan(big.size);
    // Filename normalized to .jpg so servers keying on the extension
    // route the payload as JPEG.
    expect(out.name).toBe("iphone.jpg");
    expect(out.type).toBe("image/jpeg");
  });

  it("normalizes HEIC filename to .jpg extension when compressed", async () => {
    const heic = mockFile("IMG_1234.HEIC", 4 * 1024 * 1024, "image/heic");
    const compressedBlob = new Blob([new Uint8Array(1)], { type: "image/jpeg" });
    Object.defineProperty(compressedBlob, "size", { value: 900 * 1024 });
    __mock.compress.mockResolvedValueOnce(compressedBlob);

    const out = await compressImageIfNeeded(heic);
    expect(out.name).toBe("IMG_1234.jpg");
    expect(out.type).toBe("image/jpeg");
  });

  it("returns the ORIGINAL file when compression throws (safe fallback)", async () => {
    const big = mockFile("weird.jpg", 3 * 1024 * 1024, "image/jpeg");
    __mock.compress.mockRejectedValueOnce(new Error("HEIC decoder crashed"));

    const out = await compressImageIfNeeded(big);
    expect(out).toBe(big);
  });

  it("handles null / undefined input safely", async () => {
    expect(await compressImageIfNeeded(null)).toBe(null);
    expect(await compressImageIfNeeded(undefined)).toBe(undefined);
    expect(__mock.compress).not.toHaveBeenCalled();
  });
});
