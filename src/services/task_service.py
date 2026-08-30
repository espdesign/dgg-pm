from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from src.domain.enums import (
    EventType,
    PriorityLevel,
    TaskHistoryAction,
    TaskStatus,
)
from src.domain.models import Task, TaskHistory
from src.ports.repositories import ITaskRepo
from src.ports.unit_of_work import IUnitOfWork
from src.services.outbox_service import OutboxService
from src.services.project_service import ProjectService


class StaleVersionError(Exception):
    """Raised when an optimistic concurrency update fails due to a version mismatch."""


class TaskService:
    def __init__(
        self,
        task_repo: ITaskRepo,
        project_service: ProjectService,
        outbox_service: OutboxService,
        uow: IUnitOfWork | None = None,
    ):
        self.task_repo = task_repo
        self.project_service = project_service
        self.outbox_service = outbox_service
        self.uow = uow

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[Any, None]:
        """Manages an atomic transaction scope via UnitOfWork if configured, or no-op if omitted."""
        if self.uow is not None:
            async with self.uow as active_uow:
                yield active_uow.session
        else:
            yield None

    async def create_task(
        self,
        guild_id: int,
        title: str,
        creator_discord_id: int,
        project_name: str | None = None,
        project_id: UUID | None = None,
        assignee_discord_id: int | None = None,
        due_at: datetime | None = None,
        priority: PriorityLevel = PriorityLevel.NORMAL,
        body: str | None = None,
        watchers: list[int] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> Task:
        # Resolve project if project_name given
        resolved_project_id = project_id
        if project_name and not resolved_project_id:
            project = await self.project_service.get_by_name(guild_id, project_name)
            if not project:
                raise ValueError(f"Project '{project_name}' was not found in this server.")
            resolved_project_id = project.id

        clean_watchers = list(set(watchers or []))

        async with self._transaction() as session:
            # Allocate short ID within transaction
            if resolved_project_id:
                task_number, short_id = await self.project_service.allocate_next_short_id(
                    resolved_project_id, session=session
                )
            else:
                # Standalone task: use a randomly generated collision-resistant ID.
                # token_hex(5) gives ~1.1e12 combinations, making unique-constraint
                # collisions (guild_id, short_id) practically impossible.
                task_number = 1
                short_id = f"TASK-{secrets.token_hex(5).upper()}"

            task = Task(
                id=uuid4(),
                guild_id=guild_id,
                project_id=resolved_project_id,
                task_number=task_number,
                short_id=short_id,
                version=1,
                title=title.strip(),
                body=body.strip() if body else None,
                status=TaskStatus.NOT_STARTED,
                priority=priority,
                creator_discord_id=creator_discord_id,
                assignee_discord_id=assignee_discord_id,
                due_at=due_at,
                metadata_json=metadata_json or {},
                watchers=clean_watchers,
            )

            # 1. Persist task
            saved_task = await self.task_repo.create(task, session=session)

            # 2. Audit log creation
            history = TaskHistory(
                task_id=saved_task.id,
                actor_discord_id=creator_discord_id,
                action=TaskHistoryAction.CREATED,
                new_status=TaskStatus.NOT_STARTED,
                notes=f"Task '{title}' created with ID {short_id}",
            )
            await self.task_repo.add_history(history, session=session)

            # 3. Schedule tiered reminders if due_at set
            if due_at:
                await self.outbox_service.schedule_task_reminders(saved_task, session=session)

            # 4. Enqueue creation event
            await self.outbox_service.enqueue_event(
                event_type=EventType.TASK_CREATED,
                idempotency_key=f"task_created:{saved_task.id}",
                payload={
                    "task_id": str(saved_task.id),
                    "short_id": saved_task.short_id,
                    "title": saved_task.title,
                    "guild_id": saved_task.guild_id,
                    "project_id": str(saved_task.project_id) if saved_task.project_id else None,
                    "creator_discord_id": saved_task.creator_discord_id,
                    "assignee_discord_id": saved_task.assignee_discord_id,
                    "watchers": saved_task.watchers,
                    "due_at": saved_task.due_at.isoformat() if saved_task.due_at else None,
                },
                session=session,
            )

        return saved_task

    async def update_status(
        self,
        task_id: UUID,
        new_status: TaskStatus,
        expected_version: int,
        actor_discord_id: int,
        notes: str | None = None,
    ) -> Task:
        current_task = await self.task_repo.get_by_id(task_id)
        if not current_task:
            raise ValueError(f"Task with ID {task_id} does not exist.")

        old_status = current_task.status
        completed_at = datetime.now(UTC) if new_status == TaskStatus.COMPLETED else None

        async with self._transaction() as session:
            updated_task = await self.task_repo.update_status_cas(
                task_id=task_id,
                expected_version=expected_version,
                new_status=new_status,
                completed_at=completed_at,
                session=session,
            )
            if not updated_task:
                raise StaleVersionError(
                    f"Task {current_task.short_id} was already modified by another user. Please refresh."
                )

            # Audit log status transition
            history = TaskHistory(
                task_id=task_id,
                actor_discord_id=actor_discord_id,
                action=TaskHistoryAction.STATUS_CHANGE,
                old_status=old_status,
                new_status=new_status,
                notes=notes,
            )
            await self.task_repo.add_history(history, session=session)

            # If completed, cancel pending reminder events
            if new_status == TaskStatus.COMPLETED:
                await self.outbox_service.cancel_task_reminders(task_id, session=session)

            # Enqueue status changed event
            await self.outbox_service.enqueue_event(
                event_type=EventType.TASK_STATUS_CHANGED,
                idempotency_key=f"task_status:{task_id}:v{updated_task.version}",
                payload={
                    "task_id": str(task_id),
                    "short_id": updated_task.short_id,
                    "title": updated_task.title,
                    "guild_id": updated_task.guild_id,
                    "project_id": str(updated_task.project_id) if updated_task.project_id else None,
                    "old_status": old_status.value,
                    "new_status": new_status.value,
                    "actor_discord_id": actor_discord_id,
                    "assignee_discord_id": updated_task.assignee_discord_id,
                    "watchers": updated_task.watchers,
                    "notes": notes,
                    "discord_thread_id": updated_task.discord_thread_id,
                    "discord_message_id": updated_task.discord_message_id,
                },
                session=session,
            )

        return updated_task

    async def add_note(
        self,
        task_id: UUID,
        actor_discord_id: int,
        note_text: str,
    ) -> TaskHistory:
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task with ID {task_id} does not exist.")

        async with self._transaction() as session:
            history = TaskHistory(
                task_id=task_id,
                actor_discord_id=actor_discord_id,
                action=TaskHistoryAction.NOTE_ADDED,
                notes=note_text.strip(),
            )
            saved_history = await self.task_repo.add_history(history, session=session)

            # Enqueue note event for thread/DM notification
            await self.outbox_service.enqueue_event(
                event_type=EventType.TASK_NOTE_ADDED,
                idempotency_key=f"task_note:{saved_history.id}",
                payload={
                    "task_id": str(task_id),
                    "short_id": task.short_id,
                    "title": task.title,
                    "guild_id": task.guild_id,
                    "actor_discord_id": actor_discord_id,
                    "assignee_discord_id": task.assignee_discord_id,
                    "watchers": task.watchers,
                    "note": note_text.strip(),
                    "discord_thread_id": task.discord_thread_id,
                },
                session=session,
            )

        return saved_history

    async def update_assignee(
        self,
        task_id: UUID,
        new_assignee_id: int | None,
        actor_discord_id: int,
    ) -> Task:
        current_task = await self.task_repo.get_by_id(task_id)
        if not current_task:
            raise ValueError(f"Task with ID {task_id} does not exist.")

        old_assignee = current_task.assignee_discord_id
        if old_assignee == new_assignee_id:
            return current_task

        clear = new_assignee_id is None
        async with self._transaction() as session:
            updated_task = await self.task_repo.update_task(
                task_id=task_id,
                assignee_discord_id=new_assignee_id,
                clear_assignee=clear,
                session=session,
            )
            if not updated_task:
                raise ValueError(f"Failed to update assignee for task {task_id}.")

            note = f"Assigned to <@{new_assignee_id}>" if new_assignee_id else "Removed assignee (unassigned)"
            history = TaskHistory(
                task_id=task_id,
                actor_discord_id=actor_discord_id,
                action=TaskHistoryAction.ASSIGNED,
                notes=note,
            )
            await self.task_repo.add_history(history, session=session)

            # Enqueue event
            await self.outbox_service.enqueue_event(
                event_type=EventType.TASK_UPDATED,
                idempotency_key=f"task_assignee:{task_id}:v{updated_task.version}",
                payload={
                    "task_id": str(task_id),
                    "short_id": updated_task.short_id,
                    "title": updated_task.title,
                    "guild_id": updated_task.guild_id,
                    "actor_discord_id": actor_discord_id,
                    "old_assignee_id": old_assignee,
                    "new_assignee_id": new_assignee_id,
                    "discord_thread_id": updated_task.discord_thread_id,
                },
                session=session,
            )

        return updated_task

    async def update_priority(
        self,
        task_id: UUID,
        new_priority: PriorityLevel,
        actor_discord_id: int,
    ) -> Task:
        current_task = await self.task_repo.get_by_id(task_id)
        if not current_task:
            raise ValueError(f"Task with ID {task_id} does not exist.")

        old_priority = current_task.priority
        if old_priority == new_priority:
            return current_task

        async with self._transaction() as session:
            updated_task = await self.task_repo.update_task(
                task_id=task_id,
                priority=new_priority,
                session=session,
            )
            if not updated_task:
                raise ValueError(f"Failed to update priority for task {task_id}.")

            history = TaskHistory(
                task_id=task_id,
                actor_discord_id=actor_discord_id,
                action=TaskHistoryAction.PRIORITY_CHANGED,
                notes=f"Priority changed from {old_priority.value} to {new_priority.value}",
            )
            await self.task_repo.add_history(history, session=session)

            await self.outbox_service.enqueue_event(
                event_type=EventType.TASK_UPDATED,
                idempotency_key=f"task_priority:{task_id}:v{updated_task.version}",
                payload={
                    "task_id": str(task_id),
                    "short_id": updated_task.short_id,
                    "title": updated_task.title,
                    "guild_id": updated_task.guild_id,
                    "actor_discord_id": actor_discord_id,
                    "old_priority": old_priority.value,
                    "new_priority": new_priority.value,
                    "discord_thread_id": updated_task.discord_thread_id,
                },
                session=session,
            )

        return updated_task

    async def update_details(
        self,
        task_id: UUID,
        actor_discord_id: int,
        title: str | None = None,
        body: str | None = None,
        due_at: datetime | None = None,
        clear_due_at: bool = False,
        watchers: list[int] | None = None,
    ) -> Task:
        current_task = await self.task_repo.get_by_id(task_id)
        if not current_task:
            raise ValueError(f"Task with ID {task_id} does not exist.")

        async with self._transaction() as session:
            updated_task = await self.task_repo.update_task(
                task_id=task_id,
                title=title,
                body=body,
                due_at=due_at,
                clear_due_at=clear_due_at,
                watchers=watchers,
                session=session,
            )
            if not updated_task:
                raise ValueError(f"Failed to update task {task_id}.")

            # If due_at changed, reschedule outbox reminders
            if clear_due_at:
                await self.outbox_service.cancel_task_reminders(task_id, session=session)
            elif due_at is not None and due_at != current_task.due_at:
                await self.outbox_service.cancel_task_reminders(task_id, session=session)
                if not updated_task.is_completed and not updated_task.is_archived:
                    await self.outbox_service.schedule_task_reminders(updated_task, session=session)

            history = TaskHistory(
                task_id=task_id,
                actor_discord_id=actor_discord_id,
                action=TaskHistoryAction.UPDATED,
                notes="Task details updated",
            )
            await self.task_repo.add_history(history, session=session)

        return updated_task

    async def update_discord_message_ids(
        self,
        task_id: UUID,
        discord_message_id: int,
        discord_thread_id: int | None = None,
    ) -> None:
        await self.task_repo.update_discord_message(task_id, discord_message_id, discord_thread_id)

    async def get_by_id(self, task_id: UUID) -> Task | None:
        return await self.task_repo.get_by_id(task_id)

    async def get_by_short_id(self, guild_id: int, short_id: str) -> Task | None:
        return await self.task_repo.get_by_short_id(guild_id, short_id)

    async def get_by_thread_id(self, guild_id: int, thread_id: int) -> Task | None:
        return await self.task_repo.get_by_thread_id(guild_id, thread_id)

    async def list_tasks(
        self,
        guild_id: int,
        project_id: UUID | None = None,
        assignee_discord_id: int | None = None,
        status: TaskStatus | None = None,
        include_archived: bool = False,
        exclude_completed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        return await self.task_repo.list_tasks(
            guild_id=guild_id,
            project_id=project_id,
            assignee_discord_id=assignee_discord_id,
            status=status,
            include_archived=include_archived,
            exclude_completed=exclude_completed,
            limit=limit,
            offset=offset,
        )

    async def search_for_autocomplete(
        self,
        guild_id: int,
        query: str,
        project_id: UUID | None = None,
        limit: int = 25,
    ) -> list[Task]:
        return await self.task_repo.search_for_autocomplete(
            guild_id=guild_id,
            query=query,
            project_id=project_id,
            limit=limit,
        )

    async def archive_task(self, task_id: UUID, actor_discord_id: int) -> Task | None:
        async with self._transaction() as session:
            task = await self.task_repo.set_archived(task_id, is_archived=True, session=session)
            if task:
                await self.outbox_service.cancel_task_reminders(task_id, session=session)
                history = TaskHistory(
                    task_id=task_id,
                    actor_discord_id=actor_discord_id,
                    action=TaskHistoryAction.ARCHIVED,
                    notes="Task archived",
                )
                await self.task_repo.add_history(history, session=session)
        return task

    async def unarchive_task(self, task_id: UUID, actor_discord_id: int) -> Task | None:
        async with self._transaction() as session:
            task = await self.task_repo.set_archived(task_id, is_archived=False, session=session)
            if task:
                if task.due_at and not task.is_completed:
                    await self.outbox_service.schedule_task_reminders(task, session=session)
                history = TaskHistory(
                    task_id=task_id,
                    actor_discord_id=actor_discord_id,
                    action=TaskHistoryAction.UNARCHIVED,
                    notes="Task unarchived and restored",
                )
                await self.task_repo.add_history(history, session=session)
        return task

    async def get_history(self, task_id: UUID) -> list[TaskHistory]:
        return await self.task_repo.get_history(task_id)
