import { defineConfig } from "vitest/config";

// Unit tests for the pure design-system functions only (src/design/**). Slide
// components and Remotion compositions are validated by `tsc --noEmit` +
// `remotion studio`, not vitest — they need the browser/render runtime.
export default defineConfig({
  test: {
    include: ["src/design/**/*.test.ts"],
    environment: "node",
  },
});
