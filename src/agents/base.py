from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, TYPE_CHECKING

from src.core.bus import EventBus
from src.core.models import AgentState

if TYPE_CHECKING:
    from openai import AsyncOpenAI
    from src.core.resource_manager import ResourceManager
    from src.execution.agent_tools import AgentToolExecutor


class BaseAgent(ABC):
    def __init__(self, name: str, bus: EventBus, provider: str | None = None) -> None:
        self.name = name
        self.bus = bus
        self._provider = provider
        self._agent_tool_executor: AgentToolExecutor | None = None
        self._resource_manager: ResourceManager | None = None
        self._tier: str | None = None

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

    def set_resource_manager(self, rm: ResourceManager, tier: str) -> None:
        """Wire in a ResourceManager for quota-aware fallback."""
        self._resource_manager = rm
        self._tier = tier

    def _ensure_client(self, provider: str) -> None:
        """Swap the LLM client to a different provider if needed."""
        if provider != self._provider:
            from src.core.provider import get_provider_client, get_provider_model
            self._client = get_provider_client(provider)
            self._model = get_provider_model(provider)
            self._provider = provider

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
        """Stream from the configured LLM provider. Yields content tokens.

        If a ResourceManager is set, checks quotas and falls back through
        the provider chain on failure.
        """
        from src.core.provider import stream_chat

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        use_model = model or self._model

        # If resource manager is available, try quota-aware routing
        if self._resource_manager and self._tier:
            next_avail = self._resource_manager.get_next_available(self._tier)
            if next_avail and not self._resource_manager.check_quota(self._provider or ""):
                provider, use_model = next_avail
                self._ensure_client(provider)

        try:
            async for token in stream_chat(
                client=self._client,
                model=use_model,
                messages=messages,
            ):
                yield token
            if self._resource_manager:
                self._resource_manager.record_usage(self._provider or "unknown")
        except Exception:
            # Try fallback chain if resource manager is available
            if self._resource_manager and self._tier:
                chain = self._resource_manager.get_fallback_chain(self._tier)
                for fallback_provider, fallback_model in chain:
                    if fallback_provider == self._provider:
                        continue  # skip the one that just failed
                    try:
                        self._ensure_client(fallback_provider)
                        async for token in stream_chat(
                            client=self._client,
                            model=fallback_model,
                            messages=messages,
                        ):
                            yield token
                        self._resource_manager.record_usage(fallback_provider)
                        return
                    except Exception:
                        continue
            raise  # re-raise if no fallback worked

    async def stream_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator:
        """Stream from the configured LLM provider with tool support."""
        from src.core.provider import stream_chat_with_tools

        use_model = model or self._model

        # If resource manager is available, try quota-aware routing
        if self._resource_manager and self._tier:
            next_avail = self._resource_manager.get_next_available(self._tier)
            if next_avail and not self._resource_manager.check_quota(self._provider or ""):
                provider, use_model = next_avail
                self._ensure_client(provider)

        try:
            async for event in stream_chat_with_tools(
                client=self._client,
                model=use_model,
                messages=messages,
                tools=tools,
            ):
                yield event
            if self._resource_manager:
                self._resource_manager.record_usage(self._provider or "unknown")
        except Exception:
            # Try fallback chain
            if self._resource_manager and self._tier:
                chain = self._resource_manager.get_fallback_chain(self._tier)
                for fallback_provider, fallback_model in chain:
                    if fallback_provider == self._provider:
                        continue
                    try:
                        self._ensure_client(fallback_provider)
                        async for event in stream_chat_with_tools(
                            client=self._client,
                            model=fallback_model,
                            messages=messages,
                            tools=tools,
                        ):
                            yield event
                        self._resource_manager.record_usage(fallback_provider)
                        return
                    except Exception:
                        continue
            raise
