from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator

from src.core.bus import EventBus
from src.core.provider import default_client, default_model, stream_chat, StreamEvent, stream_chat_with_tools


from src.core.models import AgentState


class BaseAgent(ABC):
    def __init__(self, name: str, bus: EventBus) -> None:
        self.name = name
        self.bus = bus

    @abstractmethod
    async def execute(
        self, prompt: str, state: AgentState | None = None
    ) -> AsyncGenerator[str, None]:
        pass

    async def steer(self, message: str) -> None:
        """Interrupt hook — allows KAIROS to redirect mid-execution."""
        pass

    async def stream_llm(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream from the configured LLM provider. Yields content tokens."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async for token in stream_chat(
            client=default_client,
            model=model or default_model,
            messages=messages,
        ):
            yield token

    async def stream_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream from the configured LLM provider with tool support.

        Yields StreamEvent objects (content or tool_call).
        """
        async for event in stream_chat_with_tools(
            client=default_client,
            model=model or default_model,
            messages=messages,
            tools=tools,
        ):
            yield event
