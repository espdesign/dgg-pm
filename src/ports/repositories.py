from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from src.domain.enums import TaskStatus
from src.domain.models import (
    OutboxEvent,
    Project,
    ProjectTeam,
    Task,
    TaskHistory,
    Team,
    TeamMember,
)


class ITaskRepo(ABC):
    @abstractmethod
    async def create(self, task: Task) -> Task:
        """Persists a new task and its initial watchers."""

    @abstractmethod
    async def get_by_id(self, task_id: UUID) -> Task | None:
        """Fetches a task by UUID."""

    @abstractmethod
    async def get_by_short_id(self, guild_id: int, short_id: str) -> Task | None:
        """Fetches a task by its short ID (e.g. INF-1) in a guild."""

    @abstractmethod
    async def update_status_cas(
        self,
        task_id: UUID,
        expected_version: int,
        new_status: TaskStatus,
        completed_at: datetime | None,
    ) -> Task | None:
        """Optimistic concurrency update for task status. Returns updated Task or None on conflict."""

    @abstractmethod
    async def update_discord_message(
        self,
        task_id: UUID,
        discord_message_id: int,
        discord_thread_id: int | None,
    ) -> None:
        """Updates Discord message and thread identifiers on a task."""

    @abstractmethod
    async def list_tasks(
        self,
        guild_id: int,
        project_id: UUID | None = None,
        assignee_discord_id: int | None = None,
        status: TaskStatus | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Task], int]:
        """Lists tasks with filters. Returns (tasks, total_count)."""

    @abstractmethod
    async def search_for_autocomplete(
        self,
        guild_id: int,
        query: str,
        project_id: UUID | None = None,
        limit: int = 25,
    ) -> list[Task]:
        """Searches open tasks for slash command autocomplete."""

    @abstractmethod
    async def set_archived(self, task_id: UUID, is_archived: bool) -> Task | None:
        """Soft-deletes or unarchives a task."""

    @abstractmethod
    async def add_history(self, history: TaskHistory) -> TaskHistory:
        """Appends a task history audit entry."""

    @abstractmethod
    async def get_history(self, task_id: UUID) -> list[TaskHistory]:
        """Retrieves chronological audit history for a task."""


class IProjectRepo(ABC):
    @abstractmethod
    async def create(self, project: Project) -> Project:
        """Persists a new project."""

    @abstractmethod
    async def get_by_id(self, project_id: UUID) -> Project | None:
        """Fetches project by UUID."""

    @abstractmethod
    async def get_by_name(self, guild_id: int, name: str) -> Project | None:
        """Fetches project by name within a guild."""

    @abstractmethod
    async def get_by_prefix(self, guild_id: int, prefix: str) -> Project | None:
        """Fetches project by prefix within a guild."""

    @abstractmethod
    async def get_by_channel_id(self, guild_id: int, channel_id: int) -> Project | None:
        """Fetches project bound to a Discord channel/thread."""

    @abstractmethod
    async def increment_task_number_atomic(self, project_id: UUID) -> tuple[int, str]:
        """Atomically increments next_task_number and returns (allocated_number, prefix)."""

    @abstractmethod
    async def list_projects(self, guild_id: int, include_archived: bool = False) -> list[Project]:
        """Lists all projects for a guild."""

    @abstractmethod
    async def set_archived(self, project_id: UUID, is_archived: bool) -> Project | None:
        """Soft-deletes or unarchives a project."""

    @abstractmethod
    async def assign_team(self, project_team: ProjectTeam) -> None:
        """Maps a team to a project."""


class ITeamRepo(ABC):
    @abstractmethod
    async def create(self, team: Team) -> Team:
        """Persists a new team."""

    @abstractmethod
    async def get_by_name(self, guild_id: int, name: str) -> Team | None:
        """Fetches team by name within a guild."""

    @abstractmethod
    async def get_by_role_id(self, guild_id: int, role_id: int) -> Team | None:
        """Fetches team by Discord role ID."""

    @abstractmethod
    async def assign_member(self, member: TeamMember) -> None:
        """Records or updates team member domain role (LEAD/MEMBER)."""

    @abstractmethod
    async def list_teams(self, guild_id: int) -> list[Team]:
        """Lists all teams for a guild."""


class IOutboxRepo(ABC):
    @abstractmethod
    async def enqueue(self, event: OutboxEvent) -> OutboxEvent:
        """Persists an outbox event."""

    @abstractmethod
    async def fetch_pending_batch(self, limit: int = 10) -> list[OutboxEvent]:
        """Fetches and locks pending scheduled events using FOR UPDATE SKIP LOCKED."""

    @abstractmethod
    async def mark_processed(self, event_id: UUID) -> None:
        """Marks an outbox event as PROCESSED."""

    @abstractmethod
    async def reschedule_or_fail(
        self,
        event_id: UUID,
        retry_count: int,
        next_scheduled_for: datetime,
        failed: bool = False,
    ) -> None:
        """Updates an event with new scheduled time or FAILED status on rate limits/errors."""

    @abstractmethod
    async def cancel_task_reminders(self, task_id: UUID) -> int:
        """Cancels all pending reminder events for a task."""
