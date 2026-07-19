import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts", "src/corpus/index.ts"],
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  banner: {
    js: "'use client';",
  },
  external: ["react", "react-dom", "@arsenal/ui", "framer-motion"],
});
