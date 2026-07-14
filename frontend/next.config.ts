import type { NextConfig } from "next";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function readAppVersion(): string {
  const candidates = [
    resolve(process.cwd(), "..", "VERSION"),
    resolve(process.cwd(), "VERSION"),
  ];
  for (const p of candidates) {
    try {
      return readFileSync(p, "utf8").trim();
    } catch {
      /* try next candidate */
    }
  }
  return "0.0.0";
}

const appVersion = readAppVersion();

const nextConfig: NextConfig = {
  output: "standalone",
  env: {
    NEXT_PUBLIC_APP_VERSION: appVersion,
  },
};

export default nextConfig;