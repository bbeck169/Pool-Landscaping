/**
 * Feb-2026 · CustomerCombobox
 * ─────────────────────────────────────────────────────────────────
 * Searchable customer picker for forms across the app. Replaces
 * every raw ``<select>`` + ``customers.map`` pattern that used to
 * live inline in New Job / New Estimate / New Invoice / Recurring
 * Jobs / etc.
 *
 * Extraction context: the New Job form on prod had ~hundreds of
 * customers in a native ``<select>`` — unscrollable in practice.
 * This component swaps that for a shadcn ``Popover`` + ``Command``
 * (cmdk) combobox: search input at top, filtered list, keyboard
 * nav, empty-state, active-check indicator.
 *
 * Deliberately caller-fetches the customer list (rather than an
 * internal ``autoFetch`` prop) — every caller already owns customer
 * state for other reasons (property autoload, warranty scope, etc.)
 * and forking an internal fetch would double-load the roster.
 *
 * Props:
 *   value        (string)   — currently-selected ``customer.id``
 *   onChange     (fn)       — called with the newly-selected id
 *   customers    (array)    — [{id, name, ...}], caller-owned.
 *                              Callers SHOULD pass ``is_active=true``
 *                              on the fetch so inactive rows never
 *                              surface (backend supports the filter).
 *   testid       (str)      — default ``"customer-combobox"``;
 *                              trigger uses this exact string,
 *                              search input becomes ``{testid}-search``,
 *                              rows become ``{testid}-item-{id}``.
 *   placeholder  (str)      — default ``"Choose a customer…"``.
 *   disabled     (bool)     — greys the trigger and blocks open.
 *   filter       (fn|null)  — optional predicate ``(customer) => bool``
 *                              for callers that need extra client-side
 *                              scoping (e.g. limit to warranty-owning
 *                              customers).
 *   children     (React)    — rendered inside the popover BEFORE the
 *                              command list. Use for a "+ New customer"
 *                              quick-create button that some forms
 *                              render alongside the picker.
 */

import React from "react";
import { ChevronsUpDown, Check } from "lucide-react";
import { colors } from "@/theme";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";


// Feb-2026 · Backlog Item 5 — local phone display helper. Reuses
// the E.164 → ``(XXX) XXX-XXXX`` transform the app already applies
// elsewhere (see ``PhoneInput.jsx``, ``customers/CustomerDetail``).
// Kept in-file to avoid a fresh import graph edge for one call site.
function _formatPhone(raw) {
  if (!raw) return "";
  const digits = String(raw).replace(/\D+/g, "");
  // 11-digit US with leading 1 → strip prefix.
  const usDigits = digits.length === 11 && digits.startsWith("1")
    ? digits.slice(1)
    : digits;
  if (usDigits.length === 10) {
    return `(${usDigits.slice(0, 3)}) ${usDigits.slice(3, 6)}-${usDigits.slice(6)}`;
  }
  return String(raw);
}

export function CustomerCombobox({
  value,
  onChange,
  customers,
  testid = "customer-combobox",
  placeholder = "Choose a customer…",
  disabled = false,
  filter = null,
  children = null,
}) {
  const [open, setOpen] = React.useState(false);
  const list = React.useMemo(() => {
    const base = Array.isArray(customers) ? customers : [];
    return typeof filter === "function" ? base.filter(filter) : base;
  }, [customers, filter]);
  const selected = React.useMemo(
    () => list.find((c) => c.id === value) || null,
    [list, value],
  );

  return (
    <Popover open={open} onOpenChange={disabled ? () => {} : setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className="w-full px-3.5 py-2.5 rounded-lg text-sm text-left flex items-center justify-between gap-2 focus:outline-none focus:ring-2"
          style={{
            backgroundColor: colors.surface,
            color: selected ? colors.onSurface : colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
            opacity: disabled ? 0.6 : 1,
            cursor: disabled ? "not-allowed" : "pointer",
          }}
          data-testid={testid}
        >
          <span className="truncate">
            {selected ? selected.name : placeholder}
          </span>
          <ChevronsUpDown size={14} className="shrink-0 opacity-60" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0 w-[--radix-popover-trigger-width] min-w-[280px]"
        data-testid={`${testid}-popover`}
      >
        {children}
        <Command>
          <CommandInput
            placeholder="Search customers…"
            data-testid={`${testid}-search`}
          />
          <CommandList>
            <CommandEmpty>No customers found.</CommandEmpty>
            {list.map((c) => {
              // Feb-2026 · Backlog Item 5 — auxiliary email/phone
              // subtitle. Disambiguates duplicate customer names
              // (e.g. the two "Mike Rivera" records that surfaced
              // on Feb-2026 P0 dedupe). Renders nothing when neither
              // field is populated so single-value customers stay
              // clean. Search value carries email + phone into the
              // cmdk filter so admins can type an email to jump to
              // the right row.
              const emailStr = (c.email || "").trim();
              const phoneStr = _formatPhone(c.phone || c.primary_phone || "");
              const hasAux = Boolean(emailStr) || Boolean(phoneStr);
              const auxCopy = [emailStr, phoneStr].filter(Boolean).join(" · ");
              const searchValue = [c.name, emailStr, phoneStr]
                .filter(Boolean).join(" ");
              return (
                <CommandItem
                  key={c.id}
                  value={searchValue}
                  onSelect={() => {
                    onChange(c.id);
                    setOpen(false);
                  }}
                  data-testid={`${testid}-item-${c.id}`}
                >
                  <Check
                    size={14}
                    className={
                      "mr-2 " + (c.id === value ? "opacity-100" : "opacity-0")
                    }
                  />
                  <div className="flex flex-col min-w-0">
                    <span className="truncate" data-testid={`${testid}-item-${c.id}-name`}>
                      {c.name}
                    </span>
                    {hasAux ? (
                      <span
                        className="text-xs truncate"
                        style={{ color: colors.muted }}
                        data-testid={`${testid}-item-${c.id}-aux`}
                      >
                        {auxCopy}
                      </span>
                    ) : null}
                  </div>
                </CommandItem>
              );
            })}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

export default CustomerCombobox;
