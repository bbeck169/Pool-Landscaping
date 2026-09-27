/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 3.
 *
 * Local Tiptap wrapper used by ``HeroEditor`` (hero heading /
 * sub-heading) and by ``MarketingFormsPage`` (section-type field
 * label). Emits HTML via ``onChange(html)`` on every user edit.
 *
 * ─── SECURITY BOUNDARY ────────────────────────────────────────
 * This extension list is the XSS containment for public-facing
 * rich-text output. The HTML this editor emits is persisted to
 * ``marketing_forms`` and rendered verbatim in two public-facing
 * surfaces:
 *   1. The admin preview + ``/widget-demo`` iframe (same origin).
 *   2. The embedded widget on tenant sites via ``/widget/form.js``
 *      (cross-origin — the visitor's browser executes it).
 *
 * ANY of the following, if added here, silently reopens the XSS
 * surface on the widget render path:
 *   * ``@tiptap/extension-image``  — enables ``<img src="...">``
 *     with arbitrary URLs (data:, javascript:, cross-origin
 *     tracking pixels).
 *   * A ``paste`` HTML handler that trusts the clipboard payload.
 *   * ``StarterKit.configure({ html: true })`` or a custom node
 *     with ``atom: true`` and raw HTML rendering.
 *   * A ``Link`` config without the ``validate`` allowlist.
 *
 * Any addition to the extension list REQUIRES:
 *   1. A DOMPurify pass on the widget render path (currently NOT
 *      present — the extension whitelist IS the sanitizer).
 *   2. A red-team sweep for javascript:, data:, blob:, vbscript:
 *      URIs across every mark and node type.
 *
 * See recon notes R6 (Phase 3 · 2026-02).
 * ──────────────────────────────────────────────────────────────
 */
import React, { useCallback, useEffect } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import TextStyle from "@tiptap/extension-text-style";
import Link from "@tiptap/extension-link";
import {
  Bold, Italic, Underline as UnderlineIcon,
  Link as LinkIcon, RemoveFormatting,
} from "lucide-react";

/**
 * ``Link.configure`` validate callback — locks ``href`` schemes to
 * ``http:``, ``https:``, ``mailto:``, ``tel:`` ONLY. Every other
 * scheme (``javascript:``, ``data:``, ``blob:``, ``vbscript:``,
 * relative paths, empty strings) returns ``false`` and Tiptap
 * silently drops the link mark. This is the XSS boundary for
 * anchor tags in rich-text output.
 */
function _validateLinkHref(href) {
  if (!href || typeof href !== "string") return false;
  const trimmed = href.trim().toLowerCase();
  // Allowlist: http: https: mailto: tel:
  return (
    trimmed.startsWith("http://") ||
    trimmed.startsWith("https://") ||
    trimmed.startsWith("mailto:") ||
    trimmed.startsWith("tel:")
  );
}

export default function RichTextField({
  value, onChange, placeholder, testid, minHeight,
}) {
  const _testid = testid || "rich-text-field";
  const _minHeight = minHeight || "3rem";

  const editor = useEditor({
    // XSS boundary — see the SECURITY BOUNDARY comment at the top
    // of this file. Do NOT add ``Image``, raw-HTML paste handlers,
    // or custom-HTML nodes without a DOMPurify hardening pass on
    // the widget render path.
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      Underline,
      TextStyle,
      Link.configure({
        openOnClick: false,
        autolink: true,
        validate: _validateLinkHref,
        HTMLAttributes: {
          rel: "noopener noreferrer",
          target: "_blank",
        },
      }),
    ],
    content: value || "",
    editorProps: {
      attributes: {
        class: "prose prose-sm max-w-none px-3 py-2 focus:outline-none",
        "data-testid": `${_testid}-content`,
        style: `min-height: ${_minHeight}`,
      },
    },
    onUpdate: ({ editor: ed }) => {
      if (typeof onChange === "function") onChange(ed.getHTML());
    },
  });

  // Sync external value → editor when the prop changes (load / revert).
  useEffect(() => {
    if (!editor) return;
    const current = editor.getHTML();
    if ((value || "") !== current) {
      editor.commands.setContent(value || "", false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, editor]);

  const insertLink = useCallback(() => {
    if (!editor) return;
    const prev = editor.getAttributes("link")?.href || "";
    // eslint-disable-next-line no-alert
    const url = window.prompt("URL (leave empty to remove link):", prev);
    if (url === null) return;
    if (url === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    // Trust the validate callback — if the URL fails the allowlist,
    // Tiptap drops the mark silently and the visible output is
    // unchanged. No need to duplicate the check here.
    editor.chain().focus().extendMarkRange("link")
      .setLink({ href: url }).run();
  }, [editor]);

  const clearFormatting = useCallback(() => {
    if (!editor) return;
    editor.chain().focus().unsetAllMarks().clearNodes().run();
  }, [editor]);

  if (!editor) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-3 text-sm text-zinc-400"
           data-testid={`${_testid}-loading`}>
        Loading editor…
      </div>
    );
  }

  const btn = (active, tid, onClick, children, label) => (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      data-testid={tid}
      className={`p-1 rounded transition ${
        active ? "bg-zinc-200 text-zinc-900" : "text-zinc-600 hover:bg-zinc-100"
      }`}
    >
      {children}
    </button>
  );

  return (
    <div className="rounded-lg border border-zinc-200 bg-white overflow-hidden"
         data-testid={_testid}>
      <div className="flex items-center gap-0.5 px-2 py-1 border-b border-zinc-200 bg-zinc-50">
        {btn(editor.isActive("bold"), `${_testid}-btn-bold`,
             () => editor.chain().focus().toggleBold().run(),
             <Bold className="w-3.5 h-3.5" />, "Bold")}
        {btn(editor.isActive("italic"), `${_testid}-btn-italic`,
             () => editor.chain().focus().toggleItalic().run(),
             <Italic className="w-3.5 h-3.5" />, "Italic")}
        {btn(editor.isActive("underline"), `${_testid}-btn-underline`,
             () => editor.chain().focus().toggleUnderline().run(),
             <UnderlineIcon className="w-3.5 h-3.5" />, "Underline")}
        <span className="mx-1 h-4 w-px bg-zinc-200" />
        {btn(editor.isActive("link"), `${_testid}-btn-link`,
             insertLink, <LinkIcon className="w-3.5 h-3.5" />, "Insert link")}
        <span className="mx-1 h-4 w-px bg-zinc-200" />
        {btn(false, `${_testid}-btn-clear`,
             clearFormatting, <RemoveFormatting className="w-3.5 h-3.5" />,
             "Clear formatting")}
      </div>
      <EditorContent editor={editor} />
      {placeholder && !value ? (
        <div className="px-3 py-1 text-xs text-zinc-400 pointer-events-none"
             data-testid={`${_testid}-placeholder`}>
          {placeholder}
        </div>
      ) : null}
    </div>
  );
}
