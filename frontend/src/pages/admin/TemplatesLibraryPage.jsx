/**
 * Phase 2 · Templates Library — admin browse + "My Templates".
 *
 * Route: `/admin/templates` (admin + super_admin).
 * Tabs: Library | My Templates
 * Categories: All | Pricing & Money | Ops & Checklists | Chemicals & Chemistry | Documents
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { LibraryBig, Search, FileText, Calculator, ClipboardList } from 'lucide-react';
import { colors, gradients } from "@/theme";
import {
  TEMPLATE_CATEGORIES,
  listDefinitions,
  listInstances,
  createInstance,
  duplicateInstance,
  deleteInstance,
  generatePdf,
} from "@/api/templates";
import TemplateCard from "@/components/templates/TemplateCard";
import TemplateInstanceList from "@/components/templates/TemplateInstanceList";

export default function TemplatesLibraryPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("library"); // library | mine
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [defs, setDefs] = useState([]);
  const [instances, setInstances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reload = async () => {
    setLoading(true);
    setError("");
    try {
      const [d, i] = await Promise.all([
        listDefinitions(),
        listInstances({ mine: true }),
      ]);
      setDefs(d?.rows || []);
      setInstances(i?.rows || []);
    } catch (e) {
      setError(e.message || "Failed to load templates.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  const definitionsByCode = useMemo(() => {
    const m = {};
    for (const d of defs) m[d.code] = d;
    return m;
  }, [defs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return defs.filter((d) => {
      if (category !== "all" && d.category !== category) return false;
      if (!q) return true;
      return (
        (d.title || "").toLowerCase().includes(q) ||
        (d.description || "").toLowerCase().includes(q) ||
        (d.code || "").toLowerCase().includes(q)
      );
    });
  }, [defs, category, query]);

  const drafts = useMemo(() => instances.filter((i) => i.status === "draft"), [instances]);
  const finalized = useMemo(() => instances.filter((i) => i.status === "finalized"), [instances]);

  const handleCreate = async (code) => {
    setBusy(true);
    try {
      const inst = await createInstance({ template_code: code });
      navigate(`/admin/templates/instances/${inst.id}`);
    } catch (e) {
      alert(e.message || "Could not create draft.");
    } finally {
      setBusy(false);
    }
  };

  const handleDuplicate = async (inst) => {
    try {
      const dup = await duplicateInstance(inst.id);
      navigate(`/admin/templates/instances/${dup.id}`);
    } catch (e) {
      alert(e.message || "Could not duplicate.");
    }
  };

  const handleDelete = async (inst) => {
    if (!window.confirm(`Delete "${inst.title || "this instance"}"? This cannot be undone.`)) return;
    try {
      await deleteInstance(inst.id);
      await reload();
    } catch (e) {
      alert(e.message || "Could not delete.");
    }
  };

  const handleDownload = async (inst) => {
    try {
      await generatePdf(inst.id, inst.title || inst.template_code);
    } catch (e) {
      alert(e.message || "Could not generate PDF.");
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="templates-library-page">
      <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            <LibraryBig size={28} style={{ color: colors.brand }} /> Templates Library
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
            Fill-in-the-blank templates for pricing, operations, chemistry & docs. Autosaves as you type.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-4" data-testid="templates-library-tabs">
        {[
          { key: "library", label: "Library" },
          { key: "mine",    label: `My Templates${instances.length ? ` (${instances.length})` : ""}` },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="px-4 py-2 rounded-xl text-sm font-bold transition-colors"
            style={{
              backgroundColor: tab === t.key ? colors.brand : colors.surface,
              color: tab === t.key ? "#fff" : colors.onSurface,
              border: `1px solid ${tab === t.key ? colors.brand : colors.border}`,
            }}
            data-testid={`templates-tab-${t.key}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "#FEE2E2", color: colors.error }} data-testid="templates-error">
          {error}
        </div>
      )}

      {tab === "library" && (
        <>
          {/* Category chips + search */}
          <div className="flex flex-wrap items-center gap-2 mb-5" data-testid="templates-category-bar">
            {TEMPLATE_CATEGORIES.map((c) => (
              <button
                key={c.key}
                onClick={() => setCategory(c.key)}
                className="px-3 py-1.5 rounded-full text-xs font-bold transition-colors"
                style={{
                  backgroundColor: category === c.key ? colors.brand : colors.surface,
                  color: category === c.key ? "#fff" : colors.onSurface,
                  border: `1px solid ${category === c.key ? colors.brand : colors.border}`,
                }}
                data-testid={`templates-category-${c.key}`}
              >
                {c.label}
              </button>
            ))}
            <div className="flex-1 min-w-[220px]">
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
                <Search size={14} style={{ color: colors.searchIcon }} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search templates by title, description, code…"
                  className="flex-1 outline-none text-sm bg-transparent"
                  data-testid="templates-search-input"
                />
              </div>
            </div>
          </div>

          {loading ? (
            <div className="p-8 text-center text-sm" style={{ color: colors.muted }} data-testid="templates-loading">
              Loading templates…
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<LibraryBig size={22} />}
              title="No templates match your filters"
              body="Try clearing the search box or picking a different category."
              testId="templates-library-empty"
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="templates-cards-grid">
              {filtered.map((defn) => (
                <TemplateCard
                  key={defn.code}
                  definition={defn}
                  onCreate={handleCreate}
                  busy={busy}
                />
              ))}
            </div>
          )}

          {/* Also available — links out to existing shipped features */}
          <div className="mt-10">
            <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>Also available</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3" data-testid="templates-also-available">
              <LinkCard
                to="/admin/tools/documents"
                title="Commercial Bid Proposal"
                subtitle="Document Generators"
                icon={<FileText size={18} />}
              />
              <LinkCard
                to="/admin/tools/documents"
                title="Price Increase Letter"
                subtitle="Document Generators"
                icon={<FileText size={18} />}
              />
              <LinkCard
                to="/pool-service"
                title="Opening / Closing Checklists"
                subtitle="Pool Service"
                icon={<ClipboardList size={18} />}
              />
              <LinkCard
                to="/tech/tools/calculators"
                title="Chemical Dosing Calculator"
                subtitle="Pool Calculators"
                icon={<Calculator size={18} />}
              />
            </div>
          </div>
        </>
      )}

      {tab === "mine" && (
        loading ? (
          <div className="p-8 text-center text-sm" style={{ color: colors.muted }} data-testid="templates-mine-loading">
            Loading your templates…
          </div>
        ) : instances.length === 0 ? (
          <EmptyState
            icon={<FileText size={22} />}
            title="You haven't filled any templates yet"
            body="Head to the Library tab and pick a template to get started."
            testId="templates-mine-empty"
          />
        ) : (
          <>
            <TemplateInstanceList
              title="Drafts"
              instances={drafts}
              definitionsByCode={definitionsByCode}
              onDuplicate={handleDuplicate}
              onDelete={handleDelete}
            />
            <TemplateInstanceList
              title="Finalized"
              instances={finalized}
              definitionsByCode={definitionsByCode}
              onDuplicate={handleDuplicate}
              onDelete={handleDelete}
              onDownload={handleDownload}
            />
          </>
        )
      )}
    </div>
  );
}

function EmptyState({ icon, title, body, testId }) {
  return (
    <div
      className="rounded-2xl p-8 text-center"
      style={{ backgroundColor: colors.surface, border: `1px dashed ${colors.border}` }}
      data-testid={testId}
    >
      <div className="inline-flex items-center justify-center w-12 h-12 rounded-full mb-3"
           style={{ background: gradients.navyToGreen.css, color: "#fff" }}>
        {icon}
      </div>
      <div className="text-base font-bold" style={{ color: colors.onSurface }}>{title}</div>
      <div className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>{body}</div>
    </div>
  );
}

function LinkCard({ to, title, subtitle, icon }) {
  return (
    <Link
      to={to}
      className="block rounded-2xl p-4 transition-shadow hover:shadow-md"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={`templates-linkcard-${to.replaceAll("/", "-")}`}
    >
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center"
             style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
          {icon}
        </div>
        <div>
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>{title}</div>
          <div className="text-xs" style={{ color: colors.muted }}>{subtitle}</div>
        </div>
      </div>
    </Link>
  );
}
