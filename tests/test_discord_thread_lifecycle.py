from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.bot import DggPmBot
from src.adapters.discord_bot.cogs.project_cog import ProjectCog
from src.adapters.discord_bot.cogs.task_cog import TaskCog
from src.domain.enums import TaskStatus


@pytest.mark.asyncio
async def test_task_create_sets_7day_auto_archive(services):
    """Verify task-create creates a thread with auto_archive_duration=10080 (7 days)."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 1234567890

    await proj_srv.create_project(guild_id=guild_id, name="Infra Core", prefix="INF")

    bot = MagicMock()
    cog = TaskCog(bot=bot, task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 999111
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.id = 888222
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 777333
    mock_thread.send = AsyncMock()
    mock_msg.create_thread = AsyncMock(return_value=mock_thread)
    mock_channel.send = AsyncMock(return_value=mock_msg)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = 1001
    interaction.channel = mock_channel
    interaction.channel_id = mock_channel.id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.task_create.callback(
        cog,
        interaction=interaction,
        project_name="Infra Core",
        title="Deploy Kubernetes cluster",
        assignee=None,
        due=None,
        priority="high",
    )

    mock_msg.create_thread.assert_awaited_once()
    kwargs = mock_msg.create_thread.call_args.kwargs
    assert kwargs.get("auto_archive_duration") == 10080
    assert "[INF-1] Deploy Kubernetes cluster" in kwargs.get("name")


@pytest.mark.asyncio
async def test_task_standalone_creates_thread(services):
    """Verify task-standalone creates a starter message and discussion thread in TextChannel."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 1234567890

    bot = MagicMock()
    cog = TaskCog(bot=bot, task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 999111
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.id = 888222
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 777333
    mock_thread.send = AsyncMock()
    mock_msg.create_thread = AsyncMock(return_value=mock_thread)
    mock_channel.send = AsyncMock(return_value=mock_msg)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = 1001
    interaction.channel = mock_channel
    interaction.channel_id = mock_channel.id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.task_standalone.callback(
        cog,
        interaction=interaction,
        title="Quick hotfix on production",
        assignee=None,
        due=None,
        priority="normal",
    )

    mock_msg.create_thread.assert_awaited_once()
    kwargs = mock_msg.create_thread.call_args.kwargs
    assert kwargs.get("auto_archive_duration") == 10080
    assert "Quick hotfix on production" in kwargs.get("name")

    # DB should have thread ID persisted
    tasks, total = await task_srv.list_tasks(guild_id=guild_id)
    assert total >= 1
    hotfix_task = next(t for t in tasks if t.title == "Quick hotfix on production")
    assert hotfix_task.discord_thread_id == 777333


@pytest.mark.asyncio
async def test_bot_sync_task_thread_archive_and_unarchive(services):
    """Verify DggPmBot.sync_task_thread archives when completed/archived and unarchives when reopened."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 987654321

    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Database migration",
        creator_discord_id=1001,
    )
    await task_srv.update_discord_message_ids(task.id, 55555, 66666)
    task = await task_srv.get_by_id(task.id)

    bot = DggPmBot(task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 66666
    mock_thread.name = f"[{task.short_id}] Database migration"
    mock_thread.archived = False
    mock_thread.edit = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_thread)

    # 1. When status is COMPLETED, should archive thread
    task = await task_srv.update_status(
        task_id=task.id,
        new_status=TaskStatus.COMPLETED,
        expected_version=task.version,
        actor_discord_id=1001,
    )
    await bot.sync_task_thread(task)
    mock_thread.edit.assert_awaited_once_with(archived=True)

    # 2. When status is reopened (IN_PROGRESS), should unarchive thread
    mock_thread.archived = True
    mock_thread.edit.reset_mock()
    task = await task_srv.update_status(
        task_id=task.id,
        new_status=TaskStatus.IN_PROGRESS,
        expected_version=task.version,
        actor_discord_id=1001,
    )
    await bot.sync_task_thread(task)
    mock_thread.edit.assert_awaited_once_with(archived=False)


@pytest.mark.asyncio
async def test_bot_sync_task_thread_title_sync(services):
    """Verify DggPmBot.sync_task_thread updates thread title when sync_title=True."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 987654321

    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Initial Title",
        creator_discord_id=1001,
    )
    await task_srv.update_discord_message_ids(task.id, 55555, 66666)

    updated_task = await task_srv.update_details(
        task_id=task.id,
        actor_discord_id=1001,
        title="Updated Awesome Title",
    )

    bot = DggPmBot(task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 66666
    mock_thread.name = f"[{task.short_id}] Initial Title"
    mock_thread.archived = False
    mock_thread.edit = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_thread)

    await bot.sync_task_thread(updated_task, sync_title=True)
    mock_thread.edit.assert_awaited_once_with(name=f"[{task.short_id}] Updated Awesome Title")


@pytest.mark.asyncio
async def test_project_archive_cascade_threads(services):
    """Verify archiving a project batch-archives its task threads, and unarchiving restores them."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 3333333333

    project = await proj_srv.create_project(guild_id=guild_id, name="Cascade Project", prefix="CAS")
    t1 = await task_srv.create_task(guild_id=guild_id, title="Task 1", creator_discord_id=1001, project_id=project.id)
    t2 = await task_srv.create_task(guild_id=guild_id, title="Task 2", creator_discord_id=1001, project_id=project.id)
    await task_srv.update_discord_message_ids(t1.id, 111, 222)
    await task_srv.update_discord_message_ids(t2.id, 333, 444)

    bot = MagicMock()
    bot.sync_task_thread = AsyncMock()

    cog = ProjectCog(bot=bot, project_service=proj_srv, team_service=team_srv, task_service=task_srv)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    # 1. Archive project
    await cog.project_archive.callback(cog, interaction=interaction, project_name="Cascade Project")
    assert bot.sync_task_thread.await_count == 2
    # Verify sync_task_thread called with action="archive" for each task
    called_task_ids = [call.args[0].id for call in bot.sync_task_thread.call_args_list]
    assert t1.id in called_task_ids
    assert t2.id in called_task_ids

    # 2. Unarchive project
    bot.sync_task_thread.reset_mock()
    await cog.project_unarchive.callback(cog, interaction=interaction, project_name="Cascade Project")
    assert bot.sync_task_thread.await_count == 2
    unarchive_called_ids = [call.args[0].id for call in bot.sync_task_thread.call_args_list]
    assert t1.id in unarchive_called_ids
    assert t2.id in unarchive_called_ids


@pytest.mark.asyncio
async def test_discord_notifier_rearchives_thread_on_completion():
    """Verify DiscordNotifier re-archives the thread after posting a completion message."""
    from src.adapters.discord_bot.discord_notifier import DiscordNotifier
    from src.domain.enums import EventType
    from src.domain.models import OutboxEvent

    bot = MagicMock()
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 999888
    mock_thread.parent = None
    mock_thread.send = AsyncMock()
    mock_thread.edit = AsyncMock()
    bot.get_channel = MagicMock(return_value=mock_thread)

    notifier = DiscordNotifier(bot=bot)

    event = OutboxEvent(
        event_type=EventType.TASK_STATUS_CHANGED,
        idempotency_key="status_test_1",
        payload={
            "short_id": "T-1",
            "title": "Fix bug",
            "old_status": "inProgress",
            "new_status": "completed",
            "actor_discord_id": 1001,
            "discord_thread_id": 999888,
        },
    )

    await notifier.dispatch_event(event)

    # Verify message sent to thread
    mock_thread.send.assert_awaited_once()
    # Verify thread was re-archived after sending the message
    mock_thread.edit.assert_awaited_once_with(archived=True)
