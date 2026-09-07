"""
Conversational AI chat endpoint (Phase 3).

POST /api/v1/chat — LangChain tool-calling agent over query_xg_stats,
query_tipster_accuracy, and search_past_bet_mistakes, streamed back as
Server-Sent Events so the frontend chat drawer can render tokens live.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.chat_tools import build_chat_tools

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """You are the BetConsensus analyst — a sharp, honest quant sports-betting \
assistant for European football. You have tools for live xG/xGA data, tipster \
(prediction source) accuracy, and the user's own past-bet history.

Rules:
- Use tools rather than guessing whenever the user asks about specific teams, \
  tipster reliability, or their own betting history.
- When a tool returns a markdown table, keep it in your answer as a markdown table \
  (don't collapse it into prose) so the UI can render it.
- Be explicit when data is simulated/demo (tools will tell you) rather than live.
- Never tell the user to bet more than a sane fractional-Kelly stake implies; if \
  asked to "just say yes", give the actual EV/edge reasoning instead.
- Keep answers tight — this is a chat drawer, not a report.
"""


class ChatMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    user_id: str | None = Field(default=None, description="Supabase auth.uid(), if signed in")
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


def _require_llm():
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured — chat is unavailable.",
        )
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="langchain-openai is not installed on the server.",
        ) from exc
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key,
        temperature=0.2,
        streaming=True,
    )


def _build_agent_executor(user_id: str | None):
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    llm = _require_llm()
    tools = build_chat_tools(user_id=user_id)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=False, max_iterations=6)


def _to_lc_history(history: list[ChatMessage]):
    from langchain_core.messages import AIMessage, HumanMessage

    out = []
    for m in history:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        else:
            out.append(AIMessage(content=m.content))
    return out


async def _stream_agent_response(executor, body: ChatRequest):
    """Yield Server-Sent Events: token deltas while the agent streams its final answer."""
    payload = {"input": body.message, "chat_history": _to_lc_history(body.history)}

    try:
        async for event in executor.astream_events(payload, version="v2"):
            kind = event.get("event")

            if kind == "on_tool_start":
                tool_name = event.get("name", "tool")
                yield f"event: tool_start\ndata: {json.dumps({'tool': tool_name})}\n\n"

            elif kind == "on_tool_end":
                tool_name = event.get("name", "tool")
                yield f"event: tool_end\ndata: {json.dumps({'tool': tool_name})}\n\n"

            elif kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                text = getattr(chunk, "content", "") if chunk is not None else ""
                if text:
                    yield f"event: token\ndata: {json.dumps({'text': text})}\n\n"

        yield "event: done\ndata: {}\n\n"
    except Exception as exc:  # noqa: BLE001 — surface the failure to the stream, not a 500 mid-stream
        logger.exception("Chat agent stream failed: %s", exc)
        yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    """Streamed (SSE) chat response from the tool-calling agent."""
    # Built eagerly (not inside the generator) so a missing API key / missing
    # langchain-openai install returns a clean 4xx/503 instead of a broken
    # stream — Starlette sends the 200 status line before pulling the first
    # chunk from a StreamingResponse's body iterator.
    executor = _build_agent_executor(body.user_id)
    return StreamingResponse(
        _stream_agent_response(executor, body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
