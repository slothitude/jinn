from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncGenerator

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


# Module-level singleton for convenience
_config = _load_config()
default_client = create_client(_config)
default_model = _config.model
