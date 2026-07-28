/**
 * Phase B2 · Feb 2026 — Shared chat attachment tile.
 *
 * Rendered inline inside a chat message bubble. Handles both the
 * F0-native shape (F2b/F2c/portal chat) and legacy chat_attachments
 * shape (TeamChat's original storage) through flexible field access.
 *
 * Accepted attachment shapes:
 *   F0 hydration (portal_chats + TeamChat when using F0 files):
 *     { id, filename, mime, size, signed_url }
 *   Legacy chat_attachments:
 *     { id, name, mime, size_bytes, storage_url, type }
 *
 * Image tiles render a thumbnail; non-image tiles render a paperclip
 * icon + filename + size. Missing url → grey placeholder card.
 *
 * Accessibility:
 *   • images have ``alt``,
 *   • download link has ``aria-label``,
 *   • whole tile is a keyboard-focusable <a>.
 *
 * Used by:
 *   • pages/chat/TeamChatPage.jsx  (staff-side)
 *   • pages/portal/PortalChatsPage.jsx  (customer + admin)
 */
import React from "react";

function attName(att) {
  return att.filename || att.name || att.original_filename || "attachment";
}
function attMime(att) {
  return String(att.mime || att.content_type || "").toLowerCase();
}
function attUrl(att) {
  return att.signed_url || att.storage_url || att.url || "";
}
function attSize(att) {
  return Number(att.size || att.size_bytes || 0);
}
function isImage(att) {
  if (!att) return false;
  if (att.type === "image") return true;
  return attMime(att).startsWith("image/");
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
  const name = attName(attachment);
  const url = attUrl(attachment);
  const size = humanSize(attSize(attachment));
  const tid = testid || `chat-attachment-${attachment.id}`;

  if (!url) {
    // Fallback grey placeholder when the tile has no url — do NOT
    // render a broken link. Preserves layout so message body stays
    // aligned.
    return (
      <div
        data-testid={tid}
        className="text-xs italic opacity-60 mt-1"
        role="note"
        aria-label={`Attachment ${name} unavailable`}
      >
        📎 {name} (unavailable)
      </div>
    );
  }

  const commonProps = {
    href: url,
    target: "_blank",
    rel: "noreferrer",
    "aria-label": `Download attachment ${name}`,
    "data-testid": tid,
  };

  if (isImage(attachment)) {
    return (
      <a {...commonProps} className="block mt-1 focus:outline focus:outline-2 focus:outline-blue-500 rounded-lg">
        <img
          src={url}
          alt={name}
          className="rounded-lg border max-h-40 object-cover"
          style={{ maxWidth: 220 }}
        />
      </a>
    );
  }

  return (
    <a
      {...commonProps}
      className="text-xs underline block mt-1 focus:outline focus:outline-2 focus:outline-blue-500 rounded"
    >
      📎 {name}
      {size ? <span className="opacity-60 ml-1">({size})</span> : null}
    </a>
  );
}

export default ChatAttachmentTile;
