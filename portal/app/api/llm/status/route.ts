import { configuredBaseUrl, jsonError } from "../../_lib/proxy";

export async function GET(): Promise<Response> {
  const baseUrl = configuredBaseUrl("VLLM_API_URL");
  if (!baseUrl) {
    return jsonError(
      503,
      "llm_backend_not_configured",
      "The local GPU endpoint is not configured.",
    );
  }

  try {
    const [health, models] = await Promise.all([
      fetch(`${baseUrl}/health`, {
        cache: "no-store",
        signal: AbortSignal.timeout(5_000),
      }),
      fetch(`${baseUrl}/v1/models`, {
        cache: "no-store",
        signal: AbortSignal.timeout(5_000),
      }),
    ]);
    if (!health.ok || !models.ok) {
      throw new Error("vLLM readiness check failed");
    }
    const modelBody = (await models.json()) as { data?: Array<{ id?: string }> };
    return Response.json(
      {
        status: "ready",
        model: modelBody.data?.[0]?.id ?? "unknown",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return jsonError(502, "llm_backend_unavailable", "The local GPU endpoint is unavailable.");
  }
}
