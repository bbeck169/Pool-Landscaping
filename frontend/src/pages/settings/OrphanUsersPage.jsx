import React from "react";
import { toast } from "sonner";
import { RefreshCw, Wrench, AlertTriangle, Check, ShieldAlert } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * Feb-2026 · Super-admin surface for orphan customer auth users.
 *
 * Backend:
 *   GET  /api/admin/orphan-customer-users
 *   POST /api/admin/users/{uid}/create-customer-record
 *
 * An orphan is a ``role=customer`` auth user whose ``customer_id`` is
 * missing (never linked) OR points at a customer record that no
 * longer exists in the tenant's ``customers`` collection. The repair
 * endpoint is idempotent — if the link already resolves it short-
 * circuits with ``was_already_linked: true``.
 *
 * Route: ``/settings/orphan-users`` — super_admin only (see App.js).
 */
export default function OrphanUsersPage() {
  const [rows, setRows] = React.useState(null); // null=loading, [] loaded
  const [busyId, setBusyId] = React.useState(null);
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setError("");
    try {
      const res = await api.get("/admin/orphan-customer-users");
      setRows(Array.isArray(res?.users) ? res.users : []);
    } catch (e) {
      setError(e?.message || "Failed to load orphan users");
      setRows([]);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const repair = async (u) => {
    setBusyId(u.id);
    try {
      const res = await api.post(`/admin/users/${u.id}/create-customer-record`);
      if (res?.was_already_linked) {
        toast.message("Already linked — no changes needed", {
          description: `${u.email} → customer ${res.customer_id}`,
        });
      } else {
        toast.success("Customer record created", {
          description: `${u.email} → customer ${res.customer_id}`,
        });
      }
      // Drop the repaired row from the list without a full refetch so
      // the UI feels instant. A subsequent refresh will confirm.
      setRows((prev) => (prev || []).filter((x) => x.id !== u.id));
    } catch (e) {
      toast.error(e?.message || "Repair failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <SafeScrollContainer
      className="p-6 max-w-4xl mx-auto"
      data-testid="orphan-users-page"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h1
            className="text-2xl font-bold mb-1 flex items-center gap-2"
            style={{ color: colors.onSurface }}
            data-testid="orphan-users-title"
          >
            <ShieldAlert size={22} color="#B45309" />
            Orphan auth users
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Customer accounts that lost their linked customer record. Click{" "}
            <b>Repair</b> to rebuild the link from the auth user's fields.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 h-[38px] rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
          data-testid="orphan-users-refresh"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error ? (
        <div
          className="rounded-xl p-4 mb-4 flex items-start gap-2"
          style={{
            backgroundColor: "#FEF3C7",
            color: "#92400E",
            border: "1px solid #FDE68A",
          }}
          data-testid="orphan-users-error"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <div className="text-sm">
            <div className="font-semibold">Could not load orphan users.</div>
            <div>{error}</div>
          </div>
        </div>
      ) : null}

      {rows === null ? (
        <div
          className="h-40 rounded-2xl animate-pulse"
          style={{ backgroundColor: colors.surfaceSecondary }}
          data-testid="orphan-users-loading"
        />
      ) : rows.length === 0 ? (
        <div
          className="rounded-2xl p-8 text-center"
          style={{
            backgroundColor: colors.surface,
            border: `1px dashed ${colors.border}`,
          }}
          data-testid="orphan-users-empty"
        >
          <div
            className="w-12 h-12 rounded-full mx-auto mb-3 flex items-center justify-center"
            style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
          >
            <Check size={22} />
          </div>
          <div className="font-semibold" style={{ color: colors.onSurface }}>
            No orphan users
          </div>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            Every customer auth account is linked to a real customer record.
          </div>
        </div>
      ) : (
        <ul className="space-y-2" data-testid="orphan-users-list">
          {rows.map((u) => (
            <OrphanRow
              key={u.id}
              user={u}
              busy={busyId === u.id}
              onRepair={() => repair(u)}
            />
          ))}
        </ul>
      )}
    </SafeScrollContainer>
  );
}


function OrphanRow({ user, busy, onRepair }) {
  const reasonLabel =
    user.reason === "missing_customer_id"
      ? "No linked customer_id"
      : user.reason === "stale_customer_id"
      ? "Stale customer_id"
      : "Orphaned";
  const reasonBg =
    user.reason === "stale_customer_id" ? "#FEE2E2" : "#FEF3C7";
  const reasonFg =
    user.reason === "stale_customer_id" ? "#991B1B" : "#92400E";

  return (
    <li
      className="rounded-xl p-4 flex items-center gap-4 flex-wrap sm:flex-nowrap"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={`orphan-users-row-${user.id}`}
    >
      <div className="flex-1 min-w-0">
        <div
          className="font-semibold truncate"
          style={{ color: colors.onSurface }}
          data-testid={`orphan-users-name-${user.id}`}
        >
          {user.name || user.email || "—"}
        </div>
        <div
          className="text-xs truncate"
          style={{ color: colors.muted }}
          data-testid={`orphan-users-email-${user.id}`}
        >
          {user.email}
          {user.phone ? <span> · {user.phone}</span> : null}
        </div>
        {user.tenant_id ? (
          <div
            className="text-[11px] mt-1 font-mono"
            style={{ color: colors.muted }}
            data-testid={`orphan-users-tenant-${user.id}`}
          >
            tenant: {user.tenant_id}
          </div>
        ) : null}
      </div>
      <span
        className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded whitespace-nowrap"
        style={{ backgroundColor: reasonBg, color: reasonFg }}
        data-testid={`orphan-users-reason-${user.id}`}
      >
        {reasonLabel}
      </span>
      <button
        type="button"
        onClick={onRepair}
        disabled={busy}
        className="inline-flex items-center gap-1.5 px-4 h-[38px] rounded-lg text-sm font-bold text-white disabled:opacity-60 disabled:cursor-not-allowed"
        style={{ backgroundColor: colors.brand }}
        data-testid={`orphan-users-repair-${user.id}`}
      >
        <Wrench size={14} />
        {busy ? "Repairing…" : "Repair"}
      </button>
    </li>
  );
}
