import React from "react";
import { Droplets, Trees, Info } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { classifyServiceType } from "@/lib/serviceTypeGroups";

/**
 * Small "Note" chip surfaced on Schedule / Route / Calendar job rows.
 * Feb-2026 Note-pill polish ship · widened vocab Feb-2026 F8.
 *
 * Icon + color routing is delegated to
 * ``@/lib/serviceTypeGroups::classifyServiceType`` so backend and
 * frontend share ONE substring vocab.  See that module for the
 * pool/landscape keyword lists.
 *
 * Props:
 *   note         — string (renders nothing when null/empty)
 *   serviceType  — service_type string; routed via classifier
 *   jobId        — used to navigate to the job detail with notes focused
 *   testid       — optional data-testid override
 */
export function ServiceNotePill({ note, serviceType, jobId, testid, compact = false }) {
  const navigate = useNavigate();
  if (!note) return null;
  const group = classifyServiceType(serviceType);
  let bg, fg, border, Icon;
  if (group === "landscape") {
    bg = "#DCFCE7"; fg = "#166534"; border = "#86EFAC"; Icon = Trees;
  } else if (group === "pool") {
    bg = "#DBEAFE"; fg = "#075985"; border = "#7DD3FC"; Icon = Droplets;
  } else {
    bg = "#F3F4F6"; fg = "#4B5563"; border = "#D1D5DB"; Icon = Info;
  }
  const preview = note.length > 120 ? note.slice(0, 120) + "…" : note;
  const onClick = (e) => {
    e.stopPropagation();
    if (jobId) navigate(`/jobs/${jobId}?focus=notes`);
  };
  return (
    <button
      onClick={onClick}
      title={preview}
      data-testid={testid || `service-note-pill${jobId ? `-${jobId}` : ""}`}
      className="inline-flex items-center gap-1 rounded-md font-bold cursor-pointer transition hover:opacity-90"
      style={{
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
        padding: compact ? "1px 6px" : "2px 8px",
        fontSize: compact ? 10 : 11,
      }}
    >
      <Icon size={compact ? 9 : 11} /> Note
    </button>
  );
}

export default ServiceNotePill;
