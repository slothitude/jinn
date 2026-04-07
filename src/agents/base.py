from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, TYPE_CHECKING

from src.core.bus import EventBus
from src.core.models import AgentState

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from src.execution.agent_tools import AgentToolExecutor


class BaseAgent(ABC):
    def __init__(self, name: str, bus: EventBus, provider: str | None = None) -> None:
        self.name = name
        self.bus = bus
        self._provider = provider
        self._agent_tool_executor: AgentToolExecutor | None = None

        if provider:
            from src.core.provider import get_provider_client, get_provider_model
            self._client: AsyncOpenAI = get_provider_client(provider)
            self._model: str = get_provider_model(provider)
        else:
            from src.core.provider import default_client, default_model
            self._client = default_client
            self._model = default_model

    def set_agent_tool_executor(self, executor: AgentToolExecutor) -> None:
        """Wire in an AgentToolExecutor for delegation tool calls."""
        self._agent_tool_executor = executor

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
        from src.core.provider import stream_chat

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async for token in stream_chat(
            client=self._client,
            model=model or self._model,
            messages=messages,
        ):
            yield token

    async def stream_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator:
        """Stream from the configured LLM provider with tool support."""
        from src.core.provider import stream_chat_with_tools

        async for event in stream_chat_with_tools(
            client=self._client,
            model=model or self._model,
            messages=messages,
            tools=tools,
        ):
            yield event
