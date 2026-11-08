import { defineConfig } from "vitest/config";

// Unit tests for platform-independent code (storage logic, validation). React Native
// screens are verified by typecheck and on device.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
