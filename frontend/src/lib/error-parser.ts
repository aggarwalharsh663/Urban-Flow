/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

/**
 * Standard Canonical Error Response Schema (Issue #7)
 * Every error returned across Electron protocols, IPC, and REST endpoints conforms to:
 * {
 *   ok: false,
 *   error: string,
 *   detail: string
 * }
 */
export interface CanonicalErrorResponse {
  ok: false;
  error: string;
  detail: string;
}

/**
 * Sanitizes raw text to prevent accidental exposure of local filesystem paths,
 * tokens, control characters, or raw JavaScript stack trace strings.
 */
export function sanitizeErrorMessage(text: string): string {
  if (!text || typeof text !== "string") {
    return "The request could not be completed.";
  }

  let clean = text.trim();

  // Strip stack trace lines and keep only the primary error description line
  if (clean.includes("\n") || clean.includes("\r")) {
    clean = clean.split(/\r?\n/)[0].trim();
  }
  clean = clean.replace(/^Error:\s*/i, "").trim();

  // Strip control characters
  clean = clean.replace(/[\x00-\x08\x0b-\x1f]/g, "").trim();

  // Redact local Windows absolute paths (e.g. C:\Users\... -> file.ext)
  clean = clean.replace(/[a-zA-Z]:\\(?:[^"'\s\n\r<>]+\\)+[^"'\s\n\r<>]*/g, (matched) => {
    const parts = matched.split("\\");
    return parts[parts.length - 1] || "[path]";
  });

  // Redact POSIX system absolute paths (e.g. /home/..., /Users/... -> file.ext), preserving API routes like /api/...
  clean = clean.replace(/\/(?:home|Users|usr|var|tmp|etc|opt|root|proc)(?:\/[a-zA-Z0-9_.-]+)+/gi, (matched) => {
    const parts = matched.split("/");
    return parts[parts.length - 1] || "[path]";
  });

  return clean || "The request could not be completed.";
}

/**
 * Maps an HTTP status code to a human-readable generic error message.
 */
export function getStatusFallback(status?: number, defaultFallback: string = "The request could not be completed."): string {
  if (!status) return defaultFallback;
  switch (status) {
    case 400:
      return "Invalid request or malformed parameters.";
    case 401:
      return "Authentication required or invalid session token.";
    case 403:
      return "Access denied or unauthorized action.";
    case 404:
      return "Requested resource or route not found.";
    case 413:
      return "Uploaded payload exceeds allowable size limits.";
    case 422:
      return "Validation failed. Please verify submitted values.";
    case 429:
      return "Too many requests. Please wait a moment before retrying.";
    case 499:
      return "Request was cancelled.";
    case 502:
    case 503:
      return "Backend service is currently initializing or unavailable.";
    case 504:
      return "Request timed out while waiting for processing.";
    default:
      if (status >= 500) {
        return "Internal server error. Please try again later.";
      }
      return defaultFallback;
  }
}

/**
 * Safely parses any error payload, response body, or Error instance into a clean,
 * human-readable string for user display.
 *
 * Evaluation Priority:
 * 1. `error` (if non-empty string)
 * 2. `detail` (if non-empty string, or formatted if array/object)
 * 3. `message` (if non-empty string)
 * 4. Safe generic fallback message (derived from HTTP status code if present)
 *
 * Guarantees:
 * - Never returns or renders `[object Object]`
 * - Never returns undefined or empty string
 * - Gracefully unpacks FastAPI 422 validation error arrays
 * - Redacts internal filesystem paths and sensitive stack traces
 */
export function parseErrorMessage(
  input: unknown,
  status?: number,
  fallback: string = "The request could not be completed."
): string {
  if (input === null || input === undefined) {
    return getStatusFallback(status, fallback);
  }

  // If input is an instance of Error
  if (input instanceof Error) {
    const errorWithBody = input as { body?: unknown; status?: number };
    if (errorWithBody.body && errorWithBody.body !== input) {
      return parseErrorMessage(errorWithBody.body, errorWithBody.status || status, fallback);
    }
    if (input.message && typeof input.message === "string" && input.message.trim().length > 0) {
      return parseErrorMessage(input.message, status, fallback);
    }
  }

  // If input is a string
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (trimmed.length === 0 || trimmed === "[object Object]") {
      return getStatusFallback(status, fallback);
    }
    // Attempt JSON parse in case a raw JSON error string was passed
    if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
      try {
        const parsed = JSON.parse(trimmed);
        return parseErrorMessage(parsed, status, fallback);
      } catch {
        // Not JSON, continue with string handling
      }
    }
    return sanitizeErrorMessage(trimmed);
  }

  // If input is an Array (e.g. FastAPI 422 validation error list)
  if (Array.isArray(input)) {
    if (input.length === 0) {
      return getStatusFallback(status, fallback);
    }
    const extracted = input
      .map((item) => {
        if (typeof item === "string" && item.trim()) return item.trim();
        if (item && typeof item === "object") {
          const loc = Array.isArray((item as any).loc)
            ? (item as any).loc.filter((l: unknown) => l !== "body").join(" -> ")
            : "";
          const msg = (item as any).msg || (item as any).message || (item as any).error;
          if (typeof msg === "string" && msg.trim()) {
            return loc ? `${loc}: ${msg.trim()}` : msg.trim();
          }
        }
        return null;
      })
      .filter((m): m is string => Boolean(m));

    if (extracted.length > 0) {
      return sanitizeErrorMessage(extracted.join("; "));
    }
    return getStatusFallback(status, fallback);
  }

  // If input is an Object
  if (typeof input === "object") {
    const obj = input as Record<string, unknown>;

    // 1. Priority 1: Check `error`
    if (typeof obj.error === "string" && obj.error.trim().length > 0) {
      const errTrim = obj.error.trim();
      if (errTrim !== "[object Object]") {
        return sanitizeErrorMessage(errTrim);
      }
    } else if (obj.error && typeof obj.error === "object") {
      const nested = parseErrorMessage(obj.error, status, "");
      if (nested && nested !== "[object Object]") {
        return sanitizeErrorMessage(nested);
      }
    }

    // 2. Priority 2: Check `detail`
    if (typeof obj.detail === "string" && obj.detail.trim().length > 0) {
      const detailTrim = obj.detail.trim();
      if (detailTrim !== "[object Object]") {
        return sanitizeErrorMessage(detailTrim);
      }
    } else if (Array.isArray(obj.detail)) {
      const fromArray = parseErrorMessage(obj.detail, status, "");
      if (fromArray && fromArray !== "[object Object]") {
        return sanitizeErrorMessage(fromArray);
      }
    } else if (obj.detail && typeof obj.detail === "object") {
      const nestedDetail = parseErrorMessage(obj.detail, status, "");
      if (nestedDetail && nestedDetail !== "[object Object]") {
        return sanitizeErrorMessage(nestedDetail);
      }
    }

    // 3. Priority 3: Check `message`
    if (typeof obj.message === "string" && obj.message.trim().length > 0) {
      const msgTrim = obj.message.trim();
      if (msgTrim !== "[object Object]") {
        return sanitizeErrorMessage(msgTrim);
      }
    }
  }

  // 4. Safe generic fallback
  return getStatusFallback(status, fallback);
}

/**
 * Creates a Canonical Error Response object following the established standard.
 */
export function createCanonicalError(
  message: string,
  status?: number
): CanonicalErrorResponse {
  const safeMessage = parseErrorMessage(message, status);
  return {
    ok: false,
    error: safeMessage,
    detail: safeMessage,
  };
}
