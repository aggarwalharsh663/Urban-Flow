/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
  type ErrorComponentProps,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, RotateCcw, Home, ShieldAlert, ArrowLeft, Terminal } from "lucide-react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { sanitizeErrorMessage } from "../lib/error-parser";

function NotFoundComponent() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--paper, #121820)",
        color: "var(--ink, #f3f4f6)",
        padding: "24px",
        fontFamily: 'var(--font-display, "Bricolage Grotesque", sans-serif)',
      }}
    >
      <div
        style={{
          maxWidth: "520px",
          width: "100%",
          padding: "36px",
          border: "3px solid var(--rule, #f3f4f6)",
          background: "var(--card, #1a2230)",
          boxShadow: "8px 8px 0 var(--shadow, #000)",
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "4px 10px",
            background: "var(--stop, #ef4444)",
            color: "#fff",
            font: '700 12px var(--font-mono, "JetBrains Mono", monospace)',
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: "16px",
          }}
        >
          <ShieldAlert size={14} />
          Error 404 · Route Unknown
        </div>

        <h1
          style={{
            font: '800 36px/1.1 var(--font-display, "Bricolage Grotesque", sans-serif)',
            letterSpacing: "-0.03em",
            textTransform: "uppercase",
            margin: "8px 0 14px",
          }}
        >
          Signal Route Not Found
        </h1>

        <p
          style={{
            fontSize: "15px",
            lineHeight: 1.5,
            color: "var(--ink-soft, #9ca3af)",
            margin: "0 0 24px",
          }}
        >
          The intersection or system page you requested does not exist or has been relocated.
          All active traffic signals and computer vision pipelines remain operational.
        </p>

        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "12px" }}>
          <Link
            to="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              height: "44px",
              padding: "0 20px",
              border: "3px solid var(--rule, #f3f4f6)",
              background: "var(--signal, #00e5ff)",
              color: "var(--signal-ink, #000)",
              font: '700 13px var(--font-mono, "JetBrains Mono", monospace)',
              textTransform: "uppercase",
              textDecoration: "none",
              cursor: "pointer",
              boxShadow: "4px 4px 0 var(--ink, #000)",
            }}
          >
            <Home size={15} />
            Return to Dashboard
          </Link>
        </div>

        <div
          style={{
            marginTop: "28px",
            paddingTop: "14px",
            borderTop: "1px dashed var(--rule, #f3f4f6)",
            fontSize: "11px",
            color: "var(--ink-soft, #9ca3af)",
            fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
          }}
        >
          UrbanFlow Adaptive Traffic Signal System · Copyright © 2026 Harsh Aggarwal
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    console.error("Root Error Boundary triggered:", error);
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  const rawMessage = error instanceof Error ? error.message : String(error || "");
  const cleanMessage = sanitizeErrorMessage(rawMessage);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--paper, #121820)",
        color: "var(--ink, #f3f4f6)",
        padding: "24px",
        fontFamily: 'var(--font-display, "Bricolage Grotesque", sans-serif)',
      }}
    >
      <div
        style={{
          maxWidth: "580px",
          width: "100%",
          padding: "36px",
          border: "3px solid var(--rule, #f3f4f6)",
          background: "var(--card, #1a2230)",
          boxShadow: "8px 8px 0 var(--shadow, #000)",
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            padding: "4px 10px",
            background: "var(--stop, #ef4444)",
            color: "#fff",
            font: '700 12px var(--font-mono, "JetBrains Mono", monospace)',
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: "16px",
          }}
        >
          <AlertTriangle size={14} />
          System Exception · Engine Fail-Safe
        </div>

        <h1
          style={{
            font: '800 32px/1.1 var(--font-display, "Bricolage Grotesque", sans-serif)',
            letterSpacing: "-0.03em",
            textTransform: "uppercase",
            margin: "8px 0 14px",
          }}
        >
          Application Encountered An Issue
        </h1>

        <p
          style={{
            fontSize: "15px",
            lineHeight: 1.5,
            color: "var(--ink-soft, #9ca3af)",
            margin: "0 0 20px",
          }}
        >
          A runtime condition prevented this view from rendering normally.
          You can attempt to reset the local route state, re-run diagnostics, or navigate home.
        </p>

        <div
          style={{
            padding: "12px 14px",
            background: "var(--paper, #121820)",
            border: "2px solid var(--rule, #f3f4f6)",
            font: '600 12px/1.4 var(--font-mono, "JetBrains Mono", monospace)',
            color: "var(--stop, #ef4444)",
            textAlign: "left",
            wordBreak: "break-all",
            marginBottom: "24px",
          }}
        >
          <strong>Diagnostic:</strong> {cleanMessage}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "12px" }}>
          <button
            type="button"
            onClick={() => {
              try {
                router.invalidate();
              } catch (e) {}
              reset();
            }}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              height: "44px",
              padding: "0 18px",
              border: "3px solid var(--rule, #f3f4f6)",
              background: "var(--signal, #00e5ff)",
              color: "var(--signal-ink, #000)",
              font: '700 13px var(--font-mono, "JetBrains Mono", monospace)',
              textTransform: "uppercase",
              cursor: "pointer",
              boxShadow: "4px 4px 0 var(--ink, #000)",
            }}
          >
            <RotateCcw size={15} />
            Try Again
          </button>

          <a
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              height: "44px",
              padding: "0 18px",
              border: "3px solid var(--rule, #f3f4f6)",
              background: "var(--card, #1a2230)",
              color: "var(--ink, #f3f4f6)",
              font: '700 13px var(--font-mono, "JetBrains Mono", monospace)',
              textTransform: "uppercase",
              textDecoration: "none",
              cursor: "pointer",
              boxShadow: "4px 4px 0 var(--ink, #000)",
            }}
          >
            <Home size={15} />
            Go Home
          </a>

          <button
            type="button"
            onClick={() => setShowDetails((prev) => !prev)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              height: "44px",
              padding: "0 14px",
              border: "2px dashed var(--rule, #f3f4f6)",
              background: "transparent",
              color: "var(--ink-soft, #9ca3af)",
              font: '600 12px var(--font-mono, "JetBrains Mono", monospace)',
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            <Terminal size={14} />
            {showDetails ? "Hide Stack" : "Technical Details"}
          </button>
        </div>

        {showDetails && error instanceof Error && error.stack && (
          <pre
            style={{
              marginTop: "20px",
              padding: "12px",
              background: "#0a0e14",
              color: "#38bdf8",
              border: "1px solid var(--rule, #f3f4f6)",
              font: '500 11px/1.4 var(--font-mono, "JetBrains Mono", monospace)',
              textAlign: "left",
              overflowX: "auto",
              maxHeight: "180px",
            }}
          >
            {sanitizeErrorMessage(error.stack)}
          </pre>
        )}

        <div
          style={{
            marginTop: "28px",
            paddingTop: "14px",
            borderTop: "1px dashed var(--rule, #f3f4f6)",
            fontSize: "11px",
            color: "var(--ink-soft, #9ca3af)",
            fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
          }}
        >
          UrbanFlow Adaptive Traffic Signal System · Copyright © 2026 Harsh Aggarwal
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1, maximum-scale=5" },
      { title: "UrbanFlow — Adaptive Traffic Signal System | Local Computer Vision" },
      {
        name: "description",
        content:
          "UrbanFlow is an intelligent adaptive traffic signal control system utilizing local computer vision (YOLOv8) to optimize intersection timing, reduce queues, and improve traffic throughput.",
      },
      {
        name: "keywords",
        content:
          "traffic signals, computer vision, YOLOv8, adaptive signal timing, traffic management, OpenCV, intersection optimization, smart city, Harsh Aggarwal",
      },
      { name: "author", content: "Harsh Aggarwal <aggarwalharsh663@gmail.com>" },
      { name: "theme-color", content: "#07111f" },
      { name: "robots", content: "index, follow" },
      { property: "og:title", content: "UrbanFlow — Adaptive Traffic Signal System" },
      {
        property: "og:description",
        content:
          "Real-time adaptive traffic signal timing powered by local computer vision (YOLOv8) and deterministic phase allocation.",
      },
      { property: "og:type", content: "website" },
      { property: "og:site_name", content: "UrbanFlow" },
      { property: "og:image", content: "/urban-flow-dark.png" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:title", content: "UrbanFlow — Adaptive Traffic Signal System" },
      {
        name: "twitter:description",
        content:
          "Real-time adaptive traffic signal timing powered by local computer vision (YOLOv8).",
      },
      { name: "twitter:image", content: "/urban-flow-dark.png" },
    ],
    links: [
      { rel: "preload", as: "image", href: "/urban-flow-dark.png" },
      {
        rel: "stylesheet",
        href: appCss,
      },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=JetBrains+Mono:wght@500;600;700;800&display=swap",
      },
      { rel: "icon", href: "/favicon.ico", type: "image/x-icon" },
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <body suppressHydrationWarning>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      {/* Required: nested routes render here. Removing <Outlet /> breaks all child routes. */}
      <Outlet />
    </QueryClientProvider>
  );
}
