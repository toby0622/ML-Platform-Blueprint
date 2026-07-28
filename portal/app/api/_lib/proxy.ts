const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
};

export function jsonError(status: number, code: string, message: string): Response {
  return Response.json(
    {
      error: {
        code,
        message,
      },
    },
    { status, headers: JSON_HEADERS },
  );
}

export function configuredBaseUrl(name: "PLATFORM_API_URL" | "VLLM_API_URL"): string | null {
  const value = process.env[name]?.trim();
  return value ? value.replace(/\/+$/, "") : null;
}

function safePath(segments: string[]): string | null {
  if (
    !segments.length ||
    segments.some(
      (segment) =>
        !segment ||
        segment === "." ||
        segment === ".." ||
        segment.includes("/") ||
        segment.includes("\\"),
    )
  ) {
    return null;
  }
  return segments.map(encodeURIComponent).join("/");
}

export async function proxyPlatform(request: Request, segments: string[]): Promise<Response> {
  const baseUrl = configuredBaseUrl("PLATFORM_API_URL");
  if (!baseUrl) {
    return jsonError(
      503,
      "live_backend_not_configured",
      "The Portal live backend is not configured. Use Demo mode or set PLATFORM_API_URL.",
    );
  }
  const path = safePath(segments);
  if (!path) {
    return jsonError(400, "invalid_proxy_path", "The requested platform path is invalid.");
  }

  const incomingUrl = new URL(request.url);
  const target = new URL(`/${path}${incomingUrl.search}`, `${baseUrl}/`);
  const headers = new Headers();
  for (const name of ["content-type", "x-tenant-id", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      cache: "no-store",
      signal: AbortSignal.timeout(120_000),
    });
    const responseHeaders = new Headers();
    responseHeaders.set(
      "Content-Type",
      response.headers.get("content-type") ?? "application/json; charset=utf-8",
    );
    responseHeaders.set("Cache-Control", "no-store");
    const requestId = response.headers.get("x-request-id");
    if (requestId) {
      responseHeaders.set("X-Request-Id", requestId);
    }
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch {
    return jsonError(
      502,
      "platform_backend_unavailable",
      "The Portal could not reach the platform API.",
    );
  }
}
