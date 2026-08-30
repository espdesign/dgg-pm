from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.adapters.db.tables import (
    OutboxEventTable,
    ProjectTable,
    ProjectTeamTable,
    TaskHistoryTable,
    TaskTable,
    TaskWatcherTable,
    TeamMemberTable,
    TeamTable,
)
from src.domain.enums import (
    EventType,
    OutboxStatus,
    PriorityLevel,
    TaskHistoryAction,
    TaskStatus,
)
from src.domain.models import (
    OutboxEvent,
    Project,
    ProjectTeam,
    Task,
    TaskHistory,
    Team,
    TeamMember,
)
from src.ports.repositories import (
    IOutboxRepo,
    IProjectRepo,
    ITaskRepo,
    ITeamRepo,
)


def _to_domain_task(row: TaskTable) -> Task:
    watchers = [w.user_discord_id for w in row.watchers] if row.watchers else []
    return Task(
        id=row.id,
        guild_id=row.guild_id,
        project_id=row.project_id,
        task_number=row.task_number,
        short_id=row.short_id,
        version=row.version,
        title=row.title,
        body=row.body,
        status=TaskStatus(row.status),
        priority=PriorityLevel(row.priority),
        creator_discord_id=row.creator_discord_id,
        assignee_discord_id=row.assignee_discord_id,
        due_at=row.due_at,
        completed_at=row.completed_at,
        discord_message_id=row.discord_message_id,
        discord_thread_id=row.discord_thread_id,
        metadata_json=row.metadata_json or {},
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        watchers=watchers,
    )


def _to_domain_project(row: ProjectTable) -> Project:
    return Project(
        id=row.id,
        guild_id=row.guild_id,
        name=row.name,
        prefix=row.prefix,
        next_task_number=row.next_task_number,
        description=row.description,
        discord_channel_id=row.discord_channel_id,
        category=row.category,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_domain_team(row: TeamTable) -> Team:
    return Team(
        id=row.id,
        guild_id=row.guild_id,
        name=row.name,
        discord_role_id=row.discord_role_id,
        created_at=row.created_at,
    )


def _to_domain_outbox(row: OutboxEventTable) -> OutboxEvent:
    return OutboxEvent(
        id=row.id,
        idempotency_key=row.idempotency_key,
        event_type=EventType(row.event_type),
        payload=row.payload or {},
        status=OutboxStatus(row.status),
        retry_count=row.retry_count,
        scheduled_for=row.scheduled_for,
        created_at=row.created_at,
        processed_at=row.processed_at,
    )


class PostgresTaskRepo(ITaskRepo):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, task: Task) -> Task:
        row = TaskTable(
            id=task.id,
            guild_id=task.guild_id,
            project_id=task.project_id,
            task_number=task.task_number,
            short_id=task.short_id,
            version=task.version,
            title=task.title,
            body=task.body,
            status=task.status.value,
            priority=task.priority.value,
            creator_discord_id=task.creator_discord_id,
            assignee_discord_id=task.assignee_discord_id,
            due_at=task.due_at,
            completed_at=task.completed_at,
            discord_message_id=task.discord_message_id,
            discord_thread_id=task.discord_thread_id,
            metadata_json=task.metadata_json,
            archived_at=task.archived_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        self.session.add(row)

        for watcher_id in task.watchers:
            watcher_row = TaskWatcherTable(
                task_id=task.id,
                user_discord_id=watcher_id,
                created_at=task.created_at,
            )
            self.session.add(watcher_row)

        await self.session.flush()
        return task

    async def get_by_id(self, task_id: UUID) -> Task | None:
        stmt = select(TaskTable).options(selectinload(TaskTable.watchers)).where(TaskTable.id == task_id)
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_task(row) if row else None

    async def get_by_short_id(self, guild_id: int, short_id: str) -> Task | None:
        stmt = (
            select(TaskTable)
            .options(selectinload(TaskTable.watchers))
            .where(
                TaskTable.guild_id == guild_id,
                func.upper(TaskTable.short_id) == short_id.upper().strip(),
            )
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_task(row) if row else None

    async def update_status_cas(
        self,
        task_id: UUID,
        expected_version: int,
        new_status: TaskStatus,
        completed_at: datetime | None,
    ) -> Task | None:
        now = datetime.now(UTC)
        stmt = (
            update(TaskTable)
            .where(TaskTable.id == task_id, TaskTable.version == expected_version)
            .values(
                status=new_status.value,
                completed_at=completed_at,
                version=expected_version + 1,
                updated_at=now,
            )
            .returning(TaskTable)
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        if not row:
            return None

        # Reload with watchers
        return await self.get_by_id(task_id)

    async def update_discord_message(
        self,
        task_id: UUID,
        discord_message_id: int,
        discord_thread_id: int | None,
    ) -> None:
        stmt = (
            update(TaskTable)
            .where(TaskTable.id == task_id)
            .values(
                discord_message_id=discord_message_id,
                discord_thread_id=discord_thread_id,
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

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
        filters = [TaskTable.guild_id == guild_id]
        if not include_archived:
            filters.append(TaskTable.archived_at.is_(None))
        if project_id:
            filters.append(TaskTable.project_id == project_id)
        if assignee_discord_id:
            filters.append(TaskTable.assignee_discord_id == assignee_discord_id)
        if status:
            filters.append(TaskTable.status == status.value)

        # Count total
        count_stmt = select(func.count()).select_from(TaskTable).where(*filters)
        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar() or 0

        # Fetch records
        stmt = (
            select(TaskTable)
            .options(selectinload(TaskTable.watchers))
            .where(*filters)
            .order_by(TaskTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        return [_to_domain_task(r) for r in rows], total_count

    async def search_for_autocomplete(
        self,
        guild_id: int,
        query: str,
        project_id: UUID | None = None,
        limit: int = 25,
    ) -> list[Task]:
        filters = [
            TaskTable.guild_id == guild_id,
            TaskTable.archived_at.is_(None),
            TaskTable.status != TaskStatus.COMPLETED.value,
        ]
        if project_id:
            filters.append(TaskTable.project_id == project_id)

        clean_query = query.strip().upper()
        if clean_query:
            filters.append(
                or_(
                    func.upper(TaskTable.short_id).like(f"%{clean_query}%"),
                    func.upper(TaskTable.title).like(f"%{clean_query}%"),
                )
            )

        stmt = (
            select(TaskTable)
            .options(selectinload(TaskTable.watchers))
            .where(*filters)
            .order_by(TaskTable.created_at.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        return [_to_domain_task(r) for r in rows]

    async def set_archived(self, task_id: UUID, is_archived: bool) -> Task | None:
        now = datetime.now(UTC) if is_archived else None
        stmt = (
            update(TaskTable)
            .where(TaskTable.id == task_id)
            .values(archived_at=now, updated_at=datetime.now(UTC))
            .returning(TaskTable)
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        if not row:
            return None
        return await self.get_by_id(task_id)

    async def add_history(self, history: TaskHistory) -> TaskHistory:
        row = TaskHistoryTable(
            id=history.id,
            task_id=history.task_id,
            actor_discord_id=history.actor_discord_id,
            action=history.action.value,
            old_status=history.old_status.value if history.old_status else None,
            new_status=history.new_status.value if history.new_status else None,
            notes=history.notes,
            created_at=history.created_at,
        )
        self.session.add(row)
        await self.session.flush()
        return history

    async def get_history(self, task_id: UUID) -> list[TaskHistory]:
        stmt = (
            select(TaskHistoryTable)
            .where(TaskHistoryTable.task_id == task_id)
            .order_by(TaskHistoryTable.created_at.asc())
        )
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        return [
            TaskHistory(
                id=r.id,
                task_id=r.task_id,
                actor_discord_id=r.actor_discord_id,
                action=TaskHistoryAction(r.action),
                old_status=TaskStatus(r.old_status) if r.old_status else None,
                new_status=TaskStatus(r.new_status) if r.new_status else None,
                notes=r.notes,
                created_at=r.created_at,
            )
            for r in rows
        ]


class PostgresProjectRepo(IProjectRepo):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, project: Project) -> Project:
        row = ProjectTable(
            id=project.id,
            guild_id=project.guild_id,
            name=project.name,
            prefix=project.prefix.upper(),
            next_task_number=project.next_task_number,
            description=project.description,
            discord_channel_id=project.discord_channel_id,
            category=project.category,
            archived_at=project.archived_at,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
        self.session.add(row)
        await self.session.flush()
        return project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        stmt = select(ProjectTable).where(ProjectTable.id == project_id)
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_project(row) if row else None

    async def get_by_name(self, guild_id: int, name: str) -> Project | None:
        stmt = select(ProjectTable).where(
            ProjectTable.guild_id == guild_id,
            func.upper(ProjectTable.name) == name.strip().upper(),
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_project(row) if row else None

    async def get_by_prefix(self, guild_id: int, prefix: str) -> Project | None:
        stmt = select(ProjectTable).where(
            ProjectTable.guild_id == guild_id,
            func.upper(ProjectTable.prefix) == prefix.strip().upper(),
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_project(row) if row else None

    async def get_by_channel_id(self, guild_id: int, channel_id: int) -> Project | None:
        stmt = select(ProjectTable).where(
            ProjectTable.guild_id == guild_id,
            ProjectTable.discord_channel_id == channel_id,
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_project(row) if row else None

    async def increment_task_number_atomic(self, project_id: UUID) -> tuple[int, str]:
        now = datetime.now(UTC)
        stmt = (
            update(ProjectTable)
            .where(ProjectTable.id == project_id)
            .values(
                next_task_number=ProjectTable.next_task_number + 1,
                updated_at=now,
            )
            .returning(ProjectTable.next_task_number - 1, ProjectTable.prefix)
        )
        res = await self.session.execute(stmt)
        row = res.first()
        if not row:
            raise ValueError(f"Project with ID {project_id} not found for atomic counter update")
        return row[0], row[1]

    async def list_projects(self, guild_id: int, include_archived: bool = False) -> list[Project]:
        filters = [ProjectTable.guild_id == guild_id]
        if not include_archived:
            filters.append(ProjectTable.archived_at.is_(None))
        stmt = select(ProjectTable).where(*filters).order_by(ProjectTable.name.asc())
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        return [_to_domain_project(r) for r in rows]

    async def set_archived(self, project_id: UUID, is_archived: bool) -> Project | None:
        now = datetime.now(UTC) if is_archived else None
        stmt = (
            update(ProjectTable)
            .where(ProjectTable.id == project_id)
            .values(archived_at=now, updated_at=datetime.now(UTC))
            .returning(ProjectTable)
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        if not row:
            return None

        # Cascade archival to associated tasks
        task_stmt = (
            update(TaskTable)
            .where(TaskTable.project_id == project_id)
            .values(archived_at=now, updated_at=datetime.now(UTC))
        )
        await self.session.execute(task_stmt)
        return _to_domain_project(row)

    async def assign_team(self, project_team: ProjectTeam) -> None:
        row = ProjectTeamTable(
            project_id=project_team.project_id,
            team_id=project_team.team_id,
            start_date=project_team.start_date,
            timeline=project_team.timeline,
        )
        await self.session.merge(row)
        await self.session.flush()


class PostgresTeamRepo(ITeamRepo):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, team: Team) -> Team:
        row = TeamTable(
            id=team.id,
            guild_id=team.guild_id,
            name=team.name,
            discord_role_id=team.discord_role_id,
            created_at=team.created_at,
        )
        self.session.add(row)
        await self.session.flush()
        return team

    async def get_by_name(self, guild_id: int, name: str) -> Team | None:
        stmt = select(TeamTable).where(
            TeamTable.guild_id == guild_id,
            func.upper(TeamTable.name) == name.strip().upper(),
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_team(row) if row else None

    async def get_by_role_id(self, guild_id: int, role_id: int) -> Team | None:
        stmt = select(TeamTable).where(
            TeamTable.guild_id == guild_id,
            TeamTable.discord_role_id == role_id,
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return _to_domain_team(row) if row else None

    async def assign_member(self, member: TeamMember) -> None:
        row = TeamMemberTable(
            team_id=member.team_id,
            user_discord_id=member.user_discord_id,
            role_type=member.role_type.value,
            created_at=member.created_at,
        )
        await self.session.merge(row)
        await self.session.flush()

    async def list_teams(self, guild_id: int) -> list[Team]:
        stmt = select(TeamTable).where(TeamTable.guild_id == guild_id).order_by(TeamTable.name.asc())
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        return [_to_domain_team(r) for r in rows]


class PostgresOutboxRepo(IOutboxRepo):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(self, event: OutboxEvent) -> OutboxEvent:
        row = OutboxEventTable(
            id=event.id,
            idempotency_key=event.idempotency_key,
            event_type=event.event_type.value,
            payload=event.payload,
            status=event.status.value,
            retry_count=event.retry_count,
            scheduled_for=event.scheduled_for,
            created_at=event.created_at,
            processed_at=event.processed_at,
        )
        # Idempotent insert: ignore if key exists
        await self.session.merge(row)
        await self.session.flush()
        return event

    async def fetch_pending_batch(self, limit: int = 10) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        stmt = (
            select(OutboxEventTable)
            .where(
                OutboxEventTable.status == OutboxStatus.PENDING.value,
                OutboxEventTable.scheduled_for <= now,
            )
            .order_by(OutboxEventTable.scheduled_for.asc())
            .limit(limit)
        )

        # Check if underlying DB engine is PostgreSQL to apply FOR UPDATE SKIP LOCKED
        bind = self.session.bind
        dialect_name = bind.dialect.name if bind else ""
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        res = await self.session.execute(stmt)
        rows = res.scalars().all()

        # Mark as processing
        for r in rows:
            r.status = OutboxStatus.PROCESSING.value
        await self.session.flush()

        return [_to_domain_outbox(r) for r in rows]

    async def mark_processed(self, event_id: UUID) -> None:
        now = datetime.now(UTC)
        stmt = (
            update(OutboxEventTable)
            .where(OutboxEventTable.id == event_id)
            .values(
                status=OutboxStatus.PROCESSED.value,
                processed_at=now,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def reschedule_or_fail(
        self,
        event_id: UUID,
        retry_count: int,
        next_scheduled_for: datetime,
        failed: bool = False,
    ) -> None:
        status_val = OutboxStatus.FAILED.value if failed else OutboxStatus.PENDING.value
        stmt = (
            update(OutboxEventTable)
            .where(OutboxEventTable.id == event_id)
            .values(
                status=status_val,
                retry_count=retry_count,
                scheduled_for=next_scheduled_for,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def cancel_task_reminders(self, task_id: UUID) -> int:
        prefix = f"task_due:{task_id}:"
        stmt = (
            update(OutboxEventTable)
            .where(
                OutboxEventTable.idempotency_key.like(f"{prefix}%"),
                OutboxEventTable.status == OutboxStatus.PENDING.value,
            )
            .values(status=OutboxStatus.CANCELLED.value)
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        return res.rowcount or 0
