/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../components/urbanflow/App.jsx";
import {
  parseErrorMessage,
  createCanonicalError,
  sanitizeErrorMessage,
  getStatusFallback,
} from "../lib/error-parser";

describe("Issue #7: Electron Protocol & Frontend Error Standardization", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    localStorage.clear();
    document.documentElement.dataset.theme = "dark";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          status: "ok",
          authenticated: true,
          geminiAvailable: false,
        }),
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Invalid request
  it("1. Handles invalid request error responses adhering to canonical schema", () => {
    const errorBody = {
      ok: false,
      error: "Invalid request: unsupported HTTP method",
      detail: "Invalid request: unsupported HTTP method",
    };
    const message = parseErrorMessage(errorBody, 400);
    expect(message).toBe("Invalid request: unsupported HTTP method");
  });

  // 2. Missing parameters
  it("2. Handles missing required parameter errors", () => {
    const errorBody = {
      ok: false,
      error: "Missing required parameter: report_id",
      detail: "Missing required parameter: report_id",
    };
    const message = parseErrorMessage(errorBody, 400);
    expect(message).toBe("Missing required parameter: report_id");
  });

  // 3. Invalid video upload
  it("3. Handles invalid video upload with format and magic byte mismatch", () => {
    const errorBody = {
      ok: false,
      error: "Unsupported video format '.exe' for north. Allowed: .mp4, .avi",
      detail: "Unsupported video format '.exe' for north. Allowed: .mp4, .avi",
    };
    const message = parseErrorMessage(errorBody, 400);
    expect(message).toContain("Unsupported video format");
  });

  // 4. Authentication failure
  it("4. Handles authentication failure (401) with clean message", () => {
    const errorBody = {
      ok: false,
      error: "Unauthorized: session token is missing or invalid",
      detail: "Unauthorized: session token is missing or invalid",
    };
    const message = parseErrorMessage(errorBody, 401);
    expect(message).toBe("Unauthorized: session token is missing or invalid");
  });

  // 5. Authorization failure
  it("5. Handles authorization failure (403) with clean message", () => {
    const errorBody = {
      ok: false,
      error: "Forbidden: action requires scope 'inference:write'",
      detail: "Forbidden: action requires scope 'inference:write'",
    };
    const message = parseErrorMessage(errorBody, 403);
    expect(message).toBe("Forbidden: action requires scope 'inference:write'");
  });

  // 6. Rate limiting
  it("6. Handles rate limiting (429) cleanly", () => {
    const errorBody = {
      ok: false,
      error: "Rate limit exceeded. Maximum 60 requests per minute.",
      detail: "Rate limit exceeded. Maximum 60 requests per minute.",
    };
    const message = parseErrorMessage(errorBody, 429);
    expect(message).toBe("Rate limit exceeded. Maximum 60 requests per minute.");
  });

  // 7. Backend unavailable
  it("7. Handles backend unavailable (503) fallback gracefully", () => {
    const errorBody = null; // Backend process was terminated or unreachable
    const message = parseErrorMessage(errorBody, 503);
    expect(message).toBe("Backend service is currently initializing or unavailable.");
  });

  // 8. Timeout
  it("8. Handles request timeout (504) fallback gracefully", () => {
    const message = parseErrorMessage(null, 504);
    expect(message).toBe("Request timed out while waiting for processing.");
  });

  // 9. Cancellation
  it("9. Handles cancellation (499) cleanly", () => {
    const errorBody = {
      ok: false,
      error: "Request was cancelled by user.",
      detail: "Request was cancelled by user.",
    };
    const message = parseErrorMessage(errorBody, 499);
    expect(message).toBe("Request was cancelled by user.");
  });

  // 10. Malformed JSON
  it("10. Handles malformed JSON payload responses", () => {
    const errorBody = {
      ok: false,
      error: "Malformed JSON in request body.",
      detail: "Malformed JSON in request body.",
    };
    const message = parseErrorMessage(errorBody, 400);
    expect(message).toBe("Malformed JSON in request body.");
  });

  // 11. Unknown protocol route
  it("11. Handles unknown protocol route (404)", () => {
    const errorBody = {
      ok: false,
      error: "API route not found: GET /api/unknown-endpoint",
      detail: "API route not found: GET /api/unknown-endpoint",
    };
    const message = parseErrorMessage(errorBody, 404);
    expect(message).toBe("API route not found: GET /api/unknown-endpoint");
  });

  // 12. Internal exception without stack trace or local path disclosure
  it("12. Sanitizes internal exceptions and redacts Windows/POSIX paths and stack traces", () => {
    const rawError = "Error: Failed at C:\\Users\\HARSH AGGARWAL\\Urban-Flow\\backend\\inference.py:45\n    at Object.run (C:\\Users\\HARSH AGGARWAL\\Urban-Flow\\main.cjs:100:12)";
    const sanitized = sanitizeErrorMessage(rawError);
    expect(sanitized).not.toContain("C:\\Users\\HARSH AGGARWAL");
    expect(sanitized).not.toContain("at Object.run");
    expect(sanitized).toContain("inference.py");
  });

  // 13. Error response JSON validity
  it("13. Generates valid JSON adhering strictly to canonical schema", () => {
    const canonical = createCanonicalError("Database connection failed", 500);
    expect(canonical.ok).toBe(false);
    expect(canonical.error).toBe("Database connection failed");
    expect(canonical.detail).toBe("Database connection failed");

    const jsonString = JSON.stringify(canonical);
    const parsed = JSON.parse(jsonString);
    expect(parsed).toEqual({
      ok: false,
      error: "Database connection failed",
      detail: "Database connection failed",
    });
  });

  // 14. HTTP status preservation
  it("14. Preserves appropriate status fallback mappings across HTTP codes", () => {
    expect(getStatusFallback(400)).toContain("Invalid request");
    expect(getStatusFallback(401)).toContain("Authentication required");
    expect(getStatusFallback(403)).toContain("Access denied");
    expect(getStatusFallback(404)).toContain("Requested resource");
    expect(getStatusFallback(413)).toContain("Uploaded payload exceeds");
    expect(getStatusFallback(422)).toContain("Validation failed");
    expect(getStatusFallback(429)).toContain("Too many requests");
    expect(getStatusFallback(503)).toContain("Backend service is currently initializing");
    expect(getStatusFallback(504)).toContain("Request timed out");
  });

  // 15. Frontend error rendering
  it("15. Renders frontend error messages without throwing or crashing the UI", async () => {
    // Mock simulation API call to fail with canonical error
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (url: string) => {
        if (url.includes("/api/simulate")) {
          return {
            ok: false,
            status: 400,
            json: async () => ({
              ok: false,
              error: "Vehicle counts must be positive integers.",
              detail: "Vehicle counts must be positive integers.",
            }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({ status: "ok" }),
        };
      })
    );

    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    );

    // Switch to simulation tab
    const simTab = screen.getByRole("button", { name: /simulated data/i });
    act(() => {
      fireEvent.click(simTab);
    });

    // Click "Use simulated traffic data" button
    const submitBtn = screen.getByRole("button", { name: /use simulated traffic data/i });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    // Verify error message is rendered in UI
    expect(screen.getByText("Vehicle counts must be positive integers.")).toBeInTheDocument();
  });

  // 16. Empty error values
  it("16. Gracefully handles empty error strings and returns safe fallback", () => {
    const errorEmpty = { ok: false, error: "", detail: "" };
    const parsed = parseErrorMessage(errorEmpty, 400);
    expect(parsed).toBe("Invalid request or malformed parameters.");
    expect(parsed).not.toBe("");
    expect(parsed).not.toBe("undefined");
  });

  // 17. Unexpected response objects (Never display [object Object])
  it("17. Never displays [object Object] for arbitrary objects or FastAPI 422 lists", () => {
    // Case A: FastAPI 422 validation error list
    const fastApiValidation = {
      detail: [
        { loc: ["body", "counts", "North"], msg: "Ensure this value is greater than 0" },
      ],
    };
    const parsedA = parseErrorMessage(fastApiValidation, 422);
    expect(parsedA).toBe("counts -> North: Ensure this value is greater than 0");
    expect(parsedA).not.toBe("[object Object]");

    // Case B: Arbitrary unexpected nested object
    const arbitraryObj = {
      error: { reason: "Subsystem timeout", code: 99 },
    };
    const parsedB = parseErrorMessage(arbitraryObj, 500);
    expect(parsedB).not.toBe("[object Object]");
    expect(typeof parsedB).toBe("string");

    // Case C: Literal string "[object Object]"
    const literalBadString = "[object Object]";
    const parsedC = parseErrorMessage(literalBadString, 500);
    expect(parsedC).toBe("Internal server error. Please try again later.");
  });
});
