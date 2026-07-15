/**
 * Phase 26.3 · Batch checks + Payroll CSV import.
 * Exports: CheckBatchNew (default), CheckPayrollImport.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Plus, Trash2, Upload, FileText, Users,
  AlertTriangle, CheckCircle2, Download, Printer,
} from "lucide-react";
import { api, api_base } from "@/api";
import { colors } from "@/theme";
import { Gate } from "@/hooks/usePermissions";

/* ═════════ BATCH CREATE ═══════════════════════════════════════════════ */
export default function CheckBatchNew() {
  const nav = useNavigate();
  const [banks, setBanks] = useState([]);
  const [payees, setPayees] = useState([]);
  const [bankId, setBankId] = useState("");
  const [lines, setLines] = useState([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [created, setCreated] = useState(null);

  useEffect(() => {
    api.get("/checks/bank-accounts").then((r) => {
      setBanks(r.items || []);
      if (r.items?.length && !bankId) setBankId(r.items[0].id);
    });
    api.get("/checks/payees").then((r) => setPayees(r.items || []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addLine = () => setLines([...lines, {
    payee_id: "", amount: 0, date: new Date().toISOString().slice(0, 10),
    memo: "", category: "",
  }]);
  const updateLine = (i, patch) => {
    const next = [...lines];
    next[i] = { ...next[i], ...patch };
    setLines(next);
  };
  const removeLine = (i) => setLines(lines.filter((_, j) => j !== i));

  const total = lines.reduce((s, l) => s + Number(l.amount || 0), 0);

  const save = async () => {
    if (!bankId) { setErr("Pick a bank account"); return; }
    if (lines.length === 0) { setErr("Add at least one check"); return; }
    if (lines.some((l) => !l.payee_id || Number(l.amount) <= 0)) {
      setErr("Every line needs a payee and a positive amount"); return;
    }
    setSaving(true); setErr("");
    try {
      const r = await api.post("/checks/batch", {
        bank_account_id: bankId,
        checks: lines.map((l) => ({
          payee_id: l.payee_id, amount: Number(l.amount),
          date: l.date, memo: l.memo, category: l.category,
        })),
      });
      setCreated(r);
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setSaving(false); }
  };

  const printBatch = async () => {
    window.open(
      `${window.location.origin}/api/checks/batch/${created.id}/print`,
      "_blank");
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="check-batch-new">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="batch-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <FileText size={22} style={{ color: colors.brand }} />
            Batch check creation
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Create multiple checks in one atomic operation. Check numbers
            are allocated sequentially.
          </p>
        </div>
        <button onClick={() => nav("/admin/checks/payroll")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="batch-payroll-link">
          <Users size={14} /> Payroll CSV
        </button>
      </div>

      {created ? (
        <div className="rounded-2xl p-6 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="batch-created">
          <CheckCircle2 size={40}
                          style={{ color: "#059669", margin: "0 auto 8px" }} />
          <div className="text-lg font-bold"
               style={{ color: colors.onSurface }}>
            Batch created — {created.check_count} checks · ${created.total_amount.toFixed(2)}
          </div>
          <div className="mt-4 flex gap-2 justify-center">
            <button onClick={printBatch}
                    className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="batch-print">
              <Printer size={14} /> Print PDF
            </button>
            <button onClick={() => nav("/admin/checks")}
                    className="px-4 py-2 text-sm font-bold rounded-xl"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}`,
                             color: colors.onSurface }}
                    data-testid="batch-close">
              Back to register
            </button>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <label className="block mb-3">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Bank account</div>
            <select value={bankId} onChange={(e) => setBankId(e.target.value)}
                    className="w-full p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid="batch-bank">
              {banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.nickname} · next #{b.next_check_number}
                </option>
              ))}
            </select>
          </label>

          <div className="flex justify-between items-center mb-2">
            <div className="text-xs font-bold" style={{ color: colors.muted }}>
              Check lines
            </div>
            <button onClick={addLine}
                    className="px-2 py-1 text-xs font-bold rounded"
                    style={{ backgroundColor: colors.brandTertiary,
                             color: colors.brand }}
                    data-testid="batch-addline">
              + Add line
            </button>
          </div>

          {lines.map((l, i) => (
            <div key={i} className="flex gap-2 mb-2 items-center flex-wrap">
              <select value={l.payee_id}
                      onChange={(e) => updateLine(i, { payee_id: e.target.value })}
                      className="flex-1 min-w-[180px] p-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}` }}
                      data-testid={`batch-line-payee-${i}`}>
                <option value="">Payee…</option>
                {payees.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.kind})
                  </option>
                ))}
              </select>
              <input type="number" step="0.01" value={l.amount}
                     onChange={(e) => updateLine(i, { amount: e.target.value })}
                     placeholder="$0.00"
                     className="w-28 p-2 rounded-lg text-sm font-mono"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`batch-line-amount-${i}`} />
              <input type="date" value={l.date}
                     onChange={(e) => updateLine(i, { date: e.target.value })}
                     className="w-36 p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`batch-line-date-${i}`} />
              <input value={l.memo}
                     onChange={(e) => updateLine(i, { memo: e.target.value })}
                     placeholder="Memo"
                     className="flex-1 min-w-[120px] p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`batch-line-memo-${i}`} />
              <button onClick={() => removeLine(i)}
                      className="p-2 rounded-lg"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}`,
                               color: "#DC2626" }}
                      data-testid={`batch-line-remove-${i}`}>
                <Trash2 size={12} />
              </button>
            </div>
          ))}

          <div className="mt-3 text-right text-sm font-bold"
               style={{ color: colors.onSurface }}>
            Total: ${total.toFixed(2)} · {lines.length} checks
          </div>
          {err ? (
            <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>
              {err}
            </div>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => nav("/admin/checks")}
                    className="px-4 py-2 text-sm font-bold rounded-xl"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}`,
                             color: colors.onSurface }}
                    data-testid="batch-cancel">
              Cancel
            </button>
            <Gate perm="Settings" action="write">
              <button onClick={save} disabled={saving}
                    className="px-4 py-2 text-sm font-bold rounded-xl"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="batch-save">
                {saving ? "Saving…" : `Create ${lines.length} checks`}
              </button>
            </Gate>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═════════ PAYROLL CSV IMPORT ═════════════════════════════════════════ */
export function CheckPayrollImport() {
  const nav = useNavigate();
  const [banks, setBanks] = useState([]);
  const [bankId, setBankId] = useState("");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    api.get("/checks/bank-accounts").then((r) => {
      setBanks(r.items || []);
      if (r.items?.length) setBankId(r.items[0].id);
    });
  }, []);

  const doPreview = async () => {
    if (!file || !bankId) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const form = new FormData();
      form.append("csv_file", file);
      const r = await fetch(
        `${api_base()}/checks/payroll/import-csv?bank_account_id=${bankId}`,
        { method: "POST", body: form,
          headers: { Authorization: "Bearer " + localStorage.getItem("token") } },
      );
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Preview failed");
      setPreview(body);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };
  const doExecute = async () => {
    setBusy(true); setErr("");
    try {
      const form = new FormData();
      form.append("csv_file", file);
      const r = await fetch(
        `${api_base()}/checks/payroll/import-csv?bank_account_id=${bankId}&execute=true`,
        { method: "POST", body: form,
          headers: { Authorization: "Bearer " + localStorage.getItem("token") } },
      );
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Execute failed");
      setResult(body);
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };
  const dlTemplate = () => {
    window.open(`${api_base()}/checks/payroll/template.csv`, "_blank");
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="check-payroll">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="payroll-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Users size={22} style={{ color: colors.brand }} />
            Payroll CSV import
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Upload a CSV of contractor / employee payouts — matches existing
            payees or auto-creates them, then generates all checks in one batch.
          </p>
        </div>
        <button onClick={dlTemplate}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="payroll-template-btn">
          <Download size={14} /> Template
        </button>
      </div>

      {result ? (
        <div className="rounded-2xl p-6 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="payroll-result">
          <CheckCircle2 size={40}
                          style={{ color: "#059669", margin: "0 auto 8px" }} />
          <div className="text-lg font-bold"
               style={{ color: colors.onSurface }}>
            Payroll import complete
          </div>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            {result.batch.check_count} checks · ${result.batch.total_amount.toFixed(2)}
          </div>
          <div className="mt-4 flex gap-2 justify-center">
            <button onClick={() =>
                        window.open(`${api_base()}/checks/batch/${result.batch.id}/print`,
                                     "_blank")}
                    className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="payroll-print">
              <Printer size={14} /> Print batch
            </button>
            <button onClick={() => nav("/admin/checks")}
                    className="px-4 py-2 text-sm font-bold rounded-xl"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}`,
                             color: colors.onSurface }}
                    data-testid="payroll-close">
              View register
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="rounded-2xl p-5 mb-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <label className="block mb-3">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>Bank account</div>
              <select value={bankId}
                      onChange={(e) => setBankId(e.target.value)}
                      className="w-full p-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}` }}
                      data-testid="payroll-bank">
                {banks.map((b) => (
                  <option key={b.id} value={b.id}>{b.nickname}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>CSV file</div>
              <input type="file" accept=".csv,text/csv"
                     onChange={(e) => setFile(e.target.files[0])}
                     className="w-full p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid="payroll-file" />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={doPreview} disabled={!file || busy}
                      className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="payroll-preview-btn">
                <Upload size={14} /> {busy ? "Working…" : "Preview"}
              </button>
            </div>
            {err ? (
              <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>
                {err}
              </div>
            ) : null}
          </div>

          {preview ? (
            <div className="rounded-2xl overflow-hidden mb-4"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                 data-testid="payroll-preview">
              <div className="p-4 border-b flex items-center gap-2"
                   style={{ borderColor: colors.border }}>
                <div className="text-sm font-bold"
                     style={{ color: colors.onSurface }}>
                  Preview · {preview.valid_count} valid · {preview.warning_count} warnings
                </div>
                <Gate perm="Settings" action="write">
                  <button onClick={doExecute}
                        disabled={!preview.can_execute || busy}
                        className="ml-auto px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                        style={{ backgroundColor: preview.can_execute
                                     ? "#059669" : colors.background,
                                 color: preview.can_execute
                                         ? "#fff" : colors.muted,
                                 opacity: preview.can_execute ? 1 : 0.6 }}
                        data-testid="payroll-execute-btn">
                    <CheckCircle2 size={14} /> Execute · create checks
                  </button>
                </Gate>
              </div>
              <table className="w-full text-sm">
                <thead style={{ backgroundColor: "#F1F5F9" }}>
                  <tr>
                    <th className="p-2 text-left">Row</th>
                    <th className="p-2 text-left">Payee</th>
                    <th className="p-2 text-right">Amount</th>
                    <th className="p-2 text-left">Date</th>
                    <th className="p-2 text-left">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.preview.map((r, i) => (
                    <tr key={i}
                        style={{ borderTop: `1px solid ${colors.border}` }}
                        data-testid={`payroll-row-${i}`}>
                      <td className="p-2 text-xs font-mono"
                          style={{ color: colors.muted }}>{r.row}</td>
                      <td className="p-2 font-bold"
                          style={{ color: colors.onSurface }}>
                        {r.payee_name || "—"}
                      </td>
                      <td className="p-2 text-right font-mono"
                          style={{ color: colors.onSurface }}>
                        {r.amount != null
                          ? `$${Number(r.amount).toFixed(2)}` : "—"}
                      </td>
                      <td className="p-2 text-xs"
                          style={{ color: colors.muted }}>
                        {r.date}
                      </td>
                      <td className="p-2 text-xs">
                        {r.warnings.length > 0 ? (
                          <span className="inline-flex items-center gap-1"
                                style={{ color: "#DC2626" }}>
                            <AlertTriangle size={10} />
                            {r.warnings.join("; ")}
                          </span>
                        ) : r.will_create_payee ? (
                          <span style={{ color: "#F59E0B" }}>
                            will create payee
                          </span>
                        ) : r.matched_payee_id ? (
                          <span style={{ color: "#059669" }}>
                            payee matched
                          </span>
                        ) : (
                          <span style={{ color: colors.muted }}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
