/**
 * executeMarco — client wrapper for the MARCO voice-command pipeline.
 *
 * 1) POST /api/audio/transcribe  (multipart, m4a file)
 * 2) POST /api/marco/execute     (JSON, transcript + context)
 */
import { getToken } from "@/src/api";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";

/* ── types ─────────────────────────────────────────────────────── */
export interface TranscribeResult {
  transcript: string;
  language: string;
  duration_sec: number | null;
  model: string;
}

export interface MarcoResult {
  action: string;
  ok: boolean;
  message: string;
  speak?: string;
  meta: Record<string, any>;
  raw_llm?: string;
}

export type MarcoScreen = "job_detail" | "service_report";

/* ── transcribe ────────────────────────────────────────────────── */
export async function transcribeAudio(fileUri: string): Promise<TranscribeResult> {
  const token = await getToken();
  const form = new FormData();
  form.append("file", {
    uri: fileUri,
    name: `marco-${Date.now()}.m4a`,
    type: "audio/x-m4a",
  } as any);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);

  try {
    const res = await fetch(`${BASE}/api/audio/transcribe`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!res.ok) {
      const data = await res.json().catch(() => null);
      const code = data?.detail?.code || data?.code || "";
      if (res.status === 413) throw new MarcoError("Audio too long. Keep it under 25 MB.", "AUDIO_TOO_LARGE");
      if (res.status === 502) throw new MarcoError("MARCO couldn't hear that. Try again.", "WHISPER_UPSTREAM_ERROR");
      throw new MarcoError(
        code === "EMPTY_FILE"
          ? "No audio recorded. Tap and speak, then tap again."
          : `Transcription failed (${res.status}).`,
        code || "TRANSCRIBE_FAILED",
      );
    }
    return await res.json();
  } catch (e: any) {
    clearTimeout(timer);
    if (e instanceof MarcoError) throw e;
    if (e?.name === "AbortError") throw new MarcoError("Transcription timed out. Try again.", "TIMEOUT");
    throw new MarcoError("MARCO connection issue. Try again.", "NETWORK");
  }
}

/* ── execute ───────────────────────────────────────────────────── */
export async function executeMarco(
  transcript: string,
  screen: MarcoScreen,
  entityId: string,
): Promise<MarcoResult> {
  const token = await getToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);

  try {
    const res = await fetch(`${BASE}/api/marco/execute`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ transcript, screen, entity_id: entityId }),
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!res.ok) {
      if (res.status === 502) throw new MarcoError("MARCO connection issue. Try again.", "UPSTREAM_ERROR");
      const data = await res.json().catch(() => null);
      throw new MarcoError(
        data?.detail?.message || data?.message || `MARCO failed (${res.status}).`,
        data?.detail?.code || "EXECUTE_FAILED",
      );
    }
    return await res.json();
  } catch (e: any) {
    clearTimeout(timer);
    if (e instanceof MarcoError) throw e;
    if (e?.name === "AbortError") throw new MarcoError("MARCO timed out. Try again.", "TIMEOUT");
    throw new MarcoError("MARCO connection issue. Try again.", "NETWORK");
  }
}

/* ── error class ───────────────────────────────────────────────── */
export class MarcoError extends Error {
  code: string;
  constructor(message: string, code: string) {
    super(message);
    this.name = "MarcoError";
    this.code = code;
  }
}
