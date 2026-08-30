from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import discord
import pytest

from src.adapters.discord_bot.bot import DggPmBot
from src.adapters.discord_bot.cogs.project_cog import ProjectCog
from src.adapters.discord_bot.cogs.task_cog import TaskCog
from src.adapters.discord_bot.discord_notifier import DiscordNotifier
from src.adapters.discord_bot.views.forum_helpers import resolve_forum_tags, setup_forum_tags
from src.adapters.discord_bot.views.task_menu import TaskCreateModal
from src.domain.enums import EventType, PriorityLevel, TaskStatus
from src.domain.models import OutboxEvent, Task


def _create_mock_tag(tag_id: int, name: str) -> MagicMock:
    tag = MagicMock(spec=discord.ForumTag)
    tag.id = tag_id
    tag.name = name
    return tag


def test_resolve_forum_tags_matching():
    """Verify resolve_forum_tags correctly matches status and priority tags while preserving custom tags."""
    mock_forum = MagicMock(spec=discord.ForumChannel)
    tag_todo = _create_mock_tag(1, "To Do")
    tag_wip = _create_mock_tag(2, "In Progress")
    tag_done = _create_mock_tag(3, "Completed")
    tag_high = _create_mock_tag(4, "🔴 High Priority")
    tag_norm = _create_mock_tag(5, "🟡 Normal")
    tag_custom = _create_mock_tag(6, "Backend")

    mock_forum.available_tags = [tag_todo, tag_wip, tag_done, tag_high, tag_norm, tag_custom]

    task = Task(
        id=uuid4(),
        short_id="AUTH-1",
        guild_id=12345,
        title="Implement Auth",
        creator_discord_id=1001,
        status=TaskStatus.IN_PROGRESS,
        priority=PriorityLevel.HIGH,
    )

    # Resolve with custom tag preserved
    tags = resolve_forum_tags(mock_forum, task, existing_tags=[tag_custom, tag_todo])
    assert tag_wip in tags
    assert tag_high in tags
    assert tag_custom in tags
    assert tag_todo not in tags  # Old status tag replaced


@pytest.mark.asyncio
async def test_project_create_with_forum_channel(services):
    """Verify /project-create accepts a ForumChannel and formats the embed correctly."""
    proj_srv = services["project"]
    team_srv = services["team"]
    bot = MagicMock()
    cog = ProjectCog(bot=bot, project_service=proj_srv, team_service=team_srv)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = 7777777777
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    mock_forum = MagicMock(spec=discord.ForumChannel)
    mock_forum.id = 555444333

    await cog.project_create.callback(
        cog,
        interaction=interaction,
        name="Security Audit",
        channel=mock_forum,
        prefix="SEC",
        description="Security pentest deliverables",
        category="Security",
    )

    interaction.response.defer.assert_awaited_once_with(ephemeral=False)
    interaction.followup.send.assert_awaited_once()

    send_call_args = interaction.followup.send.call_args
    embed = send_call_args.kwargs.get("embed")
    assert embed is not None
    assert "Forum Post Board" in next(f.value for f in embed.fields if f.name == "Bound Channel")

    project = await proj_srv.get_by_name(7777777777, "Security Audit")
    assert project is not None
    assert project.discord_channel_id == 555444333


@pytest.mark.asyncio
async def test_task_create_in_forum_channel(services):
    """Verify /task-create creates a Forum Post (thread + starter message) with tags in a ForumChannel."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 1122334455

    project = await proj_srv.create_project(
        guild_id=guild_id,
        name="Core Engine",
        prefix="COR",
        discord_channel_id=987654321,
    )

    bot = MagicMock()
    cog = TaskCog(bot=bot, task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    mock_forum = MagicMock(spec=discord.ForumChannel)
    mock_forum.id = 987654321
    tag_todo = _create_mock_tag(10, "Not Started")
    tag_urgent = _create_mock_tag(20, "High")
    mock_forum.available_tags = [tag_todo, tag_urgent]

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 888999
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.id = 888999

    res_mock = MagicMock()
    res_mock.thread = mock_thread
    res_mock.message = mock_msg
    mock_forum.create_thread = AsyncMock(return_value=res_mock)
    bot.get_channel = MagicMock(return_value=mock_forum)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = 1001
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel_id = 111111
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.task_create.callback(
        cog,
        interaction=interaction,
        project_name="Core Engine",
        title="Refactor Query Pipeline",
        assignee=None,
        due=None,
        priority="high",
    )

    mock_forum.create_thread.assert_awaited_once()
    kwargs = mock_forum.create_thread.call_args.kwargs
    assert kwargs.get("auto_archive_duration") == 10080
    assert "[COR-1] Refactor Query Pipeline" in kwargs.get("name")
    assert tag_urgent in kwargs.get("applied_tags")

    # Verify task persisted with message and thread IDs
    tasks, _ = await task_srv.list_tasks(guild_id=guild_id, project_id=project.id)
    assert len(tasks) == 1
    assert tasks[0].discord_thread_id == 888999
    assert tasks[0].discord_message_id == 888999


@pytest.mark.asyncio
async def test_task_create_modal_in_forum_channel(services):
    """Verify TaskCreateModal properly creates a thread in a ForumChannel."""
    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 9988776655

    project = await proj_srv.create_project(
        guild_id=guild_id,
        name="Design System",
        prefix="DS",
        discord_channel_id=444555666,
    )

    mock_forum = MagicMock(spec=discord.ForumChannel)
    mock_forum.id = 444555666
    mock_forum.available_tags = []

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 777666
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.id = 777666
    res_mock = MagicMock()
    res_mock.thread = mock_thread
    res_mock.message = mock_msg
    mock_forum.create_thread = AsyncMock(return_value=res_mock)

    modal = TaskCreateModal(task_service=task_srv, project=project, target_channel=mock_forum)
    modal.title_input._value = "Add Dark Mode Colors"
    modal.desc_input._value = "Tokens for dark mode"
    modal.priority_input._value = "normal"
    modal.assignee_input._value = ""
    modal.due_input._value = ""

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = 1001
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)
    mock_forum.create_thread.assert_awaited_once()
    kwargs = mock_forum.create_thread.call_args.kwargs
    assert "[DS-1] Add Dark Mode Colors" in kwargs.get("name")


@pytest.mark.asyncio
async def test_bot_sync_forum_post_starter_message_and_tags(services):
    """Verify DggPmBot.sync_root_task_message and sync_task_thread work inside ForumChannels."""
    proj_srv = services["project"]
    task_srv = services["task"]
    team_srv = services["team"]
    guild_id = 123123123

    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Migrate Cache Cluster",
        creator_discord_id=1001,
        priority=PriorityLevel.HIGH,
    )
    await task_srv.update_discord_message_ids(task.id, 888111, 888111)
    task = await task_srv.get_by_id(task.id)

    bot = DggPmBot(task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    mock_forum = MagicMock(spec=discord.ForumChannel)
    tag_high = _create_mock_tag(1, "High")
    tag_done = _create_mock_tag(2, "Completed")
    mock_forum.available_tags = [tag_high, tag_done]

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 888111
    mock_thread.parent = mock_forum
    mock_thread.applied_tags = [tag_high]
    mock_thread.archived = False
    mock_thread.edit = AsyncMock()

    mock_starter_msg = MagicMock(spec=discord.Message)
    mock_starter_msg.edit = AsyncMock()
    mock_thread.starter_message = mock_starter_msg
    mock_thread.fetch_message = AsyncMock(return_value=mock_starter_msg)

    bot.get_channel = MagicMock(return_value=mock_thread)

    # 1. Test sync_root_task_message edits starter message in forum post
    await bot.sync_root_task_message(task)
    mock_starter_msg.edit.assert_awaited_once()

    # 2. Test sync_task_thread updates applied tags and archives upon completion
    completed_task = await task_srv.update_status(
        task_id=task.id,
        new_status=TaskStatus.COMPLETED,
        expected_version=task.version,
        actor_discord_id=1001,
    )
    await bot.sync_task_thread(completed_task)
    mock_thread.edit.assert_awaited_once()
    edit_kwargs = mock_thread.edit.call_args.kwargs
    assert edit_kwargs.get("archived") is True
    assert tag_done in edit_kwargs.get("applied_tags")


@pytest.mark.asyncio
async def test_discord_notifier_handles_forum_post_status_changed():
    """Verify DiscordNotifier updates starter message and applies forum tags on status changed."""
    bot = MagicMock()
    mock_forum = MagicMock(spec=discord.ForumChannel)
    tag_done = _create_mock_tag(99, "Completed")
    mock_forum.available_tags = [tag_done]

    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 555666
    mock_thread.parent = mock_forum
    mock_thread.send = AsyncMock()
    mock_thread.edit = AsyncMock()
    mock_thread.archived = False

    mock_embed = MagicMock(spec=discord.Embed)
    mock_field = MagicMock()
    mock_field.name = "Status"
    mock_field.inline = True
    mock_embed.fields = [mock_field]
    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.embeds = [mock_embed]
    mock_msg.edit = AsyncMock()

    mock_thread.starter_message = mock_msg
    mock_thread.fetch_message = AsyncMock(return_value=mock_msg)
    bot.get_channel = MagicMock(return_value=mock_thread)

    notifier = DiscordNotifier(bot=bot)
    event = OutboxEvent(
        event_type=EventType.TASK_STATUS_CHANGED,
        idempotency_key="status_forum_test_1",
        payload={
            "short_id": "T-10",
            "title": "Fix memory leak",
            "old_status": "inProgress",
            "new_status": "completed",
            "actor_discord_id": 1001,
            "discord_thread_id": 555666,
            "discord_message_id": 555666,
        },
    )

    await notifier.dispatch_event(event)

    # Starter message in forum post should have been edited
    mock_msg.edit.assert_awaited_once()
    # Thread should have applied tags and been archived
    mock_thread.edit.assert_awaited_once()
    kwargs = mock_thread.edit.call_args.kwargs
    assert kwargs.get("archived") is True
    assert tag_done in kwargs.get("applied_tags")


@pytest.mark.asyncio
async def test_setup_forum_tags_merging():
    """Verify setup_forum_tags appends missing standard PM tags and preserves custom tags."""
    mock_forum = MagicMock(spec=discord.ForumChannel)
    custom_tag = _create_mock_tag(1, "Customer Request")
    existing_wip = _create_mock_tag(2, "In Progress")
    mock_forum.available_tags = [custom_tag, existing_wip]
    mock_forum.edit = AsyncMock()

    added, total, err = await setup_forum_tags(mock_forum)
    assert err is None
    assert added > 0
    assert total > 2
    mock_forum.edit.assert_awaited_once()
    saved_tags = mock_forum.edit.call_args.kwargs.get("available_tags")
    assert custom_tag in saved_tags
    assert existing_wip in saved_tags
    tag_names = [t.name for t in saved_tags]
    assert "High Priority" in tag_names
    assert "Completed" in tag_names


@pytest.mark.asyncio
async def test_setup_forum_tags_forbidden():
    """Verify setup_forum_tags handles missing permissions gracefully."""
    mock_forum = MagicMock(spec=discord.ForumChannel)
    mock_forum.available_tags = []
    mock_forum.name = "restricted-forum"
    mock_forum.id = 999111
    mock_forum.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Missing Permissions"))

    added, _total, err = await setup_forum_tags(mock_forum)
    assert added == 0
    assert err is not None
    assert "Manage Channels" in err


@pytest.mark.asyncio
async def test_project_setup_forum_command(services):
    """Verify /project-setup-forum executes setup_forum_tags and replies with embed."""
    proj_srv = services["project"]
    team_srv = services["team"]
    bot = MagicMock()
    cog = ProjectCog(bot=bot, project_service=proj_srv, team_service=team_srv)

    mock_forum = MagicMock(spec=discord.ForumChannel)
    mock_forum.id = 333222111
    mock_forum.name = "eng-backlog"
    mock_forum.available_tags = []
    mock_forum.edit = AsyncMock()

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cog.project_setup_forum.callback(cog, interaction=interaction, forum=mock_forum)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Forum Tags Configured" in embed.title
