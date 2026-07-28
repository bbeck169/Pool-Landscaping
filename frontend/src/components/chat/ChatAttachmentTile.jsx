/**
 * Phase B2 · Feb 2026 — Shared chat attachment tile.
 *
 * Rendered inline inside a chat message bubble. One <a> per
 * attachment; image attachments render a thumbnail, everything else
 * renders a paperclip icon + filename. Clicking opens the storage
 * URL in a new tab (browser handles the download / preview).
 *
 * Contract (matches ``chat_attachments`` server-side shape):
 *   attachment: {
 *     id: string,
 *     name: string,
 *     mime?: string,
 *     type?: "image" | "file",
 *     size_bytes?: number,
 *     storage_url: string,
 *   }
 *
 * Used by:
 *   • pages/chat/TeamChatPage.jsx  (staff-side)
 *   • pages/portal/PortalChatsPage.jsx  (customer-side)
 */
import React from "react";

function isImage(att) {
  if (!att) return false;
  if (att.type === "image") return true;
  const mime = String(att.mime || "").toLowerCase();
  return mime.startsWith("image/");
}

function humanSize(bytes) {
  const n = Number(bytes || 0);
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function ChatAttachmentTile({ attachment, testid }) {
  if (!attachment || !attachment.id) return null;
  const image = isImage(attachment);
  const size = humanSize(attachment.size_bytes);
  const commonProps = {
    href: attachment.storage_url,
    target: "_blank",
    rel: "noreferrer",
    "data-testid": testid || `chat-attachment-${attachment.id}`,
  };

  if (image) {
    return (
      <a {...commonProps} className="block mt-1">
        <img
          src={attachment.storage_url}
          alt={attachment.name || "attachment"}
          className="rounded-lg border max-h-40 object-cover"
          style={{ maxWidth: 220 }}
        />
      </a>
    );
  }

  return (
    <a {...commonProps} className="text-xs underline block mt-1">
      📎 {attachment.name || "attachment"}
      {size ? <span className="opacity-60 ml-1">({size})</span> : null}
    </a>
  );
}

export default ChatAttachmentTile;
