import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Beaker, Sparkles, Plus, Trash2, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { PageHeader, Button, Skeleton, TextInput, EmptyState, Modal, Toast } from "@/components/ui-kit";

const READINGS = [
  { k: "fc", label: "FC (ppm)", range: "Target 1–4" },
  { k: "ph", label: "pH", range: "Target 7.4–7.6" },
  { k: "ta", label: "TA (ppm)", range: "Target 80–120" },
  { k: "cya", label: "CYA (ppm)", range: "Target 30–50" },
  { k: "salt", label: "Salt (ppm)", range: "Optional" },
];

export default function CustomerChemistry() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [customer, setCustomer] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [volume, setVolume] = useState(15000);
  const [readings, setReadings] = useState({ fc: "", ph: "", ta: "", cya: "", salt: "" });
  const [rec, setRec] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [newItem, setNewItem] = useState({ name: "", unit: "oz", unit_price: 0 });

  const load = async () => {
    try {
      const [c, cat] = await Promise.all([
        api.get(`/customers/${id}`),
        api.get("/chemicals/catalog"),
      ]);
      setCustomer(c);
      setCatalog(cat || []);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const recommend = async () => {
    setBusy(true);
    setErrorMsg("");
    setRec(null);
    try {
      const cleaned = {};
      Object.entries(readings).forEach(([k, v]) => {
        if (v !== "" && v !== null) cleaned[k] = Number(v);
      });
      const result = await api.post(
        "/chemicals/dosing-recommendation",
        { volume_gal: Number(volume), readings: cleaned },
        45000
      );
      setRec(result);
    } catch (e) {
      setErrorMsg(e.message || "Failed");
    } finally {
      setBusy(false);
    }
  };

  const createChemical = async () => {
    try {
      await api.post("/items", {
        ...newItem,
        unit_price: Number(newItem.unit_price) || 0,
        category: "Chemical",
        taxable: true,
      });
      setAddOpen(false);
      setNewItem({ name: "", unit: "oz", unit_price: 0 });
      const cat = await api.get("/chemicals/catalog");
      setCatalog(cat || []);
      setToast({ tone: "success", message: "Chemical added to catalog" });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="chemistry-page">
      <button
        onClick={() => navigate(`/customers/${id}`)}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> {customer?.name || "Customer"}
      </button>

      <PageHeader
        title="Pool Chemistry"
        subtitle="Track catalog + get an AI dosing recommendation."
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* AI dosing panel */}
        <div
          className="rounded-2xl p-5"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="ai-dosing-panel"
        >
          <div className="flex items-center gap-2 mb-4">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center text-white"
              style={{
                // K67 · Feb-2026 — swap the sky-600 stop for menu
                // navy via the canonical gradients.navyToGreen token.
                // Keep the 135deg direction (icon-plate diagonal) —
                // K67 constraint is "direction unchanged".
                background: gradients.navyToGreen.css.replace(
                  "90deg",
                  "135deg",
                ),
              }}
            >
              <Sparkles size={18} />
            </div>
            <div>
              <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
                AI Dosing Recommendation
              </h3>
              <p className="text-xs" style={{ color: colors.muted }}>
                Enter volume + current readings.
              </p>
            </div>
          </div>

          <TextInput
            label="POOL VOLUME (gallons)"
            type="number"
            inputMode="decimal"
            pattern="[0-9]*[.,]?[0-9]*"
            value={volume}
            onChange={(e) => setVolume(e.target.value)}
            wrapperClass="mb-3"
            testid="cx-volume"
          />

          <div className="grid grid-cols-2 gap-3 mb-4">
            {READINGS.map((r) => (
              <TextInput
                key={r.k}
                label={r.label}
                type="number"
                step="0.1"
                inputMode="decimal"
                pattern="[0-9]*[.,]?[0-9]*"
                value={readings[r.k]}
                onChange={(e) =>
                  setReadings((s) => ({ ...s, [r.k]: e.target.value }))
                }
                placeholder={r.range}
                testid={`cx-reading-${r.k}`}
              />
            ))}
          </div>

          <Button onClick={recommend} disabled={busy} testid="cx-recommend">
            <Sparkles size={14} /> {busy ? "Thinking…" : "Recommend"}
          </Button>

          {errorMsg ? (
            <div
              className="mt-4 rounded-lg p-3 text-sm flex items-start gap-2"
              style={{ backgroundColor: "#FEF9C3", color: "#A16207" }}
              data-testid="cx-ai-error"
            >
              <AlertTriangle size={14} className="mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          ) : null}

          {rec ? (
            <div className="mt-5" data-testid="cx-recommendations">
              {(rec.recommendations || []).length === 0 ? (
                <p className="text-sm" style={{ color: colors.muted }}>
                  No additions needed — readings are within target.
                </p>
              ) : (
                <ul className="space-y-2">
                  {rec.recommendations.map((r, i) => (
                    <li
                      key={i}
                      className="p-3 rounded-lg"
                      style={{
                        backgroundColor: colors.brandTertiary,
                        border: `1px solid ${colors.brandTertiary}`,
                      }}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <div
                          className="text-sm font-semibold"
                          style={{ color: colors.onBrandTertiary }}
                        >
                          {r.chemical}
                        </div>
                        <div
                          className="text-sm font-bold"
                          style={{ color: colors.onBrandTertiary }}
                        >
                          {r.amount_oz} oz
                        </div>
                      </div>
                      <p className="text-xs mt-1" style={{ color: colors.onBrandTertiary }}>
                        {r.reason}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              {(rec.warnings || []).length ? (
                <div className="mt-3 space-y-1">
                  {rec.warnings.map((w, i) => (
                    <div
                      key={i}
                      className="text-xs px-3 py-1.5 rounded"
                      style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                    >
                      ⚠ {w}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* Catalog */}
        <div
          className="rounded-2xl p-5"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Beaker size={18} color={colors.brand} />
              <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
                Chemicals Catalog
              </h3>
            </div>
            <Button variant="ghost" onClick={() => setAddOpen(true)} testid="cx-add-chem">
              <Plus size={14} /> Add
            </Button>
          </div>

          {catalog === null ? (
            <div className="space-y-2">
              <Skeleton style={{ height: 40 }} />
              <Skeleton style={{ height: 40 }} />
            </div>
          ) : catalog.length === 0 ? (
            <EmptyState
              title="No chemicals yet"
              hint="Add commonly-used products (Chlorine, pH-, Bicarb) so they appear in field reports."
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: colors.divider }}>
              {catalog.map((c) => (
                <li key={c.id} className="py-2.5 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                      {c.name}
                    </div>
                    <div className="text-xs" style={{ color: colors.muted }}>
                      {c.unit} · ${c.unit_price?.toFixed?.(2)}
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      try {
                        await api.del(`/items/${c.id}`);
                        setCatalog(catalog.filter((x) => x.id !== c.id));
                      } catch (e) {
                        setToast({ tone: "error", message: e.message });
                      }
                    }}
                    style={{ color: colors.error }}
                    className="opacity-70 hover:opacity-100"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add chemical to catalog"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={createChemical}>Add</Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextInput
            label="NAME"
            value={newItem.name}
            onChange={(e) => setNewItem({ ...newItem, name: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-3">
            <TextInput
              label="UNIT"
              value={newItem.unit}
              onChange={(e) => setNewItem({ ...newItem, unit: e.target.value })}
            />
            <TextInput
              label="UNIT PRICE"
              type="number"
              step="0.01"
              value={newItem.unit_price}
              onChange={(e) => setNewItem({ ...newItem, unit_price: e.target.value })}
            />
          </div>
        </div>
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
