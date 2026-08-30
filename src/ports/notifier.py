from abc import ABC, abstractmethod

from src.domain.models import OutboxEvent


class INotificationDispatcher(ABC):
    @abstractmethod
    async def dispatch_event(self, event: OutboxEvent) -> None:
        """Dispatches an outbox event to Discord (Channel message, Thread message, or DM)."""
