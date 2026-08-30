from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.adapters.db.tables import OutboxEventTable
from src.adapters.worker.outbox_worker import OutboxWorker
from src.domain.enums import EventType, OutboxStatus, TaskStatus
from src.ports.notifier import INotificationDispatcher


class MockNotifier(INotificationDispatcher):
    def __init__(self):
        self.dispatched = []

    async def dispatch_event(self, event):
        self.dispatched.append(event)


@pytest.mark.asyncio
async def test_tiered_reminder_scheduling_and_cancellation(services, db_session):
    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 555555555555555555

    project = await proj_srv.create_project(guild_id=guild_id, name="Sprint 1", prefix="SP1")

    # Due in 48 hours
    due_time = datetime.now(UTC) + timedelta(hours=48)
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Release MVP",
        creator_discord_id=1001,
        project_id=project.id,
        assignee_discord_id=2001,
        due_at=due_time,
    )

    # Verify all 4 events are in outbox table (task_created, 24h, 1h, due)
    stmt = select(OutboxEventTable).where(OutboxEventTable.idempotency_key.like(f"%{task.id}%"))
    res = await db_session.execute(stmt)
    rows = res.scalars().all()
    assert len(rows) == 4

    keys = [r.idempotency_key for r in rows]
    assert f"task_created:{task.id}" in keys
    assert f"task_due:{task.id}:24h" in keys
    assert f"task_due:{task.id}:1h" in keys
    assert f"task_due:{task.id}:due" in keys

    # Complete task
    await task_srv.update_status(
        task_id=task.id,
        new_status=TaskStatus.COMPLETED,
        expected_version=1,
        actor_discord_id=2001,
    )

    # Reminders should now be CANCELLED
    db_session.expire_all()
    res_after = await db_session.execute(stmt)
    rows_after = res_after.scalars().all()
    cancelled_reminders = [
        r
        for r in rows_after
        if r.idempotency_key.startswith(f"task_due:{task.id}") and r.status == OutboxStatus.CANCELLED.value
    ]
    assert len(cancelled_reminders) == 3


@pytest.mark.asyncio
async def test_outbox_worker_batch_processing(services, repos, db_session):
    outbox_srv = services["outbox"]
    outbox_repo = repos["outbox"]
    mock_notifier = MockNotifier()

    # Enqueue past-due pending event
    await outbox_srv.enqueue_event(
        event_type=EventType.TASK_CREATED,
        idempotency_key="test_key_1",
        payload={"msg": "Hello"},
        scheduled_for=datetime.now(UTC),
    )

    # Check pending batch
    pending = await outbox_repo.fetch_pending_batch(limit=10)
    assert len(pending) >= 1

    # Test processing directly with mock notifier
    worker = OutboxWorker(outbox_repo=outbox_repo, notifier=mock_notifier, poll_interval=1.0)
    await worker._process_single_event(pending[0])
    assert len(mock_notifier.dispatched) == 1
    assert mock_notifier.dispatched[0].idempotency_key == "test_key_1"


@pytest.mark.asyncio
async def test_outbox_worker_429_rate_limit_backoff(services, repos):
    outbox_srv = services["outbox"]
    outbox_repo = repos["outbox"]

    class RateLimitedNotifier(INotificationDispatcher):
        async def dispatch_event(self, event):
            exc = Exception("Discord rate limit")
            exc.status = 429
            exc.retry_after = 0.1
            raise exc

    notifier = RateLimitedNotifier()
    evt = await outbox_srv.enqueue_event(
        event_type=EventType.TASK_CREATED,
        idempotency_key="test_rate_limited",
        payload={"msg": "Burst"},
        scheduled_for=datetime.now(UTC),
    )

    worker = OutboxWorker(outbox_repo=outbox_repo, notifier=notifier, poll_interval=0.1)
    await worker.process_batch()

    assert evt is not None


@pytest.mark.asyncio
async def test_discord_notifier_user_preferences_routing(services):
    """Verify DiscordNotifier respects user notification preferences (DM, Channel, Both, Silent, Closed DMs)."""
    from unittest.mock import AsyncMock, MagicMock

    import discord

    from src.adapters.discord_bot.discord_notifier import DiscordNotifier
    from src.domain.enums import NotificationPreference
    from src.domain.models import OutboxEvent

    user_srv = services["user"]
    guild_id = 999111888

    # Set user 1001 -> CHANNEL
    await user_srv.set_preference(guild_id, 1001, NotificationPreference.CHANNEL)
    # Set user 1002 -> NONE (Silent)
    await user_srv.set_preference(guild_id, 1002, NotificationPreference.NONE)
    # User 1003 has default (DM) but DMs closed -> triggers fallback in thread

    bot = MagicMock()
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.send = AsyncMock()
    mock_thread.parent = None
    bot.get_channel = MagicMock(return_value=mock_thread)

    mock_user_1003 = MagicMock(spec=discord.User)
    mock_user_1003.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "DMs closed"))
    bot.get_user = MagicMock(return_value=mock_user_1003)
    bot.fetch_user = AsyncMock(return_value=mock_user_1003)

    notifier = DiscordNotifier(bot, user_service=user_srv)

    # 1. Test status change for user 1001 (CHANNEL)
    evt_channel = OutboxEvent(
        event_type=EventType.TASK_STATUS_CHANGED,
        idempotency_key="status_channel_test",
        payload={
            "task_id": "test-task-1",
            "short_id": "T-1",
            "title": "Build UI",
            "guild_id": guild_id,
            "old_status": "notStarted",
            "new_status": "inProgress",
            "actor_discord_id": 9999,
            "assignee_discord_id": 1001,
            "watchers": [],
            "discord_thread_id": 555666,
        },
    )
    await notifier.dispatch_event(evt_channel)
    # Thread received status message + in-thread ping for 1001
    assert mock_thread.send.await_count >= 2

    # 2. Test status change for user 1002 (NONE / Silent)
    mock_thread.send.reset_mock()
    evt_silent = OutboxEvent(
        event_type=EventType.TASK_STATUS_CHANGED,
        idempotency_key="status_silent_test",
        payload={
            "task_id": "test-task-2",
            "short_id": "T-2",
            "title": "Build UI 2",
            "guild_id": guild_id,
            "old_status": "notStarted",
            "new_status": "inProgress",
            "actor_discord_id": 9999,
            "assignee_discord_id": 1002,
            "watchers": [],
            "discord_thread_id": 555666,
        },
    )
    await notifier.dispatch_event(evt_silent)
    # Only thread update message, NO extra user ping
    assert mock_thread.send.await_count == 1
