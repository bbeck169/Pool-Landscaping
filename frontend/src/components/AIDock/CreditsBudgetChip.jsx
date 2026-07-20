/**
 * CreditsBudgetChip — Feb-2026
 *
 * Compact live-balance pill for the admin top bar. Reads
 * `GET /api/ai-credits/balance` on mount + on tab-visibility
 * changes, colour-codes the balance, and deep-links into the AI
 * Employees Dock drawer via the `ai-dock:open` window event when
 * clicked.
 *
 * Role gate: renders `null` for non-admins. The chip is admin-only
 * because the underlying endpoint is admin-only (see
 * ``tests/test_ai_employees_rbac.py``) — any non-admin render would
 * only produce a 403 on the network tab. Belt-and-braces gate.
 */
import React from "react";
import { Sparkles } from "lucide-react";
import { api } from "@/api";
import { usePermissions } from "@/hooks/usePermissions";

const RED_THRESHOLD = 100;
const AMBER_THRESHOLD = 500;

function tierFor(balance) {
  if (balance == null) return { tone: "muted", label: "AI credits — loading" };
  if (balance < RED_THRESHOLD) {
    return {
      tone: "red",
      bg: "#fee2e2",
      fg: "#991b1b",
      label: `${balance} credits · critical — top up soon`,
    };
  }
  if (balance < AMBER_THRESHOLD) {
    return {
      tone: "amber",
      bg: "#fef3c7",
      fg: "#92400e",
      label: `${balance} credits · low — approaching throttle`,
    };
  }
  return {
    tone: "green",
    bg: "#dcfce7",
    fg: "#166534",
    label: `${balance} credits · healthy`,
  };
}

export default function CreditsBudgetChip() {
  const { effectiveRole } = usePermissions();
  const [balance, setBalance] = React.useState(null);

  const isAdmin = effectiveRole === "admin" || effectiveRole === "super_admin";

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/ai-credits/balance");
      setBalance(typeof r?.balance === "number" ? r.balance : null);
    } catch {
      setBalance(null);
    }
  }, []);

  React.useEffect(() => {
    if (!isAdmin) return undefined;
    load();
    const onVis = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [isAdmin, load]);

  if (!isAdmin) return null;

  const tier = tierFor(balance);
  const open = () => {
    try {
      window.dispatchEvent(new CustomEvent("ai-dock:open"));
    } catch { /* no-op */ }
  };

  return (
    <button
      type="button"
      onClick={open}
      title={tier.label}
      className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-xs font-semibold whitespace-nowrap transition hover:opacity-90"
      style={{
        backgroundColor: tier.bg || "#e5e7eb",
        color: tier.fg || "#374151",
      }}
      data-testid="credits-budget-chip"
      data-tier={tier.tone}
      data-balance={balance == null ? "" : String(balance)}
    >
      <Sparkles size={12} />
      <span>{balance == null ? "—" : `${balance}c`}</span>
    </button>
  );
}
