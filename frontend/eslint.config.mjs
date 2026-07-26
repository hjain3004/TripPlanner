import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  // Generated API client — do not edit by hand or lint
  { ignores: ["src/lib/api/client/**", "src/lib/api/core/**", "src/lib/api/*.gen.ts", "src/lib/api/index.ts"] },
]);

export default eslintConfig;
