import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

function proxyUrl(request: NextRequest, pathSegments: string[]): string {
  const path = pathSegments.join("/");
  const search = request.nextUrl.search;
  return `${BACKEND_URL}/chat/${path}${search}`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const backendRes = await fetch(proxyUrl(request, path), {
    headers: { Accept: "application/json" },
  });

  if (!backendRes.ok) {
    return new Response(`Backend error: ${backendRes.status}`, {
      status: backendRes.status,
    });
  }

  return new Response(backendRes.body, {
    status: backendRes.status,
    headers: {
      "Content-Type": backendRes.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const body = await request.text();

  const backendRes = await fetch(proxyUrl(request, path), {
    method: "POST",
    headers: { "Content-Type": request.headers.get("Content-Type") ?? "application/json" },
    body,
  });

  if (!backendRes.ok) {
    return new Response(`Backend error: ${backendRes.status}`, {
      status: backendRes.status,
    });
  }

  if (!backendRes.body) {
    return new Response("Backend response body is null", { status: 502 });
  }

  return new Response(backendRes.body, {
    status: backendRes.status,
    headers: {
      "Content-Type": backendRes.headers.get("Content-Type") ?? "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
