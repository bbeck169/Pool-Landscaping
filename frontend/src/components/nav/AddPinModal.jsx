/**
 * Phase K75 · Step B · Feb-2026 — Add-pin modal.
 *
 * Searchable tree grouped by category. Each row shows icon +
 * label + full route path. Rows already in the caller's pin
 * list are rendered disabled with a "Pinned" badge. The 15-pin
 * cap is enforced in the header — when at cap, every row is
 * disabled with a top-of-modal notice.
 */
import React, { useMemo, useState } from "react";
import { X, Search, Check } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { pinPickerForRole } from "@/nav/pinRegistry";
import { resolveIcon } from "@/nav/lucideIcons";
import { colors } from "@/theme";


export default function AddPinModal({
  open,
  onOpenChange,
  role,
  pinnedRoutes,     // Set<string>
  atCap,
  cap,
  onAdd,            // (pin) => Promise<{ok, code?}>
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(null); // ``to`` currently being added
  const [errCode, setErrCode] = useState(null);

  const groups = useMemo(() => pinPickerForRole(role), [role]);

  const filtered = useMemo(() => {
    if (!q.trim()) return groups;
    const needle = q.trim().toLowerCase();
    return groups
      .map((g) => ({
        ...g,
        entries: g.entries.filter(
          (e) =>
            e.label.toLowerCase().includes(needle) ||
            e.to.toLowerCase().includes(needle),
        ),
      }))
      .filter((g) => g.entries.length > 0);
  }, [groups, q]);

  const handleAdd = async (entry) => {
    setBusy(entry.to);
    setErrCode(null);
    const res = await onAdd({
      to: entry.to,
      label: entry.label,
      iconKey: entry.iconKey,
    });
    setBusy(null);
    if (!res?.ok) {
      setErrCode(res?.code || "add_failed");
      return;
    }
    // Success — keep the modal open for chained adds (the row becomes
    // "Pinned" via ``pinnedRoutes`` recomputation upstream).
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl max-h-[80vh] p-0 gap-0 overflow-hidden"
        data-testid="add-pin-modal"
      >
        <DialogHeader className="p-5 pb-3 border-b">
          <div className="flex items-center justify-between">
            <DialogTitle
              className="text-lg font-semibold"
              data-testid="add-pin-modal-title"
            >
              Add a Quick Access pin
            </DialogTitle>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="p-1 rounded hover:bg-gray-100"
              aria-label="Close add-pin modal"
              data-testid="add-pin-modal-close"
            >
              <X size={18} />
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {pinnedRoutes.size} of {cap} pins in use
            {atCap ? " — remove one before adding another" : ""}
          </p>
          <div className="mt-3 relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search routes..."
              className="pl-8 h-9 text-sm"
              data-testid="add-pin-modal-search"
              autoFocus
            />
          </div>
          {atCap ? (
            <div
              className="mt-2 rounded-md px-3 py-2 text-xs font-medium"
              style={{
                backgroundColor: "#FEF3C7",
                color: "#92400E",
                border: "1px solid #FDE68A",
              }}
              data-testid="add-pin-modal-at-cap"
            >
              You've hit the {cap}-pin cap. Remove a pin before adding a new one.
            </div>
          ) : null}
          {errCode ? (
            <div
              className="mt-2 rounded-md px-3 py-2 text-xs font-medium"
              style={{
                backgroundColor: "#FEE2E2",
                color: "#991B1B",
                border: "1px solid #FCA5A5",
              }}
              data-testid="add-pin-modal-error"
            >
              {errCode === "pin_cap_exceeded"
                ? "Pin cap reached — remove a pin first."
                : errCode === "duplicate_pin"
                ? "That route is already pinned."
                : errCode === "wrong_role_route"
                ? "Your role can't pin that route."
                : errCode === "icon_not_whitelisted"
                ? "Icon not in K75 whitelist."
                : `Failed to add pin (${errCode})`}
            </div>
          ) : null}
        </DialogHeader>

        <div
          className="overflow-y-auto flex-1"
          style={{ maxHeight: "50vh" }}
          data-testid="add-pin-modal-body"
        >
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-sm text-gray-500"
                 data-testid="add-pin-modal-empty">
              No routes match "{q}".
            </div>
          ) : (
            filtered.map((g) => (
              <div key={g.key} className="px-3 pt-3 pb-1">
                <div className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 px-2 pb-1"
                     data-testid={`add-pin-modal-group-${g.key}`}>
                  {g.label}
                </div>
                <ul className="space-y-0.5">
                  {g.entries.map((e) => {
                    const isPinned = pinnedRoutes.has(e.to);
                    const disabled = isPinned || atCap || busy === e.to;
                    const Icon = resolveIcon(e.iconKey);
                    const tid = `add-pin-row-${e.to.replaceAll("/", "_").replaceAll("?", "_")}`;
                    return (
                      <li key={e.to}>
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => handleAdd(e)}
                          className={[
                            "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-left",
                            disabled
                              ? "opacity-50 cursor-not-allowed"
                              : "hover:bg-gray-100 cursor-pointer",
                          ].join(" ")}
                          data-testid={tid}
                          data-pinned={isPinned ? "true" : "false"}
                        >
                          <Icon size={14} className="opacity-70 shrink-0" />
                          <span className="flex-1 min-w-0 truncate">{e.label}</span>
                          <span className="text-[10px] text-gray-400 font-mono truncate max-w-[40%]">
                            {e.to}
                          </span>
                          {isPinned ? (
                            <span
                              className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                              style={{ backgroundColor: colors.nav.bgActiveNavy, color: "#fff" }}
                              data-testid={`${tid}-badge`}
                            >
                              <Check size={10} className="inline -mt-[1px] mr-0.5" />
                              Pinned
                            </span>
                          ) : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </div>

        <DialogFooter className="p-3 border-t bg-gray-50 flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            data-testid="add-pin-modal-done"
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
