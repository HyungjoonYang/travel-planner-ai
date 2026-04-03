import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  timeout: 30_000,
  retries: 1,
  reporter: [["list"], ["json", { outputFile: "results.json" }]],
  use: {
    baseURL: process.env.QA_BASE_URL || "http://localhost:8000",
    extraHTTPHeaders: { Accept: "application/json" },
  },
});
