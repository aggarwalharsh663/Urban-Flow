// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
  vite: {
    server: {
      host: "127.0.0.1",
      port: 5174,
      strictPort: true,
      // Proxy API and upload calls in local dev mode so the token is attached server-side (V-01 Option A)
      proxy: {
        "/api": {
          target: process.env.VITE_BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              const devToken = process.env.URBAN_FLOW_DEV_TOKEN || process.env.VITE_API_TOKEN;
              if (devToken && !proxyReq.getHeader("X-API-Token")) {
                proxyReq.setHeader("X-API-Token", devToken);
              }
            });
          },
        },
        "/uploads": {
          target: process.env.VITE_BACKEND_URL || "http://127.0.0.1:8000",
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              const devToken = process.env.URBAN_FLOW_DEV_TOKEN || process.env.VITE_API_TOKEN;
              if (devToken && !proxyReq.getHeader("X-API-Token")) {
                proxyReq.setHeader("X-API-Token", devToken);
              }
            });
          },
        },
      },
    },
  },
});
