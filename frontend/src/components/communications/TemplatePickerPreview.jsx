/**
 * TD-100-sub-template · Feb-2026 — extracted sub-primitive.
 *
 * Formerly inlined inside ``SendComposeModal`` at
 * ``pages/customers/CustomerDetail.jsx:3775+`` (template-fetch effect
 * + aside picker JSX + ``pickTemplate`` handler). Extracted as a pure
 * selection + fetch primitive so the compose surface can stay focused
 * on editor state (subject / message / preview-pane / attachments).
 *
 * NOT consumed by ``components/mass-messaging/MassMessagingComposeDialog``
 * — that dialog carries intentional UX divergence (dropdown + debounced
 * auto-preview + ``useCustom`` toggle driven by bulk-recipient semantic),
 * see ``memory/td100_shared_compose_modal_audit.md`` for the parent-audit
 * rationale that explicitly rejected consolidation.
 *
 * Props (controlled):
 *   • ``channel``          "email" | "sms". Drives the ``?channel=`` fetch
 *                          param + loading/empty-state copy.
 *   • ``recipientId``      Opaque id for the current recipient (customer
 *                          id in the SendComposeModal case). Forwarded to
 *                          ``onPreviewRequest`` consumers; not used
 *                          internally for anything else.
 *   • ``pickedId``         Controlled selection id. "" = "Custom message"
 *                          selected. Parent owns this state so its
 *                          subject/message editor stays in sync with the
 *                          picker.
 *   • ``onPick(templateObj | null)``
 *                          Fires on template-row click (full template
 *                          object) or on Custom-row click (null). Parent
 *                          applies ``subject`` + ``body`` to its editor
 *                          state.
 *   • ``onPreviewRequest?(templateObj)``
 *                          Optional. Emitted alongside ``onPick`` on
 *                          non-null selections so a future consumer can
 *                          auto-preview on pick. The current
 *                          SendComposeModal consumer does NOT wire this —
 *                          its "Preview" button is parent-owned and uses
 *                          the parent's own ``runPreview`` with the full
 *                          editable body (which may differ from the
 *                          template's canonical body after the operator
 *                          edits it).
 *   • ``onError?(message)``
 *                          Optional. Emitted on fetch failure. The
 *                          current consumer leaves this unwired — matches
 *                          pre-extraction behavior of silently falling
 *                          back to an empty template list.
 *
 * Testids preserved (locked by phase29-composer-template-picker.test):
 *   • ``cd-send-templates`` (aside root)
 *   • ``cd-send-template-custom``
 *   • ``cd-send-templates-loading``
 *   • ``cd-send-templates-empty``
 *   • ``cd-send-template-{templateId}``
 */
import React, { useEffect, useState } from "react";

import { api } from "@/api";
import { colors } from "@/theme";


export default function TemplatePickerPreview({
  channel,
  recipientId,                                              // eslint-disable-line no-unused-vars
  pickedId = "",
  onPick,
  onPreviewRequest,
  onError,
}) {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(false);

  // Fetch effect — scoped to channel. Deps match the pre-extraction
  // ``[payload, isEmail]`` shape in CustomerDetail.jsx's parent effect:
  // ``payload`` gated the parent effect (modal only runs the fetch when
  // mounted on an open modal); the sub-primitive is only mounted when
  // the modal is open, so ``channel`` alone is the correct dep here.
  useEffect(() => {
    if (!channel) return undefined;
    let cancelled = false;
    setLoading(true);
    setTemplates([]);
    api
      .get(`/marketing/templates?channel=${channel}&active=true`)
      .then((r) => { if (!cancelled) setTemplates(r?.templates || []); })
      .catch((e) => {
        if (cancelled) return;
        setTemplates([]);
        if (typeof onError === "function") {
          onError(e?.message || "Failed to load templates");
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // onError intentionally omitted — a parent-recreated callback
    // must not refetch the template list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel]);

  const _handlePick = (t) => {
    if (typeof onPick === "function") onPick(t || null);
    if (t && typeof onPreviewRequest === "function") onPreviewRequest(t);
  };

  const isEmail = channel === "email";

  return (
    <aside
      data-testid="cd-send-templates"
      style={{ borderRight: `1px solid ${colors.border}`,
                paddingRight: 12, maxHeight: 380, overflowY: "auto" }}
    >
      <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>
        TEMPLATE
      </div>
      <button type="button"
               onClick={() => _handlePick(null)}
               className="w-full text-left rounded-md px-2 py-1.5 mb-1 text-sm"
               style={{
                 background: pickedId === "" ? colors.surfaceSecondary : "transparent",
                 border: pickedId === "" ? `1px solid ${colors.border}` : "1px solid transparent",
                 color: colors.onSurface,
               }}
               data-testid="cd-send-template-custom">
        <div className="font-semibold">Custom message</div>
        <div className="text-xs" style={{ color: colors.muted }}>
          Write from scratch
        </div>
      </button>
      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="cd-send-templates-loading">Loading…</div>
      ) : templates.length === 0 ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="cd-send-templates-empty">
          No saved {isEmail ? "email" : "SMS"} templates.
        </div>
      ) : templates.map((t) => (
        <button key={t.id}
                 type="button"
                 onClick={() => _handlePick(t)}
                 className="w-full text-left rounded-md px-2 py-1.5 mb-1 text-sm"
                 style={{
                   background: pickedId === t.id ? colors.surfaceSecondary : "transparent",
                   border: pickedId === t.id ? `1px solid ${colors.border}` : "1px solid transparent",
                   color: colors.onSurface,
                 }}
                 data-testid={`cd-send-template-${t.id}`}>
          <div className="font-semibold">{t.name}</div>
          {t.category ? (
            <div className="text-xs" style={{ color: colors.muted }}>{t.category}</div>
          ) : null}
        </button>
      ))}
    </aside>
  );
}
