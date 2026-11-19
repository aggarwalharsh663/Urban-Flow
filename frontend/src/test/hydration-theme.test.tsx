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
import { useIsMobile } from "../hooks/use-mobile";

function ResponsiveTestComponent() {
  const isMobile = useIsMobile();
  return <div data-testid="mobile-indicator">{isMobile ? "mobile" : "desktop"}</div>;
}

describe("Issue #6: React Hydration & Theme State Safety", () => {
  let queryClient: QueryClient;
  let originalError: typeof console.error;
  let originalWarn: typeof console.warn;
  let errorSpy: ReturnType<typeof vi.fn>;
  let warnSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    localStorage.clear();
    document.documentElement.dataset.theme = "dark";

    originalError = console.error;
    originalWarn = console.warn;
    errorSpy = vi.fn();
    warnSpy = vi.fn();
    console.error = errorSpy;
    console.warn = warnSpy;

    // Mock fetch for /api/health to prevent unhandled rejection during tests
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: "ok",
          authenticated: true,
          computer_vision_ready: true,
          model_available: true,
          missing_dependencies: [],
          gemini_available: false,
        }),
      })
    );
  });

  afterEach(() => {
    console.error = originalError;
    console.warn = originalWarn;
    vi.restoreAllMocks();
  });

  it("1. Root route and App shell render with deterministic initial dark theme", () => {
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    );

    const appShell = container.querySelector(".app-shell");
    expect(appShell).toBeInTheDocument();
    expect(appShell).toHaveAttribute("data-theme", "dark");
  });

  it("2. Initial hydration produces consistent markup without mismatch", () => {
    // Initial render pass must be deterministic and dark by default
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    );

    const logo = container.querySelector("header .brand img");
    expect(logo).toHaveAttribute("src", "/urban-flow-dark.png");

    const toggleBtn = container.querySelector(".theme-toggle");
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn).toHaveTextContent("Light");
  });

  it("3. Light theme initializes safely when stored in localStorage", async () => {
    localStorage.setItem("urban-flow-theme", "light");

    let container: HTMLElement;
    await act(async () => {
      const rendered = render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
      container = rendered.container;
    });

    const appShell = container!.querySelector(".app-shell");
    expect(appShell).toHaveAttribute("data-theme", "light");
    expect(document.documentElement.dataset.theme).toBe("light");

    const logo = container!.querySelector("header .brand img");
    expect(logo).toHaveAttribute("src", "/urban-flow-light.png");
  });

  it("4. Dark theme initializes and applies correctly", async () => {
    localStorage.setItem("urban-flow-theme", "dark");

    let container: HTMLElement;
    await act(async () => {
      const rendered = render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
      container = rendered.container;
    });

    const appShell = container!.querySelector(".app-shell");
    expect(appShell).toHaveAttribute("data-theme", "dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    const logo = container!.querySelector("header .brand img");
    expect(logo).toHaveAttribute("src", "/urban-flow-dark.png");
  });

  it("5. Missing localStorage defaults safely to dark theme", async () => {
    localStorage.removeItem("urban-flow-theme");

    let container: HTMLElement;
    await act(async () => {
      const rendered = render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
      container = rendered.container;
    });

    const appShell = container!.querySelector(".app-shell");
    expect(appShell).toHaveAttribute("data-theme", "dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("6. Invalid localStorage values gracefully fall back to dark theme", async () => {
    // Test corrupted strings, objects, numbers
    for (const invalidValue of ["blue", "invalid-theme", "{}", "123", "system"]) {
      localStorage.setItem("urban-flow-theme", invalidValue);

      let container: HTMLElement;
      await act(async () => {
        const rendered = render(
          <QueryClientProvider client={queryClient}>
            <App />
          </QueryClientProvider>
        );
        container = rendered.container;
      });

      const appShell = container!.querySelector(".app-shell");
      expect(appShell).toHaveAttribute("data-theme", "dark");
      expect(document.documentElement.dataset.theme).toBe("dark");
    }

    // Test localStorage throwing SecurityError (sandboxed iframe / Electron)
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    });

    let container: HTMLElement;
    await act(async () => {
      const rendered = render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
      container = rendered.container;
    });

    const appShell = container!.querySelector(".app-shell");
    expect(appShell).toHaveAttribute("data-theme", "dark");
  });

  it("7. Theme switching toggles between dark and light smoothly", async () => {
    let container: HTMLElement;
    await act(async () => {
      const rendered = render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
      container = rendered.container;
    });

    const toggleBtn = container!.querySelector(".theme-toggle") as HTMLButtonElement;
    expect(toggleBtn).toBeInTheDocument();

    // Click 1: Dark -> Light
    await act(async () => {
      fireEvent.click(toggleBtn);
    });

    expect(container!.querySelector(".app-shell")).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("urban-flow-theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");

    // Click 2: Light -> Dark
    await act(async () => {
      fireEvent.click(toggleBtn);
    });

    expect(container!.querySelector(".app-shell")).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("urban-flow-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("8. Responsive hook useIsMobile is deterministic on initial render", () => {
    const { getByTestId } = render(<ResponsiveTestComponent />);
    // Initial mount must return false (desktop layout) to avoid hydration layout mismatch
    expect(getByTestId("mobile-indicator")).toHaveTextContent("desktop");
  });

  it("9. Electron startup environment executes lifecycle hooks without error", async () => {
    // Simulate Electron environment properties
    vi.stubGlobal("isElectron", true);

    let container: HTMLElement;
    await act(async () => {
      const rendered = render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
      container = rendered.container;
    });

    expect(container!.querySelector(".topbar")).toBeInTheDocument();
    expect(container!.querySelector(".hero")).toBeInTheDocument();
  });

  it("10. Absence of hydration warnings during render and mount", async () => {
    await act(async () => {
      render(
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      );
    });

    // Check that neither error nor warn recorded hydration mismatch strings
    const allLogged = [
      ...errorSpy.mock.calls.map((c) => c.join(" ")),
      ...warnSpy.mock.calls.map((c) => c.join(" ")),
    ];

    const hydrationErrors = allLogged.filter(
      (msg) =>
        msg.includes("Hydration failed") ||
        msg.includes("did not match") ||
        msg.includes("418") ||
        msg.includes("suppressHydrationWarning")
    );

    expect(hydrationErrors).toEqual([]);
  });
});
