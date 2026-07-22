/**
 * Phase 9B · Feb 2026 — TemplateEditor.
 *
 * Two modes:
 *   * ``email`` — TipTap rich editor with toolbar (bold/italic/underline/
 *     strike/H1-H3/lists/blockquote/link/image/color/align/undo/redo)
 *     + Insert-Merge-Tag button. HTML source toggle at far right.
 *   * ``sms`` — plain Textarea with GSM-7-aware segment counter, plus
 *     an Insert-Merge-Tag button that inserts at cursor.
 *
 * Emits ``onChange(html)`` for email, ``onChange(text)`` for SMS.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bold, Italic, Underline as UnderlineIcon, Strikethrough,
  Heading1, Heading2, Heading3,
  List, ListOrdered, Quote,
  Link as LinkIcon, Image as ImageIcon,
  AlignLeft, AlignCenter, AlignRight, AlignJustify,
  Undo, Redo, Palette, Code2, Plus,
} from "lucide-react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import { Color } from "@tiptap/extension-color";
import TextStyle from "@tiptap/extension-text-style";
import TextAlign from "@tiptap/extension-text-align";
import { MergeTagPalette } from "./MergeTagPalette";
import { MediaLibraryPicker } from "./MediaLibraryPicker";

const COLOR_SWATCHES = [
  "#111827", "#4B5563", "#6B7280", "#9CA3AF",
  "#DC2626", "#EA580C", "#CA8A04", "#16A34A",
  "#0284C7", "#4F46E5", "#9333EA", "#DB2777",
];

// GSM-7 basic character set + basic extension characters. Any character
// outside this set forces the message onto the UCS-2 (Unicode) code
// path — 70-char segments instead of 160.
const GSM7_BASIC = /^[A-Za-z0-9@£$¥èéùìòÇØøÅå\u0394_\u03a6\u0393\u039b\u03a9\u03a0\u03a8\u03a3\u0398\u039eÆæßÉ !\"#¤%&'()*+,\-./:;<=>?¡ÄÖÑÜ§¿äöñüà\n\r ]*$/;
const GSM7_EXT = /[\^{}\\\[\]~|€]/;

export function TemplateEditor({ mode = "email", value = "", onChange, tenantId }) {
  // Thin dispatcher — each concrete editor owns its own hooks so we
  // never violate rules-of-hooks with a conditional early return.
  if (mode === "sms") {
    return <SmsEditor value={value} onChange={onChange} />;
  }
  return <EmailEditor value={value} onChange={onChange} />;
}


function EmailEditor({ value = "", onChange }) {
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mediaOpen, setMediaOpen] = useState(false);
  const [colorOpen, setColorOpen] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      Underline,
      TextStyle,
      Color,
      Image.configure({ inline: false, allowBase64: false }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" },
      }),
      Placeholder.configure({
        placeholder: "Write your email — use +Tag to insert a merge tag.",
      }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
    ],
    content: value || "",
    editorProps: {
      attributes: {
        class: "prose prose-sm max-w-none min-h-[280px] px-4 py-3 focus:outline-none",
        "data-testid": "template-editor-content",
      },
    },
    onUpdate: ({ editor }) => {
      if (typeof onChange === "function") onChange(editor.getHTML());
    },
  });

  // Sync external value → editor when the prop changes (revert / load).
  useEffect(() => {
    if (!editor) return;
    const current = editor.getHTML();
    if (value !== current) {
      editor.commands.setContent(value || "", false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, editor]);

  const insertText = useCallback((text) => {
    if (!editor) return;
    editor.chain().focus().insertContent(text).run();
  }, [editor]);

  function insertLink() {
    const prev = editor?.getAttributes("link")?.href || "";
    // eslint-disable-next-line no-alert
    const url = window.prompt("URL (leave empty to remove link):", prev);
    if (url === null) return;
    if (url === "") {
      editor?.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    editor?.chain().focus().extendMarkRange("link")
      .setLink({ href: url }).run();
  }

  function pickImage() { setMediaOpen(true); }

  if (!editor) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-4 text-sm text-zinc-400">
        Loading editor…
      </div>
    );
  }

  const btn = (active, testid, onClick, children, label) => (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      data-testid={testid}
      className={`p-1.5 rounded transition ${
        active ? "bg-zinc-200 text-zinc-900" : "text-zinc-600 hover:bg-zinc-100"
      }`}
    >
      {children}
    </button>
  );

  return (
    <div className="rounded-xl border border-zinc-200 bg-white overflow-hidden"
         data-testid="template-editor-email">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-0.5 px-2 py-1.5 border-b border-zinc-200 bg-zinc-50">
        {btn(editor.isActive("bold"), "editor-btn-bold",
             () => editor.chain().focus().toggleBold().run(),
             <Bold className="w-4 h-4" />, "Bold")}
        {btn(editor.isActive("italic"), "editor-btn-italic",
             () => editor.chain().focus().toggleItalic().run(),
             <Italic className="w-4 h-4" />, "Italic")}
        {btn(editor.isActive("underline"), "editor-btn-underline",
             () => editor.chain().focus().toggleUnderline().run(),
             <UnderlineIcon className="w-4 h-4" />, "Underline")}
        {btn(editor.isActive("strike"), "editor-btn-strike",
             () => editor.chain().focus().toggleStrike().run(),
             <Strikethrough className="w-4 h-4" />, "Strikethrough")}
        <span className="mx-1 h-5 w-px bg-zinc-200" />
        {btn(editor.isActive("heading", { level: 1 }), "editor-btn-h1",
             () => editor.chain().focus().toggleHeading({ level: 1 }).run(),
             <Heading1 className="w-4 h-4" />, "Heading 1")}
        {btn(editor.isActive("heading", { level: 2 }), "editor-btn-h2",
             () => editor.chain().focus().toggleHeading({ level: 2 }).run(),
             <Heading2 className="w-4 h-4" />, "Heading 2")}
        {btn(editor.isActive("heading", { level: 3 }), "editor-btn-h3",
             () => editor.chain().focus().toggleHeading({ level: 3 }).run(),
             <Heading3 className="w-4 h-4" />, "Heading 3")}
        <span className="mx-1 h-5 w-px bg-zinc-200" />
        {btn(editor.isActive("bulletList"), "editor-btn-ul",
             () => editor.chain().focus().toggleBulletList().run(),
             <List className="w-4 h-4" />, "Bulleted list")}
        {btn(editor.isActive("orderedList"), "editor-btn-ol",
             () => editor.chain().focus().toggleOrderedList().run(),
             <ListOrdered className="w-4 h-4" />, "Numbered list")}
        {btn(editor.isActive("blockquote"), "editor-btn-quote",
             () => editor.chain().focus().toggleBlockquote().run(),
             <Quote className="w-4 h-4" />, "Blockquote")}
        <span className="mx-1 h-5 w-px bg-zinc-200" />
        {btn(editor.isActive("link"), "editor-btn-link",
             insertLink, <LinkIcon className="w-4 h-4" />, "Insert link")}
        {btn(false, "editor-btn-image",
             pickImage, <ImageIcon className="w-4 h-4" />, "Insert image")}
        <div className="relative">
          {btn(colorOpen, "editor-btn-color",
               () => setColorOpen((v) => !v),
               <Palette className="w-4 h-4" />, "Text color")}
          {colorOpen && (
            <div className="absolute z-20 top-full left-0 mt-1 bg-white border border-zinc-200 rounded-lg shadow-lg p-2 flex flex-col gap-2 w-52">
              <div className="grid grid-cols-6 gap-1">
                {COLOR_SWATCHES.map((c) => (
                  <button key={c}
                          onClick={() => {
                            editor.chain().focus().setColor(c).run();
                            setColorOpen(false);
                          }}
                          data-testid={`editor-color-swatch-${c}`}
                          title={c}
                          className="w-6 h-6 rounded border border-zinc-200"
                          style={{ background: c }}/>
                ))}
              </div>
              <input
                type="color"
                onChange={(e) => editor.chain().focus().setColor(e.target.value).run()}
                data-testid="editor-color-custom"
                className="w-full h-8 cursor-pointer"
              />
              <button onClick={() => {
                        editor.chain().focus().unsetColor().run();
                        setColorOpen(false);
                      }}
                      className="text-xs text-zinc-500 hover:text-zinc-900">
                Reset color
              </button>
            </div>
          )}
        </div>
        <span className="mx-1 h-5 w-px bg-zinc-200" />
        {btn(editor.isActive({ textAlign: "left" }), "editor-btn-align-left",
             () => editor.chain().focus().setTextAlign("left").run(),
             <AlignLeft className="w-4 h-4" />, "Align left")}
        {btn(editor.isActive({ textAlign: "center" }), "editor-btn-align-center",
             () => editor.chain().focus().setTextAlign("center").run(),
             <AlignCenter className="w-4 h-4" />, "Align center")}
        {btn(editor.isActive({ textAlign: "right" }), "editor-btn-align-right",
             () => editor.chain().focus().setTextAlign("right").run(),
             <AlignRight className="w-4 h-4" />, "Align right")}
        {btn(editor.isActive({ textAlign: "justify" }), "editor-btn-align-justify",
             () => editor.chain().focus().setTextAlign("justify").run(),
             <AlignJustify className="w-4 h-4" />, "Justify")}
        <span className="mx-1 h-5 w-px bg-zinc-200" />
        {btn(false, "editor-btn-undo",
             () => editor.chain().focus().undo().run(),
             <Undo className="w-4 h-4" />, "Undo")}
        {btn(false, "editor-btn-redo",
             () => editor.chain().focus().redo().run(),
             <Redo className="w-4 h-4" />, "Redo")}
        <span className="mx-1 h-5 w-px bg-zinc-200" />
        <button
          type="button"
          onClick={() => setMergeOpen(true)}
          data-testid="editor-btn-merge-tag"
          className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-zinc-700 bg-white border border-zinc-200 hover:bg-zinc-50"
        >
          <Plus className="w-3.5 h-3.5" />
          Tag
        </button>
        <span className="ml-auto" />
        {btn(showSource, "editor-btn-source",
             () => setShowSource((v) => !v),
             <Code2 className="w-4 h-4" />, "HTML source")}
      </div>

      {/* Body */}
      {showSource ? (
        <textarea
          value={value}
          onChange={(e) => onChange && onChange(e.target.value)}
          data-testid="template-editor-source"
          className="w-full min-h-[280px] px-4 py-3 font-mono text-sm focus:outline-none"
        />
      ) : (
        <EditorContent editor={editor} />
      )}

      <MergeTagPalette
        open={mergeOpen}
        onOpenChange={setMergeOpen}
        onInsert={(token) => insertText(token)}
      />
      <MediaLibraryPicker
        open={mediaOpen}
        onOpenChange={setMediaOpen}
        onSelect={(m) => {
          if (m?.cdn_url || m?.url) {
            editor.chain().focus().setImage({
              src: m.cdn_url || m.url,
              alt: m.alt_text || "",
            }).run();
          }
        }}
      />
    </div>
  );
}


// ═══════════════════════════ SMS Editor ═══════════════════════════════
function SmsEditor({ value = "", onChange }) {
  const [mergeOpen, setMergeOpen] = useState(false);
  const ref = useRef(null);
  const { chars, isUnicode, segmentSize, segments } = computeSmsSegments(value);
  const remaining = segmentSize - (chars % segmentSize || segmentSize);

  function insertAtCursor(text) {
    const el = ref.current;
    if (!el) {
      onChange?.((value || "") + text);
      return;
    }
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const next = (value || "").slice(0, start) + text + (value || "").slice(end);
    onChange?.(next);
    setTimeout(() => {
      el.focus();
      const cursor = start + text.length;
      el.setSelectionRange(cursor, cursor);
    }, 0);
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white overflow-hidden"
         data-testid="template-editor-sms">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-200 bg-zinc-50">
        <button
          type="button"
          onClick={() => setMergeOpen(true)}
          data-testid="editor-btn-merge-tag"
          className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-zinc-700 bg-white border border-zinc-200 hover:bg-zinc-50"
        >
          <Plus className="w-3.5 h-3.5" />
          Tag
        </button>
        <span className="ml-auto text-xs text-zinc-500"
              data-testid="sms-char-counter">
          {chars} chars / {segments} {segments === 1 ? "segment" : "segments"}
          {isUnicode && (
            <span className="ml-2 text-orange-600 font-medium"
                  data-testid="sms-unicode-badge"
                  title="Unicode/emoji forces 70-char segments">
              Unicode
            </span>
          )}
          {" · "}
          <span title="Characters left in current segment">
            {remaining} to next segment
          </span>
        </span>
      </div>
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        data-testid="sms-textarea"
        placeholder="Hi {{CUSTOMER_FIRST_NAME}}, your service is scheduled…"
        className="w-full min-h-[200px] px-4 py-3 text-sm focus:outline-none"
      />
      <MergeTagPalette
        open={mergeOpen}
        onOpenChange={setMergeOpen}
        onInsert={(token) => { insertAtCursor(token); setMergeOpen(false); }}
      />
    </div>
  );
}


// Exposed for unit tests + preview rendering. Returns:
//   { chars, isUnicode, segmentSize, segments }
export function computeSmsSegments(text) {
  const str = String(text || "");
  const isUnicode = !!(str && (!GSM7_BASIC.test(str) || GSM7_EXT.test(str)));
  const segmentSize = isUnicode ? 70 : 160;
  const chars = str.length;
  const segments = chars === 0 ? 0 : Math.ceil(chars / segmentSize);
  return { chars, isUnicode, segmentSize, segments };
}
