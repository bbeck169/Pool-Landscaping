/**
 * Phase 2 B2 · Feb-2026 · QuoteRecipientPicker
 * ─────────────────────────────────────────────────────────────────
 * Unified picker that accepts either a Customer OR a Lead as a
 * quote recipient. Hits GET /api/quote-recipients/search; renders
 * search results with per-row "Customer" / "Lead" badges.
 *
 * Props:
 *   value       {type:"customer"|"lead", id, name} | null
 *   onChange    fn({type,id,name}) — fired on pick (or clear).
 *   testid      default "quote-recipient-picker"
 *   placeholder
 *   disabled
 */
import React from "react";
import { ChevronsUpDown, Check } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
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

const BADGE_COPY = { customer: "Customer", lead: "Lead" };
const BADGE_BG = { customer: "#DBEAFE", lead: "#FEF3C7" };
const BADGE_FG = { customer: "#1E40AF", lead: "#92400E" };

export function RecipientTypeBadge({ type, testid }) {
  const kind = type === "lead" ? "lead" : "customer";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 0.4,
        borderRadius: 999,
        background: BADGE_BG[kind],
        color: BADGE_FG[kind],
        textTransform: "uppercase",
      }}
      data-testid={testid}
      data-recipient-type={kind}
    >
      {BADGE_COPY[kind]}
    </span>
  );
}

export function QuoteRecipientPicker({
  value,
  onChange,
  testid = "quote-recipient-picker",
  placeholder = "Choose a customer or lead…",
  disabled = false,
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const rows = await api.get(
          `/quote-recipients/search?q=${encodeURIComponent(query || "")}&limit=20`,
        );
        if (!cancelled) setResults(Array.isArray(rows) ? rows : []);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 180);
    return () => { cancelled = true; clearTimeout(t); };
  }, [open, query]);

  const selectedLabel = value && value.id
    ? value.name || value.id
    : placeholder;

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
            color: value?.id ? colors.onSurface : colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
            opacity: disabled ? 0.6 : 1,
            cursor: disabled ? "not-allowed" : "pointer",
          }}
          data-testid={testid}
          data-recipient-type={value?.type || ""}
        >
          <span className="truncate flex items-center gap-2 min-w-0">
            {value?.id ? (
              <RecipientTypeBadge
                type={value.type}
                testid={`${testid}-selected-badge`}
              />
            ) : null}
            <span className="truncate">{selectedLabel}</span>
          </span>
          <ChevronsUpDown size={14} className="shrink-0 opacity-60" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0 w-[--radix-popover-trigger-width] min-w-[320px]"
        data-testid={`${testid}-popover`}
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Search customers or leads…"
            value={query}
            onValueChange={setQuery}
            data-testid={`${testid}-search`}
          />
          <CommandList>
            {loading ? (
              <div
                className="px-3 py-2 text-xs"
                style={{ color: colors.muted }}
                data-testid={`${testid}-loading`}
              >
                Searching…
              </div>
            ) : null}
            <CommandEmpty data-testid={`${testid}-empty`}>
              No matches.
            </CommandEmpty>
            {results.map((r) => {
              const kind = r.kind === "lead" ? "lead" : "customer";
              const aux = [r.email, r.phone].filter(Boolean).join(" · ");
              const selected = value?.id === r.id && value?.type === kind;
              return (
                <CommandItem
                  key={`${kind}-${r.id}`}
                  value={`${r.display_name || ""} ${r.email || ""} ${r.phone || ""}`}
                  onSelect={() => {
                    onChange?.({
                      type: kind,
                      id: r.id,
                      name: r.display_name || "",
                    });
                    setOpen(false);
                  }}
                  data-testid={`${testid}-item-${kind}-${r.id}`}
                >
                  <Check
                    size={14}
                    className={"mr-2 " + (selected ? "opacity-100" : "opacity-0")}
                  />
                  <div className="flex flex-col min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <RecipientTypeBadge
                        type={kind}
                        testid={`${testid}-item-${kind}-${r.id}-badge`}
                      />
                      <span className="truncate font-medium">
                        {r.display_name || "(unnamed)"}
                      </span>
                    </div>
                    {aux ? (
                      <span
                        className="text-xs truncate"
                        style={{ color: colors.muted }}
                      >
                        {aux}
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

export default QuoteRecipientPicker;
