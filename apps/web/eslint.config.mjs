// ESLint with Next's own rules (core web vitals + TypeScript), as the Next 16 docs set it up. src/gql is generated.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  // Reviewer copy uses plain apostrophes ("can't"); React renders them as text, so escaping them is noise.
  { rules: { "react/no-unescaped-entities": "off" } },
  // Jest's config is CommonJS.
  { files: ["jest.config.js"], rules: { "@typescript-eslint/no-require-imports": "off" } },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "src/gql/**"]),
]);
