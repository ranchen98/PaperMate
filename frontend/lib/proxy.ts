import type { NextRequest } from "next/server";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export function backendUrl(
  prefix: string,
  pathSegments: string[],
  search: string,
): string {
  const path = pathSegments.join("/");
  return `${BACKEND_URL}/${prefix}/${path}${search}`;
}

export function cookieHeader(request: NextRequest): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { cookie } : {};
}

export function applySetCookie(src: Response, dst: Headers): void {
  const headers = src.headers as unknown as { getSetCookie?: () => string[] };
  const cookies = headers.getSetCookie?.call(src.headers) ?? [];
  for (const c of cookies) {
    dst.append("set-cookie", c);
  }
}
