/**
 * Phase 15b · Feb-2026 — Customer tag picker with inline "add new" affordance.
 *
 * Props:
 *   customerId    — string, target customer id
 *   value         — string[], the customer's current tags (controlled)
 *   onChange      — (nextTags: string[]) => void, fires after a
 *                   successful PATCH so the parent can update its cache
 *   readOnly?     — boolean, hides the "add" trigger when true
 *
 * Behavior:
 *   • Trigger button opens a shadcn Popover containing a Command
 *     search box + list of registry tags.
 *   • The user can type to filter.
 *   • If the typed string exactly matches an existing tag it's added
 *     via a plain click on the row (no "add new" affordance).
 *   • If it has zero exact matches (case-insensitive) an
 *     "+ Add new tag: '<typed>'" row appears at the bottom of the
 *     list; clicking it POSTs to `/customer-tags` (which is idempotent
 *     server-side) and then PATCHes the customer.
 *   • Existing tag chips render inline with a "×" remove button.
 *   • RBAC — server enforces admin/manager; the trigger UI still
 *     renders for other roles but the API will reject their write.
 *     The parent should hide the picker for read-only surfaces.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import {
  Popover, PopoverContent, PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command, CommandInput, CommandList, CommandEmpty, CommandGroup,
  CommandItem,
} from "@/components/ui/command";

function tagColor(name, palette) {
  // Deterministic palette pick — same name → same color across
  // renders. Mirrors the server-side _pick_color helper so a tag
  // shown here matches its stored color once it round-trips.
  let h = 0;
  const s = (name || "").trim().toLowerCase();
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return palette[h % palette.length];
}

const _DEFAULT_PALETTE = [
  "#DBEAFE", "#FEE2E2", "#DCFCE7", "#FEF3C7", "#EDE9FE",
  "#CFFAFE", "#FCE7F3", "#FEDCBB", "#E0E7FF", "#D1FAE5",
];

export default function CustomerTagPicker({
  customerId, value, onChange, readOnly = false,
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [registry, setRegistry] = useState([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const selected = useMemo(
    () => Array.isArray(value) ? value : [],
    [value]
  );

  // Fetch registry on open.
  useEffect(() => {
    if (!open) return;
    api.get("/customer-tags").then((r) => {
      setRegistry(Array.isArray(r?.items) ? r.items : []);
    }).catch(() => setRegistry([]));
  }, [open]);

  const registryByLow = useMemo(() => {
    const m = new Map();
    registry.forEach((t) => m.set((t.name || "").toLowerCase(), t));
    return m;
  }, [registry]);

  // Registry rows minus already-selected ones (case-insensitive).
  const selectedLows = useMemo(
    () => new Set(selected.map((s) => s.toLowerCase())),
    [selected]
  );
  const remaining = useMemo(
    () => registry.filter((t) => !selectedLows.has((t.name || "").toLowerCase())),
    [registry, selectedLows]
  );

  // Filter by search string (substring, case-insensitive).
  const q = search.trim().toLowerCase();
  const filtered = q
    ? remaining.filter((t) => (t.name || "").toLowerCase().includes(q))
    : remaining;

  // Determine whether to show the "+ Add new tag" row: only when
  // the user has typed something AND that string doesn't already
  // exactly match a selectable tag (either in the registry or the
  // current selection).
  const trimmed = search.trim();
  const exactExists = trimmed && (
    selectedLows.has(trimmed.toLowerCase())
      || registryByLow.has(trimmed.toLowerCase())
  );
  const showAddNew = !!trimmed && !exactExists;

  async function commit(nextTags) {
    setBusy(true);
    try {
      const res = await api.patch(`/customers/${customerId}/tags`, {
        tags: nextTags,
      });
      onChange?.(res?.tags || nextTags);
    } finally {
      setBusy(false);
    }
  }

  const addTag = async (name) => {
    const t = (name || "").trim();
    if (!t) return;
    if (selectedLows.has(t.toLowerCase())) return;
    const next = [...selected, t];
    await commit(next);
    setSearch("");
    // Refresh the registry once so the newly-created tag shows up.
    api.get("/customer-tags").then((r) => {
      setRegistry(Array.isArray(r?.items) ? r.items : []);
    });
  };

  const removeTag = async (name) => {
    const next = selected.filter((t) => t !== name);
    await commit(next);
  };

  return (
    <div
      className="flex items-center flex-wrap gap-1.5"
      data-testid="customer-tag-picker"
    >
      {selected.map((t) => {
        const reg = registryByLow.get(t.toLowerCase());
        const color = reg?.color || tagColor(t, _DEFAULT_PALETTE);
        return (
          <span
            key={t}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold"
            style={{ background: color, color: "#111827" }}
            data-testid={`customer-tag-chip-${t}`}
          >
            {t}
            {!readOnly && (
              <button
                type="button"
                onClick={() => removeTag(t)}
                className="ml-0.5 opacity-60 hover:opacity-100"
                aria-label={`Remove tag ${t}`}
                data-testid={`customer-tag-remove-${t}`}
              >
                <X size={11} />
              </button>
            )}
          </span>
        );
      })}

      {!readOnly && (
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              data-testid="customer-tag-picker-trigger"
            >
              <Plus size={12} className="mr-1" />
              Tag
            </Button>
          </PopoverTrigger>
          <PopoverContent
            className="w-64 p-0"
            align="start"
            data-testid="customer-tag-picker-popover"
          >
            <Command shouldFilter={false}>
              <CommandInput
                ref={inputRef}
                value={search}
                onValueChange={setSearch}
                placeholder="Search or add a tag…"
                data-testid="customer-tag-picker-search"
              />
              <CommandList data-testid="customer-tag-picker-list">
                {filtered.length === 0 && !showAddNew ? (
                  <CommandEmpty>No tags found.</CommandEmpty>
                ) : null}
                {filtered.length > 0 ? (
                  <CommandGroup heading="Existing tags">
                    {filtered.map((t) => (
                      <CommandItem
                        key={t.id}
                        value={t.name}
                        onSelect={() => { addTag(t.name); }}
                        data-testid={`customer-tag-option-${t.name}`}
                      >
                        <span
                          className="w-2.5 h-2.5 rounded-full mr-2 shrink-0"
                          style={{ background: t.color || tagColor(t.name, _DEFAULT_PALETTE) }}
                        />
                        <span className="flex-1">{t.name}</span>
                        {typeof t.usage_count === "number" && t.usage_count > 0 ? (
                          <span
                            className="text-[10px] opacity-60"
                            style={{ color: colors.muted }}
                          >
                            ×{t.usage_count}
                          </span>
                        ) : null}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ) : null}
                {showAddNew ? (
                  <CommandGroup heading="Create new">
                    <CommandItem
                      value={`__addnew__${trimmed}`}
                      onSelect={() => { addTag(trimmed); }}
                      data-testid="customer-tag-add-new"
                      className="text-emerald-700 font-semibold"
                    >
                      <Plus size={13} className="mr-1.5" />
                      Add new tag: &ldquo;{trimmed}&rdquo;
                    </CommandItem>
                  </CommandGroup>
                ) : null}
              </CommandList>
            </Command>
            {busy ? (
              <div
                className="text-[11px] px-2 py-1 border-t"
                style={{ color: colors.muted, borderColor: colors.border }}
              >
                Saving…
              </div>
            ) : null}
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
