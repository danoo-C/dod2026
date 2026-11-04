// Vitest: the frontend's tests, in jsdom (docs/plans/frontend.md, decision 5).
import { defineConfig, mergeConfig } from "vitest/config";

import vite from "./vite.config.ts";

export default mergeConfig(
  vite,
  defineConfig({
    test: {
      environment: "jsdom",
      include: ["tests/**/*.test.{ts,tsx}"],
      restoreMocks: true,
    },
  }),
);
