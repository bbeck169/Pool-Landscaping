/**
 * Phase F1 · Feb 2026 — dev smoke-test page for the file components.
 *
 * Reachable at ``/dev/file-upload`` in preview only (route gated by
 * ``REACT_APP_PUBLIC_ENV === "preview"``). Not a real user surface —
 * F2 will wire the real customer / job / persona / portal flows.
 */
import React, { useCallback, useState } from "react";
import { FileUpload } from "@/components/files/FileUpload";
import { FileList } from "@/components/files/FileList";

export default function FileUploadDemoPage() {
  const [reloadKey, setReloadKey] = useState(0);
  const forceRefresh = useCallback(() => setReloadKey((k) => k + 1), []);

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8"
          data-testid="file-upload-demo-page">
      <h1 className="text-2xl font-bold mb-1">File Upload · dev smoke test</h1>
      <p className="text-sm text-zinc-500 mb-6">
        Preview-only route — verifies the F0 backend + F1 shared
        components end-to-end. Uploads land in
        <code className="mx-1 px-1 rounded bg-zinc-100">poolscape-crm/&lt;tenant&gt;/dev_smoke/…</code>.
      </p>

      <section className="mb-6">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-600 mb-2">
          Upload
        </h2>
        <FileUpload
          purpose="dev_smoke"
          linkedEntityType="dev"
          linkedEntityId="local_test"
          accept="image/*"
          onUploaded={forceRefresh}
        />
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-600 mb-2">
          Recent files
        </h2>
        <FileList
          key={reloadKey}
          linkedEntityType="dev"
          linkedEntityId="local_test"
          canDelete
          onChange={() => {}}
        />
      </section>
    </div>
  );
}
