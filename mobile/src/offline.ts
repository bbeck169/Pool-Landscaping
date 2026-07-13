import NetInfo from "@react-native-community/netinfo";
import { useEffect, useState } from "react";
import { storage } from "@/src/utils/storage";
import { api } from "@/src/api";

/** Live connectivity state. Defaults to online so first paint isn't blocked. */
export function useOnline() {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const unsub = NetInfo.addEventListener((s) =>
      setOnline(!!s.isConnected && s.isInternetReachable !== false)
    );
    NetInfo.fetch().then((s) => setOnline(!!s.isConnected));
    return () => unsub();
  }, []);
  return online;
}

// ---------------- Jobs / schedule cache ----------------
const JOBS_CACHE = "cache_jobs";

export async function cacheJobs(key: string, data: any) {
  try {
    await storage.setItem(`${JOBS_CACHE}_${key}`, JSON.stringify(data));
  } catch {}
}

export async function getCachedJobs(key: string): Promise<any[] | null> {
  try {
    const s = await storage.getItem<string>(`${JOBS_CACHE}_${key}`, "");
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}

// ---------------- Pending photo upload queue ----------------
export type PendingPhoto = { id: string; jobId: string; data: string; label: string; created_at: string };
const PQ = "pending_photos";

async function getQueue(): Promise<PendingPhoto[]> {
  try {
    const s = await storage.getItem<string>(PQ, "");
    return s ? JSON.parse(s) : [];
  } catch {
    return [];
  }
}

async function setQueue(q: PendingPhoto[]) {
  await storage.setItem(PQ, JSON.stringify(q));
}

export async function queuePhoto(item: Omit<PendingPhoto, "id" | "created_at">) {
  const q = await getQueue();
  q.push({ ...item, id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, created_at: new Date().toISOString() });
  await setQueue(q);
}

export async function pendingForJob(jobId: string): Promise<PendingPhoto[]> {
  const q = await getQueue();
  return q.filter((i) => i.jobId === jobId);
}

export async function pendingCount(): Promise<number> {
  return (await getQueue()).length;
}

/** Upload every queued photo; keep any that still fail. Returns count uploaded. */
export async function flushPendingPhotos(): Promise<{ uploaded: number; remaining: number }> {
  const q = await getQueue();
  if (!q.length) return { uploaded: 0, remaining: 0 };
  const remaining: PendingPhoto[] = [];
  let uploaded = 0;
  for (const item of q) {
    try {
      await api.post(`/jobs/${item.jobId}/photos`, { data: item.data, label: item.label });
      uploaded++;
    } catch {
      remaining.push(item);
    }
  }
  await setQueue(remaining);
  return { uploaded, remaining: remaining.length };
}

// ---------------- Single job cache (offline detail + optimistic updates) ----------------
const JOB_CACHE = "cache_job";

export async function cacheJob(job: any) {
  try {
    if (job?.id) await storage.setItem(`${JOB_CACHE}_${job.id}`, JSON.stringify(job));
  } catch {}
}

export async function getCachedJob(id: string): Promise<any | null> {
  try {
    const s = await storage.getItem<string>(`${JOB_CACHE}_${id}`, "");
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}

// ---------------- Pending job mutations (status + field report) ----------------
export type PendingMutation = { id: string; path: string; body: any; created_at: string };
const MQ = "pending_mutations";

async function getMQ(): Promise<PendingMutation[]> {
  try {
    const s = await storage.getItem<string>(MQ, "");
    return s ? JSON.parse(s) : [];
  } catch {
    return [];
  }
}

async function setMQ(q: PendingMutation[]) {
  await storage.setItem(MQ, JSON.stringify(q));
}

/** Queue a PUT mutation (e.g. job status or field-report) to replay when back online. */
export async function queueMutation(path: string, body: any) {
  const q = await getMQ();
  q.push({ id: `m-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, path, body, created_at: new Date().toISOString() });
  await setMQ(q);
}

export async function pendingMutationCount(): Promise<number> {
  return (await getMQ()).length;
}

/** Replay queued mutations in order; keep any that still fail. */
export async function flushPendingMutations(): Promise<{ synced: number; remaining: number }> {
  const q = await getMQ();
  if (!q.length) return { synced: 0, remaining: 0 };
  const remaining: PendingMutation[] = [];
  let synced = 0;
  for (const m of q) {
    try {
      await api.put(m.path, m.body);
      synced++;
    } catch {
      remaining.push(m);
    }
  }
  await setMQ(remaining);
  return { synced, remaining: remaining.length };
}
