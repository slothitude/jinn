from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import AsyncGenerator, Any, Dict, List

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load .env at import time
load_dotenv()


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str


PROVIDERS = {
    "zhipu": {
        "base_url": "",
        "default_model": "glm-5.1",
        "fallback_models": [
            "glm-5.1", "glm-5", "glm-5-turbo",
            "glm-4.7", "glm-4.6", "glm-4.5", "glm-4.5-air",
        ],
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "nvidia/llama-3.1-nemotron-70b-instruct",
        "fallback_models": [
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "meta/llama-3.1-405b-instruct",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
        ],
    },
}


def _load_config() -> LLMConfig:
    provider_name = os.getenv("LLM_PROVIDER", "zhipu").lower()
    profile = PROVIDERS.get(provider_name)
    if profile is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. "
            f"Available: {', '.join(PROVIDERS.keys())}"
        )
    prefixed_key = os.getenv(f"{provider_name.upper()}_API_KEY", "")
    return LLMConfig(
        base_url=os.getenv("LLM_BASE_URL", "") or profile["base_url"],
        api_key=os.getenv("LLM_API_KEY", "") or prefixed_key,
        model=os.getenv("LLM_MODEL", "") or profile["default_model"],
    )


def create_client(config: LLMConfig | None = None) -> AsyncOpenAI:
    """Create an AsyncOpenAI client from config (defaults to .env)."""
    if config is None:
        config = _load_config()
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
    )


# --- httpx-based fallback (works reliably on Windows + asyncio) ---


async def _httpx_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 120.0,
    **kwargs,
) -> str:
    """Non-streaming chat completion via raw httpx request."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        **kwargs,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""


async def _httpx_stream(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 60.0,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """Streaming chat completion via raw httpx SSE request."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        **kwargs,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        yield delta["content"]
                except json.JSONDecodeError:
                    continue


# --- Model fallback chain ---

# Backward-compatible alias
FALLBACK_MODELS = PROVIDERS["zhipu"]["fallback_models"]


def _get_fallback_chain(preferred: str) -> list[str]:
    """Build fallback chain starting with preferred model."""
    provider_name = os.getenv("LLM_PROVIDER", "zhipu").lower()
    profile = PROVIDERS.get(provider_name, PROVIDERS["zhipu"])
    chain = [preferred]
    for m in profile["fallback_models"]:
        if m not in chain:
            chain.append(m)
    return chain


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
    """Non-streaming chat completion with model fallback chain.

    Tries httpx first (reliable on Windows), then falls back through
    available models if the primary one fails.
    """
    config = _load_config()
    chain = _get_fallback_chain(model)

    for m in chain:
        try:
            return await _httpx_chat(
                config.base_url, config.api_key, m, messages, **kwargs
            )
        except Exception as e:
            print(f"[provider] {m} failed ({type(e).__name__}): {str(e)[:200]}")
            continue

    # Last resort: raw content hint
    return ""


async def list_models(client: AsyncOpenAI | None = None) -> list[str]:
    """List available model IDs from the provider via httpx."""
    config = _load_config()
    url = f"{config.base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.get(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return sorted(m["id"] for m in data.get("data", []))


# --- Multi-provider client registry ---

_provider_clients: dict[str, AsyncOpenAI] = {}
_provider_models: dict[str, str] = {}


def get_provider_client(provider_name: str) -> AsyncOpenAI:
    """Get or create a cached client for a specific provider."""
    if provider_name not in _provider_clients:
        profile = PROVIDERS[provider_name]
        api_key = os.getenv("LLM_API_KEY", "") or os.getenv(f"{provider_name.upper()}_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "") or profile["base_url"]
        _provider_clients[provider_name] = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        _provider_models[provider_name] = os.getenv("LLM_MODEL", "") or profile["default_model"]
    return _provider_clients[provider_name]


def get_provider_model(provider_name: str) -> str:
    """Get the default model for a provider (creates client if needed)."""
    if provider_name not in _provider_models:
        get_provider_client(provider_name)  # populates _provider_models
    return _provider_models[provider_name]


# Module-level singleton for convenience
_config = _load_config()
default_client = create_client(_config)
default_model = _config.model
