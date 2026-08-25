/**
 * Feb 2026 — iOS field-upload compression helper.
 *
 * Fixes the P0 timeout issue where technicians uploading modern
 * iPhone photos (4-7 MB HEIC-converted-to-JPEG) from LTE at pool
 * decks were exceeding the platform ingress read timeout on every
 * upload surface. `browser-image-compression` runs in a web worker
 * (does not block Safari), targets ~1.5MB / 2560px, and normalizes
 * HEIC/PNG to JPEG so the outgoing payload is a predictable size.
 *
 * Design contract:
 *   * Non-image files pass through UNCHANGED (PDFs, mp4, csv, etc).
 *   * Images ≤ 1 MB pass through UNCHANGED (already small).
 *   * Any compression failure returns the ORIGINAL file — the caller's
 *     existing size gate (25 MB `MAX_UPLOAD_SIZE_BYTES` in FileUpload,
 *     10-photo cap on `/api/jobs/{jid}/photos`) is still the last-line
 *     defense.
 */
import imageCompression from "browser-image-compression";

const COMPRESS_THRESHOLD_BYTES = 1024 * 1024; // ≤1MB skip
const OPTS = {
  maxSizeMB: 1.5,          // hard target — brings 6MB HEIC-JPEG → ~1.2MB
  maxWidthOrHeight: 2560,  // 4K → sensible print/social size
  useWebWorker: true,      // does not block UI on iOS Safari
  fileType: "image/jpeg",  // normalize HEIC / PNG variants
  initialQuality: 0.82,
};

/**
 * Compress an image `File` if it is worth compressing.
 *
 * @param {File | null | undefined} file
 * @returns {Promise<File | null | undefined>}
 */
export async function compressImageIfNeeded(file) {
  if (!file || typeof file !== "object") return file;
  const type = typeof file.type === "string" ? file.type : "";
  if (!type.startsWith("image/")) return file;
  if (typeof file.size !== "number" || file.size <= COMPRESS_THRESHOLD_BYTES) {
    return file;
  }
  try {
    const out = await imageCompression(file, OPTS);
    if (!out || typeof out !== "object") return file;
    // Preserve the original filename but swap the extension to .jpg so
    // servers that key on the extension (multipart + base64 upload
    // paths both do) route it as JPEG.
    const originalName = typeof file.name === "string" ? file.name : "photo.jpg";
    const nextName = originalName.replace(/\.[^.]+$/, "") + ".jpg";
    // out is a Blob from browser-image-compression; wrap it in a File so
    // FormData.append() keeps the filename and downstream code that
    // reads `file.name` (e.g. `readAsDataURL` label + `file.name`
    // append) keeps working.
    return new File([out], nextName, {
      type: out.type || "image/jpeg",
      lastModified: Date.now(),
    });
  } catch {
    return file;
  }
}

export default compressImageIfNeeded;
