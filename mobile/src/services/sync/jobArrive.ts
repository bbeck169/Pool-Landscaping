/**
 * Phase O3 · Enqueue `job.arrive` operation.
 *
 * When offline, the arrive/on-my-way action is queued in the O2 sync
 * queue and dispatched on reconnect. When online, it dispatches
 * immediately through the same queue path for consistency.
 */
import { enqueue } from "./queue";

/**
 * Enqueue a `job.arrive` operation. Returns the client UUID.
 */
export async function enqueueJobArrive(jobId: string): Promise<string> {
  return enqueue({
    op_type: "job.arrive",
    entity_id: jobId,
    endpoint: "/mobile/sync",
    method: "BATCH",
    payload: {
      job_id: jobId,
      arrived_at: new Date().toISOString(),
    },
  });
}
