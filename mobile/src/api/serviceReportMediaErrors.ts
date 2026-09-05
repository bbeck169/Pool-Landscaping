/**
 * K59.a · Feb-2026 — Pure helper for flattening FastAPI ``response.detail``
 * payloads into a readable string.  Extracted from
 * ``serviceReportMedia.ts`` so it can be unit-tested without loading
 * the wider ``@/src/api`` chain (which pulls AsyncStorage +
 * SecureStore and is not Jest-friendly in isolation).
 *
 * FastAPI + Pydantic-v2 emit ``detail`` in three shapes:
 *
 *   1. ``string``           — explicit ``HTTPException(400, "…")`` sites.
 *   2. ``list[dict]``       — Pydantic auto-generated 422 validation
 *                             errors — each item has ``{type, loc, msg,
 *                             input, url}``.  Feeding this array to
 *                             ``new Error(x)`` produced the classic
 *                             ``"[object Object]"`` banner text
 *                             reported by users in K59.
 *   3. ``dict``             — business-rule raises like
 *                             ``HTTPException(422, {"detail": ...,
 *                             "message": ..., "missing_labels": [...]})``.
 *
 * The helper flattens all three into a single readable string capped
 * at 400 chars so a pathological Pydantic dump can't wreck the
 * fixed-height banner layout.
 *
 * REGRESSION CONTRACT: no input path may ever produce the literal
 * ``"[object Object]"`` substring in its return value.
 *
 * See /app/memory/PHASE_K59_a_UPLOAD_ERROR_STRINGIFIER.md.
 */

const _K59A_CAP = 400;

const _clip = (s: string): string =>
  s.length > _K59A_CAP ? s.slice(0, _K59A_CAP) : s;

export function stringifyDetail(detail: unknown): string {
  if (typeof detail === "string") return _clip(detail);
  if (Array.isArray(detail)) {
    return _clip(
      detail
        .map((item: any) => {
          if (typeof item === "string") return item;
          if (item?.msg) {
            const loc = Array.isArray(item.loc) ? item.loc.join(".") : "";
            return loc ? `${loc}: ${item.msg}` : String(item.msg);
          }
          try { return JSON.stringify(item).slice(0, 200); }
          catch { return "[unserialisable]"; }
        })
        .filter(Boolean)
        .join("; "),
    );
  }
  if (detail && typeof detail === "object") {
    const d = detail as any;
    const base: string = String(d.message ?? d.msg ?? d.detail ?? d.error ?? "");
    const labels: unknown = d.missing_labels ?? d.missing_fields;
    if (base && Array.isArray(labels) && labels.length) {
      return _clip(`${base}: ${labels.join(", ")}`);
    }
    if (base) return _clip(base);
    try { return _clip(JSON.stringify(d)); }
    catch { return "[unserialisable]"; }
  }
  return _clip(String(detail ?? ""));
}
