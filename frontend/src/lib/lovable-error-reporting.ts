// Stub for Lovable error reporting — no-op in local/self-hosted builds.
export function reportLovableError(_error: unknown, _context?: Record<string, unknown>): void {
  // Not connected to any remote reporting service in this build.
}