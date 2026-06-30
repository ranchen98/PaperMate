import type { NextRequest } from "next/server";
import { backendUrl, cookieHeader, applySetCookie } from "@/lib/proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function proxyUrl(request: NextRequest, pathSegments: string[]): string {
  const path = pathSegments.join("/");
  const search = request.nextUrl.search;
  return backendUrl("paper", [path], search);
}

function buildHeaders(backendRes: Response): Headers {
  const headers = new Headers();
  headers.set(
    "Content-Type",
    backendRes.headers.get("Content-Type") ?? "application/json",
  );
  headers.set("Cache-Control", "no-store");
  applySetCookie(backendRes, headers);
  return headers;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const backendRes = await fetch(proxyUrl(request, path), {
    headers: { Accept: "application/json", ...cookieHeader(request) },
  });

  const headers = buildHeaders(backendRes);
  if (!backendRes.ok) {
    return new Response(`Backend error: ${backendRes.status}`, {
      status: backendRes.status,
      headers,
    });
  }

  return new Response(backendRes.body, {
    status: backendRes.status,
    headers,
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const body = request.body;

  const backendRes = await fetch(proxyUrl(request, path), {
    method: "POST",
    headers: {
      "Content-Type": request.headers.get("Content-Type") ?? "application/json",
      ...cookieHeader(request),
    },
    body,
    duplex: "half",
  } as RequestInit);

  const headers = buildHeaders(backendRes);
  if (!backendRes.ok) {
    return new Response(`Backend error: ${backendRes.status}`, {
      status: backendRes.status,
      headers,
    });
  }

  return new Response(backendRes.body, {
    status: backendRes.status,
    headers,
  });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const backendRes = await fetch(proxyUrl(request, path), {
    method: "DELETE",
    headers: { Accept: "application/json", ...cookieHeader(request) },
  });

  const headers = buildHeaders(backendRes);
  if (!backendRes.ok) {
    return new Response(`Backend error: ${backendRes.status}`, {
      status: backendRes.status,
      headers,
    });
  }

  return new Response(backendRes.body, {
    status: backendRes.status,
    headers,
  });
}
