from abc import ABC, abstractmethod
from typing import AsyncGenerator

from src.core.bus import EventBus


class BaseAgent(ABC):
    def __init__(self, name: str, bus: EventBus) -> None:
        self.name = name
        self.bus = bus

    @abstractmethod
    async def execute(self, prompt: str) -> AsyncGenerator[str, None]:
        pass

    async def steer(self, message: str) -> None:
        """Interrupt hook — allows KAIROS to redirect mid-execution."""
        pass
