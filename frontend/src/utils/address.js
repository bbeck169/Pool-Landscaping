/**
 * Phase P14 · Feb-2026 — Address coercion (client-side twin).
 *
 * Mirrors the backend's ``_coerce_address_to_str`` (in
 * ``backend/routers/jobs.py``) so an object-shaped address on the
 * wire is rendered identically wherever the frontend touches it
 * (Item 5 ``ClickableAddress``, list cells, detail headers).
 *
 * Contract:
 *   * ``null`` / ``undefined``  → ``""``
 *   * ``string``                 → trimmed as-is
 *   * ``dict`` with ``formatted`` / ``full`` / ``line1`` → prefer that
 *   * otherwise concat street, city, state, zip in that order,
 *     comma-cleaned and stripped
 *   * anything else (number, boolean, function) → ``""``
 *
 * NOT a general-purpose formatter — deliberately doesn't handle
 * i18n / non-US postal shapes / country codes. Add fields to the
 * concat order if the backend model grows them.
 */

/** Prefer keys in a canonical order. First non-empty wins. */
function _preferKey(dict, keys) {
  for (const k of keys) {
    const v = dict?.[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}


export function coerceAddressToStr(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value !== "object") return "";

  // Prefer any pre-formatted key the backend / geocoder already
  // wrote — cheap fast-path.
  const preformatted = _preferKey(value, ["formatted", "full", "line1"]);
  if (preformatted) {
    // Some upstream shapes carry ``line1`` PLUS city/state — check
    // whether preformatted is the full thing (has a comma) or just
    // the street. If bare street, fall through to concat so we
    // still ship city/state on the wire.
    if (preformatted.includes(",")) return preformatted;
    // Concat pattern below — reuse ``preformatted`` as the street.
  }

  const street = preformatted
    || _preferKey(value, ["street", "line1", "address", "address1", "line_1"]);
  const city   = _preferKey(value, ["city", "town", "municipality", "locality"]);
  const state  = _preferKey(value, ["state", "province", "region", "state_code"]);
  const zip    = _preferKey(value, ["zip", "postal_code", "postcode", "zipcode", "zip_code"]);

  // Build: "street, city, state zip" — collapse empty segments and
  // stray commas.
  const parts = [];
  if (street) parts.push(street);
  if (city)   parts.push(city);
  const stateZip = [state, zip].filter(Boolean).join(" ").trim();
  if (stateZip) parts.push(stateZip);
  return parts.join(", ").replace(/\s{2,}/g, " ").trim();
}


export default coerceAddressToStr;
