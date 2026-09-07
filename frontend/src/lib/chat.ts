import { API_BASE } from "@/lib/api";

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export type ChatStreamEvent =
  | { type: "token"; text: string }
  | { type: "tool_start"; tool: string }
  | { type: "tool_end"; tool: string }
  | { type: "done" }
  | { type: "error"; message: string };

function parseSSEBlock(block: string): ChatStreamEvent | null {
  let eventName = "message";
  let dataLine = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) dataLine += line.slice("data:".length).trim();
  }
  if (!dataLine) return null;

  let payload: Record<string, unknown> = {};
  try {
    payload = JSON.parse(dataLine);
  } catch {
    return null;
  }

  switch (eventName) {
    case "token":
      return { type: "token", text: typeof payload.text === "string" ? payload.text : "" };
    case "tool_start":
      return { type: "tool_start", tool: typeof payload.tool === "string" ? payload.tool : "tool" };
    case "tool_end":
      return { type: "tool_end", tool: typeof payload.tool === "string" ? payload.tool : "tool" };
    case "done":
      return { type: "done" };
    case "error":
      return {
        type: "error",
        message: typeof payload.message === "string" ? payload.message : "Unknown error",
      };
    default:
      return null;
  }
}

/**
 * Streams /api/v1/chat as Server-Sent Events. Uses fetch + a manual reader
 * rather than EventSource, since EventSource can't send a POST body.
 */
export async function streamChat(
  params: { message: string; userId: string | null; history: ChatMessage[] },
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: params.message,
        user_id: params.userId,
        history: params.history,
      }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    onEvent({ type: "error", message: (err as Error).message || "Network error" });
    return;
  }

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    // A non-2xx response here is FastAPI's own JSON error body (e.g. the
    // 503 raised before streaming starts when OPENAI_API_KEY is unset), not
    // an SSE stream — unwrap `{"detail": "..."}` rather than showing raw JSON.
    let message = text;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") message = parsed.detail;
    } catch {
      // not JSON — use the raw text as-is
    }
    onEvent({ type: "error", message: message || `Request failed: ${res.status}` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sepIndex: number;
      while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        const event = parseSSEBlock(rawEvent);
        if (event) onEvent(event);
      }
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      onEvent({ type: "error", message: (err as Error).message || "Stream interrupted" });
    }
  }
}
