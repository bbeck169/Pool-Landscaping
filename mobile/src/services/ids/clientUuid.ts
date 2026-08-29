/**
 * Phase O2 · Crypto-strong UUID v4 generator.
 *
 * Uses `react-native-get-random-values` polyfill so `uuid` v11
 * reads from `crypto.getRandomValues()` on both iOS and Android.
 *
 * IMPORTANT: the polyfill import MUST execute before `uuid` is
 * first required anywhere in the process — we guarantee that by
 * importing this module from the root layout boot path.
 */
import "react-native-get-random-values";
import { v4 as uuidv4 } from "uuid";

/**
 * Returns a crypto-strong RFC-4122 v4 UUID.
 *
 * Use for:
 *   • sync-queue idempotency keys
 *   • client-generated entity IDs (offline creates)
 *   • any context where collision = silent data loss
 */
export function clientUuid(): string {
  return uuidv4();
}

export default clientUuid;
