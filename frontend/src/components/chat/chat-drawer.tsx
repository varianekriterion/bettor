"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Loader2, MessageCircle, Send, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useAuth } from "@/contexts/auth-context";
import { streamChat, type ChatMessage } from "@/lib/chat";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "My tipster says back Girona BTTS. What does the data say?",
  "How accurate has forebet been in La Liga lately?",
  "Have I made this kind of bet before?",
];

interface DisplayMessage extends ChatMessage {
  id: string;
  pending?: boolean;
}

export function ChatDrawer() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Scope bet-memory tool calls to the signed-in user's journal rows.
  const userId = user?.id ?? null;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    setError(null);
    setInput("");

    const history = messages.map(({ role, content }) => ({ role, content }));
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: trimmed },
      { id: assistantId, role: "assistant", content: "", pending: true },
    ]);
    setStreaming(true);
    setActiveTool(null);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    await streamChat(
      { message: trimmed, userId, history },
      (event) => {
        if (event.type === "tool_start") {
          setActiveTool(event.tool);
        } else if (event.type === "tool_end") {
          setActiveTool(null);
        } else if (event.type === "token") {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + event.text } : m))
          );
        } else if (event.type === "error") {
          setError(event.message);
        }
      },
      controller.signal
    );

    setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, pending: false } : m)));
    setActiveTool(null);
    setStreaming(false);
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          className="fixed bottom-6 right-6 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500 text-zinc-950 shadow-lg shadow-emerald-500/20 transition-transform hover:scale-105 hover:bg-emerald-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
          aria-label="Open BetConsensus analyst chat"
        >
          <MessageCircle className="h-5 w-5" />
        </button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-emerald-500/15 ring-1 ring-emerald-500/40">
              <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
            </div>
            <SheetTitle>BetConsensus Analyst</SheetTitle>
          </div>
          <SheetDescription>
            Ask about xG, tipster accuracy, or your own bet history — grounded in tools, not vibes.
          </SheetDescription>
        </SheetHeader>

        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {messages.length === 0 && (
            <div className="space-y-2">
              <p className="text-xs text-zinc-500">Try asking:</p>
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="block w-full rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-left text-xs text-zinc-300 transition-colors hover:border-emerald-500/40 hover:bg-zinc-900"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {messages.map((m) => (
            <ChatBubble key={m.id} message={m} />
          ))}

          {activeTool && (
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <Loader2 className="h-3 w-3 animate-spin" />
              Using {activeTool}…
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </div>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex shrink-0 items-end gap-2 border-t border-zinc-800 p-3"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder="Ask about a team, tipster, or your own bets…"
            rows={2}
            disabled={streaming}
            className="min-h-[40px] flex-1 resize-none rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500/50 focus:outline-none disabled:opacity-60"
          />
          <Button type="submit" size="icon" disabled={streaming || !input.trim()}>
            {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function ChatBubble({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[88%] rounded-lg px-3 py-2 text-sm leading-relaxed",
          isUser
            ? "bg-emerald-500/15 text-emerald-100 ring-1 ring-emerald-500/25"
            : "border border-zinc-800 bg-zinc-900/70 text-zinc-100"
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : message.content ? (
          <MarkdownMessage content={message.content} />
        ) : (
          <span className="inline-flex items-center gap-1.5 text-zinc-500">
            <Bot className="h-3.5 w-3.5" />
            <Loader2 className="h-3 w-3 animate-spin" />
          </span>
        )}
      </div>
    </div>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="space-y-2">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-zinc-50">{children}</strong>,
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-4">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-4">{children}</ol>,
          code: ({ children }) => (
            <code className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[11px] text-emerald-300">
              {children}
            </code>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-md border border-zinc-800">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-zinc-800/60">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b border-zinc-800 px-2 py-1.5 text-left font-medium text-zinc-300">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-zinc-900 px-2 py-1.5 text-zinc-300">{children}</td>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-400 underline underline-offset-2 hover:text-emerald-300"
            >
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
