/**
 * Phase 17 · Feb-2026 — QuickBooks Online admin integration page.
 *
 * Route: /admin/integrations/qbo
 * Tabs: Connect · Sync · History · Data browser (7 entity sub-tabs).
 * Read-only against Intuit. Match links are user-confirmed only.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Cloud, RefreshCw, History, Database, Link as LinkIcon, ExternalLink, AlertCircle } from "lucide-react";

import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const ENTITY_TABS = [
  { key: "customers",       label: "Customers" },
  { key: "invoices",        label: "Invoices" },
  { key: "payments",        label: "Payments" },
  { key: "accounts",        label: "Accounts" },
  { key: "journal-entries", label: "Journal Entries" },
  { key: "vendors",         label: "Vendors" },
  { key: "bills",           label: "Bills" },
];

function _authHeader() {
  const t = typeof window !== "undefined" ? window.localStorage.getItem("token") : "";
  return { Authorization: `Bearer ${t}` };
}

export default function QuickBooksIntegrationPage() {
  const [params] = useSearchParams();
  const [tab, setTab] = useState(params.get("connected") === "1" ? "sync" : "connect");
  const [connectionsRes, setConnectionsRes] = useState({ connections: [], configured: false });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/qbo/connections`, { headers: _authHeader() });
      const j = await r.json().catch(() => ({}));
      setConnectionsRes(j || { connections: [], configured: false });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const active = connectionsRes.connections?.[0];

  return (
    <div className="mx-auto max-w-6xl p-6" data-testid="qbo-integration-page">
      <div className="mb-6 flex items-center gap-3">
        <Cloud className="h-8 w-8 text-emerald-600" />
        <div>
          <h1 className="text-2xl font-bold text-slate-900">QuickBooks Online</h1>
          <p className="text-sm text-slate-500">
            Read-only inbound sync. Zero write-back to Intuit — QBO data is
            displayed side-by-side with CRM records with optional user-confirmed match links.
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200">
        {[
          { key: "connect", label: "Connect", icon: LinkIcon },
          { key: "sync",    label: "Sync",    icon: RefreshCw },
          { key: "history", label: "History", icon: History },
          { key: "data",    label: "Data browser", icon: Database },
        ].map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            data-testid={`qbo-tab-${t.key}`}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-semibold border-b-2 ${
              tab === t.key ? "border-emerald-600 text-emerald-700" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : tab === "connect" ? (
        <ConnectTab res={connectionsRes} onRefresh={load} />
      ) : tab === "sync" ? (
        <SyncTab connection={active} onRefresh={load} />
      ) : tab === "history" ? (
        <HistoryTab />
      ) : tab === "data" ? (
        <DataBrowserTab connection={active} />
      ) : null}
    </div>
  );
}

function ConnectTab({ res, onRefresh }) {
  const [starting, setStarting] = useState(false);

  const connect = async () => {
    setStarting(true);
    try {
      const r = await fetch(`${API}/qbo/oauth/connect-url`, { headers: _authHeader() });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Failed to start OAuth flow.");
      window.location.href = j.auth_url;
    } catch (err) {
      toast.error(String(err.message || err));
      setStarting(false);
    }
  };

  const revoke = async (id) => {
    if (!window.confirm("Revoke this QuickBooks connection?")) return;
    const r = await fetch(`${API}/qbo/connections/${id}`, {
      method: "DELETE", headers: _authHeader(),
    });
    if (r.ok) { toast.success("Connection revoked."); onRefresh(); }
    else toast.error("Revoke failed.");
  };

  if (!res.configured) {
    return (
      <Card data-testid="qbo-unconfigured-card">
        <CardHeader className="flex flex-row items-center gap-2">
          <AlertCircle className="text-amber-600" />
          <CardTitle>QuickBooks OAuth not configured</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            Before connecting, register an Intuit Developer app and fill in the
            following backend environment variables:
          </p>
          <ul className="list-disc pl-6 space-y-1 text-slate-700">
            <li><code>QBO_CLIENT_ID</code> — Intuit Developer app Client ID</li>
            <li><code>QBO_CLIENT_SECRET</code> — Client Secret</li>
            <li><code>QBO_REDIRECT_URI</code> — Callback URL (this app's <code>/api/qbo/oauth/callback</code>)</li>
            <li><code>QBO_ENVIRONMENT</code> — <code>sandbox</code> or <code>production</code></li>
          </ul>
          <a
            href="https://developer.intuit.com/"
            target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 text-emerald-700 font-semibold underline"
            data-testid="qbo-setup-help-link"
          >
            <ExternalLink size={14} /> Create your Intuit Developer app
          </a>
        </CardContent>
      </Card>
    );
  }

  if ((res.connections || []).length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Connect to QuickBooks</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm text-slate-600">
            Grant read-only access to your QuickBooks company. You can revoke at any time.
          </p>
          <Button onClick={connect} disabled={starting} data-testid="qbo-connect-btn">
            {starting ? "Redirecting…" : "Connect to QuickBooks"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle>Active connections</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {res.connections.map((c) => (
          <div key={c.qbo_connection_id}
               className="flex items-center justify-between rounded border border-slate-200 p-3"
               data-testid={`qbo-connection-${c.qbo_connection_id}`}>
            <div>
              <div className="font-semibold text-slate-900">
                {c.qbo_company_name || "QuickBooks company"}
              </div>
              <div className="text-xs text-slate-500">
                Realm {c.qbo_realm_id} · {c.environment} · connected {c.connected_at?.slice(0, 10)}
              </div>
            </div>
            <Button variant="ghost" onClick={() => revoke(c.qbo_connection_id)}
                    data-testid={`qbo-revoke-${c.qbo_connection_id}`}>
              Revoke
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SyncTab({ connection, onRefresh }) {
  const [syncing, setSyncing] = useState(false);
  const [forceFull, setForceFull] = useState(false);
  const [lastRun, setLastRun] = useState(null);

  useEffect(() => {
    (async () => {
      const r = await fetch(`${API}/qbo/sync/runs?limit=1`, { headers: _authHeader() });
      const j = await r.json().catch(() => ({}));
      setLastRun((j.runs || [])[0] || null);
    })();
  }, [syncing]);

  if (!connection) {
    return <p className="text-sm text-slate-500">Connect to QuickBooks first.</p>;
  }

  const run = async () => {
    if (forceFull && !window.confirm("Force full sync? This ignores the delta cursor and re-pulls everything.")) return;
    setSyncing(true);
    try {
      const r = await fetch(`${API}/qbo/sync/run-now`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ..._authHeader() },
        body: JSON.stringify({
          qbo_connection_id: connection.qbo_connection_id,
          force_full: forceFull,
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Sync failed.");
      toast.success(j.already_running ? "Sync already running." : "Sync started.");
      onRefresh();
    } catch (err) {
      toast.error(String(err.message || err));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Sync now</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={forceFull} onChange={(e) => setForceFull(e.target.checked)}
                    data-testid="qbo-force-full-checkbox" />
            Force full sync (ignore delta cursor)
          </label>
          <Button onClick={run} disabled={syncing} data-testid="qbo-sync-now-btn">
            {syncing ? "Syncing…" : "Sync from QuickBooks now"}
          </Button>
        </CardContent>
      </Card>
      {lastRun ? (
        <Card>
          <CardHeader><CardTitle className="text-base">Last run</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
              <Kpi label="Status" value={lastRun.status} />
              <Kpi label="Duration" value={`${lastRun.duration_ms || 0} ms`} />
              <Kpi label="Started" value={lastRun.started_at?.slice(0, 19) || "—"} />
              <Kpi label="Triggered" value={lastRun.triggered_by} />
            </div>
            <div className="mt-3 text-xs text-slate-500">
              Entities pulled:{" "}
              {Object.entries(lastRun.entities_pulled || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "—"}
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function HistoryTab() {
  const [runs, setRuns] = useState([]);
  useEffect(() => {
    (async () => {
      const r = await fetch(`${API}/qbo/sync/runs?limit=50`, { headers: _authHeader() });
      const j = await r.json().catch(() => ({}));
      setRuns(j.runs || []);
    })();
  }, []);
  return (
    <Card>
      <CardHeader><CardTitle>Sync history</CardTitle></CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-slate-500" data-testid="qbo-history-empty">No runs yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>
                <th className="text-left py-2">Started</th>
                <th className="text-left py-2">Trigger</th>
                <th className="text-left py-2">Status</th>
                <th className="text-right py-2">Duration</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} data-testid={`qbo-history-row-${r.run_id}`}>
                  <td className="py-1">{r.started_at?.slice(0, 19)}</td>
                  <td className="py-1">{r.triggered_by}</td>
                  <td className="py-1"><span className={`rounded px-2 py-0.5 text-xs ${
                    r.status === "success" ? "bg-emerald-100 text-emerald-800"
                    : r.status === "partial_success" ? "bg-amber-100 text-amber-800"
                    : "bg-red-100 text-red-800"
                  }`}>{r.status}</span></td>
                  <td className="py-1 text-right">{r.duration_ms || 0} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function DataBrowserTab({ connection }) {
  const [entity, setEntity] = useState("customers");
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!connection) return;
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (search) qs.set("search", search);
      const r = await fetch(`${API}/qbo/${entity}?${qs.toString()}`, { headers: _authHeader() });
      const j = await r.json().catch(() => ({}));
      setRows(j.items || []);
    } finally {
      setLoading(false);
    }
  }, [entity, search, connection]);

  useEffect(() => { load(); }, [load]);

  if (!connection) return <p className="text-sm text-slate-500">Connect first.</p>;

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1">
        {ENTITY_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setEntity(t.key)}
            data-testid={`qbo-entity-tab-${t.key}`}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              entity === t.key ? "bg-emerald-600 text-white" : "bg-slate-100 text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <Input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…" className="mb-3"
              data-testid="qbo-data-search" />
      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500" data-testid="qbo-data-empty">
          No {entity} synced yet. Run a sync first.
        </p>
      ) : (
        <div className="overflow-hidden rounded border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-600">
              <tr>
                <th className="text-left px-2 py-1">QBO ID</th>
                <th className="text-left px-2 py-1">Summary</th>
                <th className="text-left px-2 py-1">Linked CRM</th>
                <th className="text-left px-2 py-1">Last synced</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.qbo_id} className="border-t border-slate-100"
                    data-testid={`qbo-data-row-${row.qbo_id}`}>
                  <td className="px-2 py-1 font-mono text-xs">{row.qbo_id}</td>
                  <td className="px-2 py-1">
                    {row.extracted?.display_name || row.extracted?.customer_name
                      || row.extracted?.doc_number || row.extracted?.name || "—"}
                  </td>
                  <td className="px-2 py-1 text-xs">
                    {row.linked_crm_id ? (
                      <span className="rounded bg-emerald-100 px-2 py-0.5 text-emerald-800">
                        {row.linked_crm_entity_type} · {row.linked_crm_id.slice(0, 12)}…
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-xs text-slate-500">{row.last_synced_at?.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value }) {
  return (
    <div className="rounded border border-slate-200 p-2">
      <div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{String(value)}</div>
    </div>
  );
}
