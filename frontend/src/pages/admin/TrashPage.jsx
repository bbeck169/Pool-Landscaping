/**
 * HARD-DELETE · HD-A · Feb-2026 — Admin Trash page.
 *
 * Lists every soft-deleted row across the seven eligible entity
 * types (customer, job, quote, service_report, file). Admin +
 * super_admin can Restore. Only super_admin sees the Purge action
 * (backend also enforces).
 *
 * Two supporting actions from the same page:
 *   • "Run nightly purge dry-run" — super_admin only. Preview which
 *     rows the nightly worker would sweep.
 *   • "Run nightly purge now" — super_admin only. Fires the sweep
 *     immediately for retention-window cleanup.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Trash2, RotateCcw, Flame, RefreshCw, Play } from "lucide-react";

import { api } from "@/api";

const ENTITY_LABELS = {
  customer: "Customers",
  job: "Jobs",
  quote: "Estimates / Invoices",
  service_report: "Service Reports",
  file: "Attachments",
};

function displayName(row) {
  return (
    row.name ||
    row.title ||
    row.invoice_number ||
    row.quote_number ||
    row.filename ||
    row.id
  );
}

export default function TrashPage() {
  const [rows, setRows] = useState(null);
  const [entityFilter, setEntityFilter] = useState("");
  const [me, setMe] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [confirmPurge, setConfirmPurge] = useState(null); // {row, skipTrash}
  const [purgeReason, setPurgeReason] = useState("");
  const [nightlyResult, setNightlyResult] = useState(null);

  const isSuper = (me?.role || "").toLowerCase() === "super_admin";

  const load = useCallback(async () => {
    setRows(null);
    try {
      const params = entityFilter ? `?entity_type=${entityFilter}` : "";
      const res = await api.get(`/hard-delete/trash${params}`);
      setRows(res.items || []);
    } catch (e) {
      toast.error(`Failed to load Trash: ${e.message || e}`);
      setRows([]);
    }
  }, [entityFilter]);

  useEffect(() => {
    api
      .get("/auth/me")
      .then((u) => setMe(u))
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const restore = async (row) => {
    setBusyId(row.id);
    try {
      await api.post(
        `/hard-delete/${row.entity_type}/${row.id}/restore`,
        null
      );
      toast.success(`Restored ${ENTITY_LABELS[row.entity_type] || row.entity_type}`);
      await load();
    } catch (e) {
      toast.error(`Restore failed: ${e.message || e}`);
    } finally {
      setBusyId(null);
    }
  };

  const purge = async () => {
    if (!confirmPurge) return;
    const { row, skipTrash } = confirmPurge;
    setBusyId(row.id);
    try {
      await api.post(`/hard-delete/${row.entity_type}/${row.id}/purge`, {
        reason: purgeReason || null,
        skip_trash: !!skipTrash,
      });
      toast.success("Purged permanently — tombstone written");
      setConfirmPurge(null);
      setPurgeReason("");
      await load();
    } catch (e) {
      const detail = e?.detail || e?.message || String(e);
      toast.error(`Purge failed: ${detail}`);
    } finally {
      setBusyId(null);
    }
  };

  const runNightly = async (dryRunOnly) => {
    try {
      const res = dryRunOnly
        ? await api.get("/hard-delete/admin/nightly-purge/dry-run")
        : await api.post("/hard-delete/admin/run-nightly-purge", null);
      setNightlyResult(res);
      toast.success(
        dryRunOnly
          ? `Nightly dry-run: ${res.candidates} candidate(s)`
          : `Nightly purge complete: ${res.purged} purged, ${res.blocked?.length || 0} blocked`
      );
      await load();
    } catch (e) {
      toast.error(`Nightly purge failed: ${e.message || e}`);
    }
  };

  const filteredRows = useMemo(
    () =>
      (rows || []).filter((r) =>
        entityFilter ? r.entity_type === entityFilter : true
      ),
    [rows, entityFilter]
  );

  const entityCounts = useMemo(() => {
    const acc = {};
    (rows || []).forEach((r) => {
      acc[r.entity_type] = (acc[r.entity_type] || 0) + 1;
    });
    return acc;
  }, [rows]);

  return (
    <div
      data-testid="admin-trash-page"
      style={{
        padding: "24px 32px",
        maxWidth: 1200,
        margin: "0 auto",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 8,
        }}
      >
        <Trash2 size={26} />
        <h1 style={{ margin: 0, fontSize: 22 }} data-testid="admin-trash-title">
          Trash
        </h1>
      </div>
      <p style={{ color: "#666", marginTop: 0 }}>
        Soft-deleted rows across the platform. Restore reverses the entire
        cascade. Hard purge is <strong>super-admin only</strong> and
        immutable — a tombstone snapshot is preserved for audit.
      </p>

      {/* Filter tabs */}
      <div
        style={{
          display: "flex",
          gap: 8,
          margin: "16px 0",
          flexWrap: "wrap",
        }}
      >
        <button
          data-testid="trash-filter-all"
          onClick={() => setEntityFilter("")}
          style={{
            padding: "6px 14px",
            borderRadius: 6,
            border: "1px solid #ccc",
            background: entityFilter === "" ? "#0f2f44" : "#fff",
            color: entityFilter === "" ? "#fff" : "#111",
            cursor: "pointer",
          }}
        >
          All ({rows?.length ?? "…"})
        </button>
        {Object.entries(ENTITY_LABELS).map(([et, label]) => (
          <button
            key={et}
            data-testid={`trash-filter-${et}`}
            onClick={() => setEntityFilter(et)}
            style={{
              padding: "6px 14px",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: entityFilter === et ? "#0f2f44" : "#fff",
              color: entityFilter === et ? "#fff" : "#111",
              cursor: "pointer",
            }}
          >
            {label} ({entityCounts[et] || 0})
          </button>
        ))}
        <button
          data-testid="trash-reload"
          onClick={load}
          title="Reload"
          style={{
            padding: "6px 10px",
            borderRadius: 6,
            border: "1px solid #ccc",
            background: "#fff",
            cursor: "pointer",
          }}
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Super-admin nightly-purge controls */}
      {isSuper && (
        <div
          data-testid="trash-super-controls"
          style={{
            border: "1px solid #eaeaea",
            borderRadius: 8,
            padding: 12,
            marginBottom: 16,
            background: "#fafafa",
          }}
        >
          <strong style={{ display: "block", marginBottom: 6 }}>
            Nightly retention sweep
          </strong>
          <span style={{ color: "#666", fontSize: 13 }}>
            Purges rows soft-deleted more than 30 days ago. Cron-schedulable;
            manual triggers below.
          </span>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button
              data-testid="trash-nightly-dryrun"
              onClick={() => runNightly(true)}
              style={{
                padding: "6px 12px",
                border: "1px solid #ccc",
                borderRadius: 6,
                background: "#fff",
                cursor: "pointer",
              }}
            >
              <Play size={13} style={{ verticalAlign: "middle" }} /> Dry run
            </button>
            <button
              data-testid="trash-nightly-run"
              onClick={() => runNightly(false)}
              style={{
                padding: "6px 12px",
                border: "1px solid #c65",
                borderRadius: 6,
                background: "#fff2ee",
                color: "#7a1a1a",
                cursor: "pointer",
              }}
            >
              <Flame size={13} style={{ verticalAlign: "middle" }} /> Run now
            </button>
          </div>
          {nightlyResult && (
            <pre
              data-testid="trash-nightly-result"
              style={{
                background: "#fff",
                border: "1px solid #eee",
                padding: 10,
                marginTop: 10,
                fontSize: 12,
                borderRadius: 6,
                overflow: "auto",
                maxHeight: 220,
              }}
            >
              {JSON.stringify(nightlyResult, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Rows */}
      {rows === null && (
        <div data-testid="trash-loading" style={{ padding: 40, color: "#888" }}>
          Loading Trash…
        </div>
      )}
      {rows !== null && filteredRows.length === 0 && (
        <div
          data-testid="trash-empty"
          style={{
            padding: 40,
            border: "1px dashed #ddd",
            borderRadius: 8,
            textAlign: "center",
            color: "#888",
          }}
        >
          Nothing in Trash. Soft-deleted rows will appear here for up to 30
          days before automatic purge.
        </div>
      )}
      {rows !== null && filteredRows.length > 0 && (
        <table
          data-testid="trash-table"
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 14,
          }}
        >
          <thead>
            <tr style={{ textAlign: "left", background: "#f5f5f5" }}>
              <th style={{ padding: 10 }}>Type</th>
              <th style={{ padding: 10 }}>Name / Id</th>
              <th style={{ padding: 10 }}>Deleted</th>
              <th style={{ padding: 10 }}>Batch</th>
              <th style={{ padding: 10, textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r) => (
              <tr
                key={`${r.entity_type}:${r.id}`}
                data-testid={`trash-row-${r.entity_type}-${r.id}`}
                style={{ borderTop: "1px solid #eee" }}
              >
                <td style={{ padding: 10 }}>
                  <span
                    style={{
                      background: "#eef",
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontSize: 12,
                    }}
                  >
                    {ENTITY_LABELS[r.entity_type] || r.entity_type}
                  </span>
                </td>
                <td style={{ padding: 10 }}>{displayName(r)}</td>
                <td style={{ padding: 10, color: "#666", fontSize: 12 }}>
                  {r.deleted_at}
                </td>
                <td style={{ padding: 10, color: "#666", fontSize: 12 }}>
                  {r.cascade_role === "root" && <strong>root</strong>}
                  {r.cascade_role === "child" && "child"}
                </td>
                <td style={{ padding: 10, textAlign: "right" }}>
                  <button
                    data-testid={`trash-restore-${r.entity_type}-${r.id}`}
                    disabled={busyId === r.id}
                    onClick={() => restore(r)}
                    style={{
                      padding: "6px 12px",
                      marginRight: 6,
                      border: "1px solid #2c6",
                      borderRadius: 6,
                      background: "#f0fff5",
                      color: "#116",
                      cursor: "pointer",
                    }}
                  >
                    <RotateCcw
                      size={13}
                      style={{ verticalAlign: "middle", marginRight: 4 }}
                    />
                    Restore
                  </button>
                  {isSuper && (
                    <button
                      data-testid={`trash-purge-${r.entity_type}-${r.id}`}
                      disabled={busyId === r.id}
                      onClick={() =>
                        setConfirmPurge({ row: r, skipTrash: false })
                      }
                      style={{
                        padding: "6px 12px",
                        border: "1px solid #c33",
                        borderRadius: 6,
                        background: "#fff0f0",
                        color: "#7a1a1a",
                        cursor: "pointer",
                      }}
                    >
                      <Flame
                        size={13}
                        style={{ verticalAlign: "middle", marginRight: 4 }}
                      />
                      Purge
                    </button>
                  )}
                  {!isSuper && (
                    <span
                      data-testid={`trash-purge-hint-${r.entity_type}-${r.id}`}
                      style={{ color: "#999", fontSize: 12 }}
                    >
                      Requires super-admin
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Purge confirmation modal */}
      {confirmPurge && (
        <div
          data-testid="trash-purge-modal"
          role="dialog"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: 8,
              padding: 24,
              maxWidth: 480,
              width: "90%",
            }}
          >
            <h2 style={{ marginTop: 0 }}>Purge permanently?</h2>
            <p>
              This immediately removes{" "}
              <strong>
                {ENTITY_LABELS[confirmPurge.row.entity_type]}: {displayName(confirmPurge.row)}
              </strong>{" "}
              and every child in the cascade. An immutable tombstone is
              written for audit. This cannot be undone.
            </p>
            <label style={{ display: "block", marginTop: 12 }}>
              Reason (optional, appended to tombstone):
              <input
                data-testid="trash-purge-reason"
                value={purgeReason}
                onChange={(e) => setPurgeReason(e.target.value)}
                style={{
                  width: "100%",
                  padding: 6,
                  marginTop: 4,
                  border: "1px solid #ccc",
                  borderRadius: 4,
                }}
              />
            </label>
            {isSuper && (
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  marginTop: 12,
                  fontSize: 13,
                }}
              >
                <input
                  data-testid="trash-purge-skip-trash"
                  type="checkbox"
                  checked={confirmPurge.skipTrash}
                  onChange={(e) =>
                    setConfirmPurge({
                      ...confirmPurge,
                      skipTrash: e.target.checked,
                    })
                  }
                />
                Skip Trash — purge immediately even without prior soft-delete
                (super-admin escape hatch).
              </label>
            )}
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 20,
              }}
            >
              <button
                data-testid="trash-purge-cancel"
                onClick={() => {
                  setConfirmPurge(null);
                  setPurgeReason("");
                }}
                style={{
                  padding: "6px 14px",
                  border: "1px solid #ccc",
                  borderRadius: 6,
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                data-testid="trash-purge-confirm"
                onClick={purge}
                disabled={busyId === confirmPurge.row.id}
                style={{
                  padding: "6px 14px",
                  border: "1px solid #c33",
                  borderRadius: 6,
                  background: "#c33",
                  color: "#fff",
                  cursor: "pointer",
                }}
              >
                Purge Permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
