/**
 * mapApiError — classifies API errors for correct UI presentation.
 *
 * Consumers use `kind` to pick the icon/color and `title`/`message` for
 * the copy, instead of showing "You're offline" for every error.
 */
import { ApiError } from "@/src/api";

export type ErrorKind =
  | "auth"       // 401 – session expired
  | "forbidden"  // 403 – not authorized
  | "not_found"  // 404
  | "server"     // 5xx
  | "offline"    // network failure (no response)
  | "client";    // other 4xx

export type MappedError = {
  title: string;
  message: string;
  kind: ErrorKind;
  status?: number;
};

export function mapApiError(err: unknown): MappedError {
  if (err instanceof ApiError) {
    const detail =
      typeof err.detail === "string"
        ? err.detail
        : err.message || "An error occurred.";

    if (err.status === 401) {
      return { title: "Session expired", message: detail, kind: "auth", status: 401 };
    }
    if (err.status === 403) {
      return {
        title: "Not authorized",
        message: detail || "You don't have permission to access this.",
        kind: "forbidden",
        status: 403,
      };
    }
    if (err.status === 404) {
      return {
        title: "Not found",
        message: detail || "The resource doesn't exist.",
        kind: "not_found",
        status: 404,
      };
    }
    if (err.status >= 500) {
      return {
        title: "Server error",
        message: detail || "Something went wrong on the server.",
        kind: "server",
        status: err.status,
      };
    }
    // Other 4xx
    return {
      title: "Something went wrong",
      message: detail,
      kind: "client",
      status: err.status,
    };
  }

  // ApiNetworkError or plain Error with no response
  if (err && typeof err === "object" && (err as any).kind === "network") {
    return {
      title: "You're offline",
      message: "Check your connection and try again.",
      kind: "offline",
    };
  }

  // Fallback for unknown errors
  const msg = err instanceof Error ? err.message : String(err || "Unknown error");
  return { title: "You're offline", message: msg, kind: "offline" };
}

/** Returns the Ionicons icon name appropriate for each error kind. */
export function errorKindIcon(kind: ErrorKind): string {
  switch (kind) {
    case "auth":      return "log-in-outline";
    case "forbidden": return "lock-closed-outline";
    case "not_found": return "help-circle-outline";
    case "server":    return "warning-outline";
    case "offline":   return "cloud-offline-outline";
    case "client":    return "alert-circle-outline";
    default:          return "alert-circle-outline";
  }
}
