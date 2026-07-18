import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileText, Copy, Trash2, Download } from "lucide-react";
import { colors } from "@/theme";
import TemplateStatusPill from "@/components/templates/TemplateStatusPill";
import { CATEGORY_LABEL } from "@/api/templates";

/**
 * Row-level renderer for instance list groups (Drafts + Finalized).
 */
export default function TemplateInstanceList({
  title, instances, definitionsByCode,
  onDuplicate, onDelete, onDownload,
}) {
  const navigate = useNavigate();
  if (!instances || instances.length === 0) return null;
  return (
    <div className="mb-6" data-testid={`template-instance-group-${title.toLowerCase()}`}>
      <div className="px-1 pb-1 text-xs font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
        {title} <span className="font-normal" style={{ color: colors.muted }}>({instances.length})</span>
      </div>
      <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
                Title
              </th>
              <th className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
                Template
              </th>
              <th className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
                Status
              </th>
              <th className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
                Updated
              </th>
              <th className="px-3 py-2 text-right text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {instances.map((inst) => {
              const defn = definitionsByCode?.[inst.template_code];
              return (
                <tr
                  key={inst.id}
                  className="hover:bg-slate-50 cursor-pointer"
                  onClick={() => navigate(`/admin/templates/instances/${inst.id}`)}
                  data-testid={`template-instance-row-${inst.id}`}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                >
                  <td className="px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>
                    <div className="flex items-center gap-2">
                      <FileText size={14} style={{ color: colors.muted }} />
                      <Link
                        to={`/admin/templates/instances/${inst.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="hover:underline"
                        data-testid={`template-instance-open-${inst.id}`}
                      >
                        {inst.title || "(untitled)"}
                      </Link>
                    </div>
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.onSurfaceSecondary }}>
                    {defn?.title || inst.template_code}
                    {defn?.category && (
                      <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
                        {CATEGORY_LABEL[defn.category] || defn.category}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2"><TemplateStatusPill status={inst.status} /></td>
                  <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>
                    {inst.updated_at ? new Date(inst.updated_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      {inst.status === "finalized" && onDownload && (
                        <button
                          onClick={() => onDownload(inst)}
                          className="p-1.5 rounded hover:bg-slate-100"
                          title="Download PDF"
                          style={{ color: colors.brand }}
                          data-testid={`template-instance-download-${inst.id}`}
                        >
                          <Download size={14} />
                        </button>
                      )}
                      <button
                        onClick={() => onDuplicate?.(inst)}
                        className="p-1.5 rounded hover:bg-slate-100"
                        title="Duplicate"
                        style={{ color: colors.onSurfaceSecondary }}
                        data-testid={`template-instance-duplicate-${inst.id}`}
                      >
                        <Copy size={14} />
                      </button>
                      <button
                        onClick={() => onDelete?.(inst)}
                        className="p-1.5 rounded hover:bg-red-50"
                        title="Delete"
                        style={{ color: colors.error }}
                        data-testid={`template-instance-delete-${inst.id}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
