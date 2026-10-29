import { defineConfig } from "vitest/config";

// Default run: unit tests only. The live suite (test/live) hits production and is opt-in
// through `npm run test:live` (vitest.live.config.ts).
export default defineConfig({
  test: {
    exclude: ["**/node_modules/**", "**/dist/**", "test/live/**"],
  },
});
