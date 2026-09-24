/**
 * Task E · Feb-2026 — NavyFilterBar
 * ─────────────────────────────────────────────────────────────────
 * Shared "navy chrome" filter/search bar for list pages.  Six
 * pages consume this: Customers, Invoices, Pricebook, Recurring
 * Jobs, Work Stream (Jobs), Payments Ledger.  Absorbs the
 * previously-inline Phase K52.1 navy strip from CustomersList +
 * InvoicesList so a single component is the source of truth.
 *
 * Compound-children API (matches shadcn ``<Select>`` / ``<Card>``):
 *
 *   <NavyFilterBar data-testid="foo-filters">
 *     <NavyFilterBar.Search
 *       value={q} onChange={setQ}
 *       placeholder="Search…"
 *       data-testid="foo-search"
 *       onClear={() => setQ("")}
 *     />
 *     <NavyFilterBar.Select
 *       value={status} onChange={setStatus}
 *       data-testid="foo-filter-status"
 *       ariaLabel="Filter by status"
 *     >
 *       <option value="">All statuses</option>
 *       <option value="open">Open</option>
 *     </NavyFilterBar.Select>
 *     <NavyFilterBar.Chip
 *       active={onlyMine} onClick={() => setOnlyMine((v) => !v)}
 *       data-testid="foo-filter-mine"
 *     >
 *       Mine only
 *     </NavyFilterBar.Chip>
 *     <NavyFilterBar.DatePicker
 *       label="Since"
 *       value={since} onChange={setSince}
 *       data-testid="foo-filter-since"
 *     />
 *     <NavyFilterBar.Combobox label="Customer" minWidth={180}>
 *       <CustomerCombobox … />
 *     </NavyFilterBar.Combobox>
 *   </NavyFilterBar>
 *
 * Prop conventions
 * ----------------
 *   • Every sub-primitive spreads ``...rest`` onto its internal
 *     control (native ``<input>`` / ``<select>`` / ``<button>``),
 *     so callers write native attributes (``data-testid``,
 *     ``aria-*``, etc.) directly in the JSX.  This preserves
 *     source-body grep tests that assert ``data-testid="…"``
 *     literals on the migrated pages, AND ships identical DOM to
 *     the pre-migration inline strip.
 *   • Every sub-primitive supports an optional ``label`` prop.
 *     When passed, a 10-px uppercase caption renders above the
 *     control (Work Stream layout parity).  When omitted, the
 *     control renders bare (Customers/Invoices layout parity).
 *
 * Styling contract (per Task E spec, decided in the halt-and-
 * report round):
 *
 *   • Container       navy bg (colors.nav.bg = "#1B1F5C"),
 *                     rounded-2xl, 1px subtle border
 *                     (colors.nav.border = "rgba(255,255,255,0.10)").
 *   • Search input    solid white card, PERMANENT blue border
 *                     (colors.inputBorder = "#3B82F6"), navy text
 *                     (colors.nav.bg used as the foreground).
 *   • Select / chip / date / combobox controls  →  navy bg,
 *                     white text, white/10 border. ``color-scheme:
 *                     dark`` on native pickers so browser chrome
 *                     (calendar icon, dropdown arrow) renders
 *                     readably against the navy fill.
 *   • Chip active     K52 gradient (colors.gradient.css) w/ white
 *                     text + subtle text-shadow.
 */
import React from "react";
import { Search as SearchIcon, X as XIcon } from "lucide-react";
import { colors } from "@/theme";


/* Internal helper — renders a small uppercase caption above the
 * control when ``label`` is passed, else just returns the control
 * unchanged. Kept private so consumers reach for it via the
 * sub-primitive ``label`` prop instead of composing directly. */
function _LabelWrap({ label, children }) {
  if (!label) return children;
  return (
    <div className="flex flex-col">
      <label
        className="text-[10px] font-bold uppercase mb-0.5"
        style={{ color: colors.nav.fg }}
      >
        {label}
      </label>
      {children}
    </div>
  );
}


export default function NavyFilterBar({ children, className = "", ...rest }) {
  return (
    <div
      className={`rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center ${className}`}
      style={{
        backgroundColor: colors.nav.bg,
        border: `1px solid ${colors.nav.border}`,
      }}
      data-navy-filter-bar="true"
      // ``...rest`` forwards data-testid, legacy marker attributes
      // (e.g. ``data-k52-navy-strip="true"`` on Customers/
      // Invoices), and arbitrary ARIA hooks without widening the
      // primitive's typed prop surface.
      {...rest}
    >
      {children}
    </div>
  );
}


NavyFilterBar.Search = function NavyFilterBarSearch({
  value,
  onChange,
  placeholder,
  ariaLabel,
  onClear,
  className = "",
  minWidth = 220,
  clearTestid,
  ...rest
}) {
  const inputTestid = rest["data-testid"];
  const showClear = typeof onClear === "function" && !!value;
  // Consumers can override the derived Clear-button testid via
  // ``clearTestid`` when the page's legacy testid diverges from
  // the ``{data-testid}-clear`` convention (e.g. RecurringJobs
  // ships ``recurring-search-clear`` alongside
  // ``recurring-search-input``).
  const resolvedClearTestid = clearTestid !== undefined
    ? clearTestid
    : (inputTestid ? `${inputTestid}-clear` : undefined);
  return (
    <div
      className={`relative flex-1 ${className}`}
      style={{ minWidth }}
    >
      <SearchIcon
        size={16}
        className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
        style={{ color: colors.inputBorder }}
        aria-hidden="true"
      />
      <input
        type="search"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="w-full pl-9 pr-8 py-2.5 rounded-lg outline-none text-sm"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.inputBorder}`,
          color: colors.nav.bg,
        }}
        {...rest}
      />
      {showClear ? (
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear search"
          data-testid={resolvedClearTestid}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded hover:opacity-70"
        >
          <XIcon size={13} style={{ color: colors.nav.bg }} />
        </button>
      ) : null}
    </div>
  );
};


NavyFilterBar.Select = function NavyFilterBarSelect({
  value,
  onChange,
  label,
  ariaLabel,
  children,
  minWidth,
  className = "",
  ...rest
}) {
  const control = (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      className={`text-xs font-semibold px-3 py-2 rounded-lg outline-none ${className}`}
      style={{
        backgroundColor: colors.nav.bg,
        color: colors.nav.fg,
        border: `1px solid ${colors.nav.border}`,
        minWidth: minWidth || undefined,
        colorScheme: "dark",
      }}
      {...rest}
    >
      {children}
    </select>
  );
  return <_LabelWrap label={label}>{control}</_LabelWrap>;
};


NavyFilterBar.Chip = function NavyFilterBarChip({
  active,
  onClick,
  ariaLabel,
  children,
  label,
  className = "",
  ...rest
}) {
  const control = (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active ? "true" : "false"}
      aria-label={ariaLabel}
      className={`text-xs font-semibold px-3 py-1.5 rounded-full transition inline-flex items-center gap-1.5 ${className}`}
      style={{
        background: active ? colors.gradient.css : "transparent",
        color: colors.nav.fg,
        border: `1px solid ${active ? "transparent" : colors.nav.fgMuted}`,
        textShadow: active ? colors.gradient.textShadow : undefined,
      }}
      {...rest}
    >
      {children}
    </button>
  );
  return <_LabelWrap label={label}>{control}</_LabelWrap>;
};


NavyFilterBar.DatePicker = function NavyFilterBarDatePicker({
  value,
  onChange,
  label,
  ariaLabel,
  className = "",
  ...rest
}) {
  const control = (
    <input
      type="date"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      className={`text-sm px-3 py-1.5 rounded-lg outline-none ${className}`}
      style={{
        backgroundColor: colors.nav.bg,
        color: colors.nav.fg,
        border: `1px solid ${colors.nav.border}`,
        colorScheme: "dark",
      }}
      {...rest}
    />
  );
  return <_LabelWrap label={label}>{control}</_LabelWrap>;
};


NavyFilterBar.Combobox = function NavyFilterBarCombobox({
  label,
  minWidth = 180,
  children,
  className = "",
}) {
  const control = (
    <div className={className} style={{ minWidth }}>
      {children}
    </div>
  );
  return <_LabelWrap label={label}>{control}</_LabelWrap>;
};
