import { defineConfig, devices } from "@playwright/test";

// Requer a pilha rodando com dados de demonstração (ver README: "Testes de ponta a ponta").
// E2E_BASE_URL aponta para a API servindo o build do frontend (ANDRIPA_FRONTEND_DIST_DIR).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "test-results/e2e-report.json" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
