import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

// Em desenvolvimento a API roda em :8000; o proxy mantém frontend e API na mesma origem,
// exatamente como em produção (CloudFront roteia /api/* para o ALB).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_PROXY_TARGET ?? "http://localhost:8000", changeOrigin: false, ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // nomes com hash permitem cache imutável no CloudFront; sw.js e index.html ficam sem cache.
    assetsDir: "assets",
  },
});
