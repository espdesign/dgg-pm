from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from src.domain.enums import EventType, OutboxStatus
from src.domain.models import OutboxEvent, Task
from src.ports.repositories import IOutboxRepo


class OutboxService:
    def __init__(self, outbox_repo: IOutboxRepo):
        self.outbox_repo = outbox_repo

    async def enqueue_event(
        self,
        event_type: EventType,
        idempotency_key: str,
        payload: dict[str, Any],
        scheduled_for: datetime | None = None,
    ) -> OutboxEvent:
        event = OutboxEvent(
            idempotency_key=idempotency_key,
            event_type=event_type,
            payload=payload,
            status=OutboxStatus.PENDING,
            scheduled_for=scheduled_for or datetime.now(UTC),
        )
        return await self.outbox_repo.enqueue(event)

    async def schedule_task_reminders(self, task: Task) -> list[OutboxEvent]:
        """Schedules tiered reminders (T-24h, T-1h, Due) for a task if due_at is set."""
        if not task.due_at or task.is_completed or task.is_archived:
            return []

        now = datetime.now(UTC)
        due_utc = task.due_at.astimezone(UTC)
        scheduled_events: list[OutboxEvent] = []

        # T-24h reminder
        t_24h = due_utc - timedelta(hours=24)
        if t_24h > now:
            evt = await self.enqueue_event(
                event_type=EventType.TASK_DUE_REMINDER,
                idempotency_key=f"task_due:{task.id}:24h",
                payload={
                    "task_id": str(task.id),
                    "short_id": task.short_id,
                    "title": task.title,
                    "guild_id": task.guild_id,
                    "assignee_discord_id": task.assignee_discord_id,
                    "reminder_type": "24h",
                    "due_at": due_utc.isoformat(),
                },
                scheduled_for=t_24h,
            )
            scheduled_events.append(evt)

        # T-1h reminder
        t_1h = due_utc - timedelta(hours=1)
        if t_1h > now:
            evt = await self.enqueue_event(
                event_type=EventType.TASK_DUE_REMINDER,
                idempotency_key=f"task_due:{task.id}:1h",
                payload={
                    "task_id": str(task.id),
                    "short_id": task.short_id,
                    "title": task.title,
                    "guild_id": task.guild_id,
                    "assignee_discord_id": task.assignee_discord_id,
                    "reminder_type": "1h",
                    "due_at": due_utc.isoformat(),
                },
                scheduled_for=t_1h,
            )
            scheduled_events.append(evt)

        # Due time alert
        if due_utc > now:
            evt = await self.enqueue_event(
                event_type=EventType.TASK_DUE_REMINDER,
                idempotency_key=f"task_due:{task.id}:due",
                payload={
                    "task_id": str(task.id),
                    "short_id": task.short_id,
                    "title": task.title,
                    "guild_id": task.guild_id,
                    "assignee_discord_id": task.assignee_discord_id,
                    "reminder_type": "due",
                    "due_at": due_utc.isoformat(),
                },
                scheduled_for=due_utc,
            )
            scheduled_events.append(evt)

        return scheduled_events

    async def cancel_task_reminders(self, task_id: UUID) -> int:
        return await self.outbox_repo.cancel_task_reminders(task_id)
