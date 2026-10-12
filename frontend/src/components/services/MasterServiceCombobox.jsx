/**
 * Phase P16 · Feb-2026 — Reusable Master Service searchable combobox.
 *
 * Renders as an <input> + typeahead dropdown that fetches the tenant's
 * active master services from ``GET /api/master-services`` and filters
 * client-side on every keystroke (case-insensitive substring match).
 *
 * Contract:
 *   • Controlled ``value`` (string) — the current NAME.
 *   • ``onChange({ name, default_price, category })`` fires on both
 *     pick + typed change so parent forms can auto-fill the price
 *     and category fields.  When the user is free-typing (no
 *     match), ``default_price`` + ``category`` are ``null`` —
 *     parent MUST NOT overwrite its own state on those keys unless
 *     they came in non-null (a pick / new-add).
 *   • Inline "+ Add …" row appears at the bottom of the dropdown
 *     whenever the typed value is non-empty AND doesn't match an
 *     existing active service (case-insensitive on ``name``).
 *     Clicking it opens the ``AddMasterServiceModal`` prefilled
 *     with the typed name, an optional numeric ``default_price``
 *     from ``defaultPriceHint``, and a REQUIRED category
 *     dropdown seeded from ``GET /master-services/categories``.
 *   • A very small in-memory cache (keyed to the tenant) prevents
 *     the list endpoint from firing on every re-mount.  The cache
 *     is invalidated locally after a successful "+ Add" so the
 *     new row shows up without a manual refetch.
 *
 * The component is intentionally dumb — no toasts, no route
 * navigation — so it's cheap to drop into Estimates / Invoices
 * line-item editors in P16.1.
 */
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { Search, X, Plus } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


// ─── Tiny in-memory cache — keyed by tenant slug on the api base URL
// (so it invalidates automatically when the user switches tenants).
const _CACHE = new Map(); // key: string → { items: Array, expires: number }
const _CACHE_TTL_MS = 60_000;


function _cacheKey() {
  // The api client stamps the auth header off localStorage / cookies;
  // the cheapest stable identity we have without importing an auth
  // hook is the origin URL — one entry per browser tab is fine.
  return typeof window !== "undefined"
    ? String(window.location?.origin || "default")
    : "default";
}


async function _fetchActiveServices(force = false) {
  const key = _cacheKey();
  const hit = _CACHE.get(key);
  if (!force && hit && hit.expires > Date.now()) return hit.items;
  const res = await api.get("/master-services");
  const items = Array.isArray(res?.items) ? res.items : [];
  _CACHE.set(key, { items, expires: Date.now() + _CACHE_TTL_MS });
  return items;
}


export function invalidateMasterServicesCache() {
  _CACHE.delete(_cacheKey());
}


function AddMasterServiceModal({
  initialName,
  initialDefaultPrice,
  onCancel,
  onCreated,
}) {
  const [name, setName] = useState(initialName || "");
  const [defaultPrice, setDefaultPrice] = useState(
    Number.isFinite(initialDefaultPrice) && initialDefaultPrice > 0
      ? String(initialDefaultPrice)
      : "",
  );
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get("/master-services/categories").then((res) => {
      if (cancelled) return;
      setCategories(Array.isArray(res?.items) ? res.items : []);
    }).catch(() => {
      if (!cancelled) setCategories([]);
    });
    return () => { cancelled = true; };
  }, []);

  const save = useCallback(async () => {
    setErr("");
    const trimmed = (name || "").trim();
    if (!trimmed) { setErr("Name is required."); return; }
    if (!category) { setErr("Category is required."); return; }
    const priceN = Number(defaultPrice);
    if (defaultPrice !== "" && (!Number.isFinite(priceN) || priceN < 0)) {
      setErr("Default price must be a non-negative number.");
      return;
    }
    setBusy(true);
    try {
      const created = await api.post("/master-services", {
        name: trimmed,
        default_price: defaultPrice === "" ? 0 : priceN,
        category,
      });
      invalidateMasterServicesCache();
      onCreated?.(created);
    } catch (e) {
      const code = e?.data?.detail?.error || e?.data?.error;
      if (code === "duplicate_name") {
        setErr("A master service with that name already exists.");
      } else if (code === "category_invalid") {
        setErr("Category is not valid for this tenant.");
      } else {
        setErr(e?.message || "Save failed.");
      }
    } finally { setBusy(false); }
  }, [name, defaultPrice, category, onCreated]);

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onCancel}
      data-testid="master-service-add-modal-backdrop"
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="master-service-add-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold" style={{ color: colors.onSurface }}>
            Add to Master Service List
          </div>
          <button
            onClick={onCancel}
            style={{ color: colors.muted }}
            data-testid="master-service-add-modal-close"
          >
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label
              className="text-xs uppercase font-semibold block mb-1"
              style={{ color: colors.muted }}
            >Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="master-service-add-modal-name"
            />
          </div>
          <div>
            <label
              className="text-xs uppercase font-semibold block mb-1"
              style={{ color: colors.muted }}
            >Default Price</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={defaultPrice}
              onChange={(e) => setDefaultPrice(e.target.value)}
              placeholder="0.00"
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="master-service-add-modal-price"
            />
          </div>
          <div>
            <label
              className="text-xs uppercase font-semibold block mb-1"
              style={{ color: colors.muted }}
            >Category *</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="master-service-add-modal-category"
            >
              <option value="">— Select category —</option>
              {categories.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>
          {err ? (
            <div
              className="text-xs px-2 py-1 rounded"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="master-service-add-modal-error"
            >{err}</div>
          ) : null}
        </div>
        <footer
          className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            onClick={onCancel}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-lg"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="master-service-add-modal-cancel"
          >Cancel</button>
          <button
            onClick={save}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-lg font-semibold disabled:opacity-60"
            style={{ background: colors.brand, color: "#FFFFFF" }}
            data-testid="master-service-add-modal-save"
          >{busy ? "Saving…" : "Add service"}</button>
        </footer>
      </div>
    </div>
  );
}


export default function MasterServiceCombobox({
  value,
  onChange,
  defaultPriceHint = null,
  placeholder = "Search or add a service…",
  disabled = false,
  testid = "master-service-combobox",
}) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const wrapRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const rows = await _fetchActiveServices();
      setItems(rows);
    } catch { setItems([]); }
    finally { setLoaded(true); }
  }, []);

  // Fetch on first focus so pages that never open the combobox
  // don't fire the extra request.  If the parent form seeds a
  // non-empty ``value``, we still preload so the exact-match
  // detection below fires immediately (for auto-fill purposes).
  useEffect(() => {
    if (!loaded && (open || (value || "").trim() !== "")) load();
  }, [open, value, loaded, load]);

  // Outside-click closes the dropdown.
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const typed = (value || "").trim();
  const filtered = useMemo(() => {
    const q = typed.toLowerCase();
    if (!q) return items.slice(0, 20);
    return items.filter((r) => (r.name || "").toLowerCase().includes(q)).slice(0, 20);
  }, [items, typed]);

  const exactMatch = useMemo(() => {
    const q = typed.toLowerCase();
    if (!q) return null;
    return items.find((r) => (r.name || "").toLowerCase() === q) || null;
  }, [items, typed]);

  const handleTextChange = useCallback((next) => {
    // Free-typing: bubble the raw name string, don't overwrite
    // parent price / category.  Parent decides how to treat
    // ``null`` on those keys (usually: preserve current state).
    onChange?.({ name: next, default_price: null, category: null });
  }, [onChange]);

  const handlePick = useCallback((row) => {
    onChange?.({
      name: row.name,
      default_price: Number.isFinite(row.default_price)
        ? row.default_price : null,
      category: row.category || null,
    });
    setOpen(false);
  }, [onChange]);

  const openAdd = useCallback(() => {
    setOpen(false);
    setShowAdd(true);
  }, []);

  const handleCreated = useCallback((created) => {
    setShowAdd(false);
    // Reload the list (cache invalidated inside create flow) so the
    // dropdown reflects the new row on next open.
    load();
    handlePick(created);
  }, [load, handlePick]);

  return (
    <div ref={wrapRef} className="relative" data-testid={testid}>
      <div className="relative">
        <Search
          size={14}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none"
          style={{ color: colors.searchIcon }}
        />
        <input
          type="text"
          value={value || ""}
          onChange={(e) => handleTextChange(e.target.value)}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          disabled={disabled}
          placeholder={placeholder}
          className="w-full text-sm rounded-lg py-2 pl-8 pr-3"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    color: colors.onSurface }}
          data-testid={`${testid}-input`}
          autoComplete="off"
        />
      </div>

      {open && !disabled ? (
        <div
          className="absolute z-[60] left-0 right-0 mt-1 rounded-lg overflow-hidden shadow-lg"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    maxHeight: 260, overflowY: "auto" }}
          data-testid={`${testid}-dropdown`}
        >
          {!loaded ? (
            <div className="px-3 py-2 text-xs"
                  style={{ color: colors.muted }}>
              Loading…
            </div>
          ) : null}
          {loaded && filtered.length === 0 && !typed ? (
            <div className="px-3 py-2 text-xs"
                  style={{ color: colors.muted }}
                  data-testid={`${testid}-empty`}>
              No master services yet. Start typing to add one.
            </div>
          ) : null}
          {filtered.map((row) => (
            <button
              key={row.id}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handlePick(row)}
              className="w-full text-left px-3 py-2 text-sm flex items-baseline justify-between hover:bg-slate-50"
              style={{ color: colors.onSurface,
                        borderBottom: `1px solid ${colors.border}` }}
              data-testid={`${testid}-option-${row.id}`}
            >
              <span className="font-semibold">{row.name}</span>
              <span className="ml-3 text-xs"
                     style={{ color: colors.muted }}>
                {row.category ? `${row.category} · ` : ""}
                ${Number(row.default_price || 0).toFixed(2)}
              </span>
            </button>
          ))}
          {typed && !exactMatch ? (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={openAdd}
              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-slate-50"
              style={{ color: colors.brand, fontWeight: 600 }}
              data-testid={`${testid}-add-prompt`}
            >
              <Plus size={14} />
              Add "{typed}" to Master Service List?
            </button>
          ) : null}
        </div>
      ) : null}

      {showAdd ? (
        <AddMasterServiceModal
          initialName={typed}
          initialDefaultPrice={defaultPriceHint}
          onCancel={() => setShowAdd(false)}
          onCreated={handleCreated}
        />
      ) : null}
    </div>
  );
}
