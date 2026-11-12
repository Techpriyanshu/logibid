import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";
import { VitePWA } from "vite-plugin-pwa";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
    // Forward API calls so phones/other devices on the LAN reach the backend through this one port.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  plugins: [
    react(),
    mode === "development" && componentTagger(),
    VitePWA({
      // "prompt": a new release waits for the user to tap Update instead of silently swapping mid-session.
      registerType: "prompt",
      includeAssets: ["icons/apple-touch-icon.png"],
      manifest: {
        id: "/",
        name: "LogiBid",
        short_name: "LogiBid",
        description: "LogiBid - Logistics E-Bidding System",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        theme_color: "#3b82f6",
        background_color: "#f8fafc",
        prefer_related_applications: false,
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // Precache only the static app shell and build assets. No runtimeCaching: API, auth and
        // live bidding responses are never stored, and non-GET requests are never queued or replayed.
        globPatterns: ["**/*.{js,css,html,png,svg,ico,woff2}"],
        globIgnores: ["**/placeholder.svg"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/docs/, /^\/openapi\.json/, /^\/do-login/],
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
      },
    }),
  ].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
