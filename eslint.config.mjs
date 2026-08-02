import eslint from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const toWarning = (value) => {
  if (Array.isArray(value)) {
    const [severity, ...options] = value;
    return severity === 0 || severity === "off" ? value : ["warn", ...options];
  }
  return value === 0 || value === "off" ? value : "warn";
};

const warningOnly = (config) => ({
  ...config,
  rules: Object.fromEntries(
    Object.entries(config.rules ?? {}).map(([name, value]) => [name, toWarning(value)]),
  ),
});

const sourceFiles = ["**/*.{js,mjs,cjs,ts,tsx}"];
const typedFiles = ["**/*.{ts,tsx}"];
const browserFiles = ["apps/{web,extension}/**/*.{js,mjs,ts,tsx}"];

export default [
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/dist/**",
      "**/coverage/**",
      "**/e2e-reports/**",
      "**/.firefox-run/**",
      "**/*.d.ts",
      ".agents/**",
      ".repair-worktrees/**",
      "logs/**",
      "apps/api/**",
    ],
  },
  warningOnly({
    ...eslint.configs.recommended,
    files: sourceFiles,
  }),
  ...tseslint.configs.recommended.map((config) =>
    warningOnly({
      ...config,
      files: typedFiles,
    }),
  ),
  warningOnly({
    files: sourceFiles,
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.browser,
        ...globals.webextensions,
      },
    },
  }),
  warningOnly({
    files: browserFiles,
    plugins: {
      "jsx-a11y": jsxA11y,
      "react-hooks": reactHooks,
    },
    rules: {
      ...jsxA11y.configs.recommended.rules,
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  }),
];
