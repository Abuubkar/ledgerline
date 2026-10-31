// next/jest wires the Next.js compiler, CSS and next/font mocks, and path aliases into Jest.
const nextJest = require("next/jest");

const createJestConfig = nextJest({ dir: "./" });

// MSW 3 and several of its dependencies ship only as ES modules, which Jest's CommonJS runtime can't load, so the
// Next.js compiler transforms them like our own code. The lookahead skips pnpm's .pnpm store folder and matches the
// package folder inside it.
const ESM_ONLY = ["msw", "@msw", "@mswjs", "@open-draft", "until-async", "headers-polyfill", "rettime", "cookie", "set-cookie-parser",
  "tough-cookie", "@inquirer", "ansi-regex", "ansi-styles", "strip-ansi", "string-width", "wrap-ansi", "fast-string-truncated-width",
  "fast-string-width", "fast-wrap-ansi", "get-east-asian-width", "cliui", "y18n", "yargs", "yargs-parser"];

const config = {
  // MSW needs the Fetch API globals (Request, Response, TextEncoder) that plain jsdom lacks: MSW's documented fix.
  testEnvironment: "jest-fixed-jsdom",
  testEnvironmentOptions: { customExportConditions: [""] },
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1" },
};

module.exports = async () => {
  const resolved = await createJestConfig(config)();
  resolved.transformIgnorePatterns = [`/node_modules/(?!(\\.pnpm|${ESM_ONLY.join("|")})(/|@))`, ...resolved.transformIgnorePatterns.filter(p => !p.includes("node_modules"))];
  return resolved;
};
