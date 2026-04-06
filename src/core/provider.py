from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import AsyncGenerator, Any, Dict, List

from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load .env at import time
load_dotenv()


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str


def _load_config() -> LLMConfig:
    return LLMConfig(
        base_url=os.getenv("LLM_BASE_URL", ""),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "glm-5.1"),
    )


def create_client(config: LLMConfig | None = None) -> AsyncOpenAI:
    """Create an AsyncOpenAI client from config (defaults to .env)."""
    if config is None:
        config = _load_config()
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
    )


async def stream_chat(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, str]],
    **kwargs,
) -> AsyncGenerator[str, None]:
    """Stream a chat completion, yielding content tokens."""
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        **kwargs,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


@dataclass
class StreamEvent:
    """A single event from a streaming chat completion with tool support."""
    type: str  # "content" or "tool_call"
    content: str = ""
    tool_call_id: str = ""
    tool_call_name: str = ""
    tool_call_arguments: str = ""


async def stream_chat_with_tools(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    **kwargs,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream a chat completion with tool support.

    Yields StreamEvent objects. Accumulates tool_call fragments across
    streaming chunks and emits complete tool call events after the stream ends.
    """
    create_kwargs: dict[str, Any] = {**kwargs}
    if tools:
        create_kwargs["tools"] = tools

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        **create_kwargs,
    )

    # Accumulate tool call fragments: id -> {id, name, arguments}
    tool_call_acc: Dict[int, Dict[str, str]] = {}

    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue

        # Content tokens
        if delta.content:
            yield StreamEvent(type="content", content=delta.content)

        # Tool call fragments
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_call_acc:
                    tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                if tc_delta.id:
                    tool_call_acc[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_call_acc[idx]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_call_acc[idx]["arguments"] += tc_delta.function.arguments

    # Emit complete tool calls
    for idx in sorted(tool_call_acc):
        tc = tool_call_acc[idx]
        yield StreamEvent(
            type="tool_call",
            tool_call_id=tc["id"],
            tool_call_name=tc["name"],
            tool_call_arguments=tc["arguments"],
        )


async def complete_chat(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, str]],
    **kwargs,
) -> str:
    """Non-streaming chat completion, returns full content."""
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False,
        **kwargs,
    )
    return response.choices[0].message.content or ""


async def list_models(client: AsyncOpenAI | None = None) -> list[str]:
    """List available model IDs from the provider."""
    c = client or default_client
    models = await c.models.list()
    return sorted(m.id for m in models.data)


# Module-level singleton for convenience
_config = _load_config()
default_client = create_client(_config)
default_model = _config.model
