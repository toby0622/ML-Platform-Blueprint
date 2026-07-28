import { configuredBaseUrl, jsonError } from "../../_lib/proxy";

interface ChatBody {
  message?: unknown;
}

export async function POST(request: Request): Promise<Response> {
  const baseUrl = configuredBaseUrl("VLLM_API_URL");
  if (!baseUrl) {
    return jsonError(
      503,
      "llm_backend_not_configured",
      "The local GPU endpoint is not configured.",
    );
  }

  let body: ChatBody;
  try {
    body = (await request.json()) as ChatBody;
  } catch {
    return jsonError(400, "invalid_json", "The chat request must be valid JSON.");
  }
  if (typeof body.message !== "string" || !body.message.trim() || body.message.length > 2_000) {
    return jsonError(422, "invalid_message", "Message must contain between 1 and 2,000 characters.");
  }

  const model = process.env.VLLM_SERVED_MODEL_NAME?.trim() || "qwen2.5-1.5b-instruct";
  try {
    const response = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [
          {
            role: "system",
            content:
              "You are the bounded local assistant for ML Platform Blueprint. Be concise and factual.",
          },
          { role: "user", content: body.message.trim() },
        ],
        temperature: 0.2,
        max_tokens: 256,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(120_000),
    });
    const result = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
      usage?: {
        prompt_tokens?: number;
        completion_tokens?: number;
      };
      error?: { message?: string };
    };
    if (!response.ok) {
      return jsonError(
        response.status,
        "llm_request_failed",
        result.error?.message ?? "The local model rejected the request.",
      );
    }
    const message = result.choices?.[0]?.message?.content;
    if (!message) {
      return jsonError(502, "invalid_llm_response", "The local model returned no message.");
    }
    return Response.json(
      {
        message,
        model,
        usage: result.usage ?? {},
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return jsonError(502, "llm_backend_unavailable", "The local GPU endpoint is unavailable.");
  }
}
