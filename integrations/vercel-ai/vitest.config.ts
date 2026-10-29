import { defineConfig } from "vitest/config";

// Default run: unit tests against a local fake HTTP server. The live smoke (test/live) is
// opt-in through `npm run test:live` (vitest.live.config.ts).
export default defineConfig({
  test: {
    exclude: ["**/node_modules/**", "**/dist/**", "test/live/**"],
    coverage: {
      provider: "v8",
      include: ["src/**"],
      reporter: ["text-summary", "text"],
      thresholds: { lines: 85, statements: 85, functions: 85, branches: 80 },
    },
  },
});
