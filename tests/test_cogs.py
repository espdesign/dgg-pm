from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.cogs.project_cog import ProjectCog


def test_project_create_command_parameters():
    """Verify that project-create command requires both 'name' and 'channel'."""
    cmd = ProjectCog.project_create
    params = {p.name: p for p in cmd.parameters}

    assert "name" in params
    assert params["name"].required is True

    assert "channel" in params
    assert params["channel"].required is True

    # Optional parameters
    assert "prefix" in params
    assert params["prefix"].required is False

    assert "description" in params
    assert params["description"].required is False

    assert "category" in params
    assert params["category"].required is False


@pytest.mark.asyncio
async def test_project_create_execution(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    bot = MagicMock()

    cog = ProjectCog(bot=bot, project_service=proj_srv, team_service=team_srv)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = 9999999999
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 123456789

    await cog.project_create.callback(
        cog,
        interaction=interaction,
        name="Platform Core",
        channel=mock_channel,
        prefix="PLC",
        description="Platform engineering",
        category="Engineering",
    )

    interaction.response.defer.assert_awaited_once_with(ephemeral=False)
    interaction.followup.send.assert_awaited_once()

    # Check project persisted in db with bound channel id
    project = await proj_srv.get_by_name(9999999999, "Platform Core")
    assert project is not None
    assert project.prefix == "PLC"
    assert project.discord_channel_id == 123456789


@pytest.mark.asyncio
async def test_project_and_team_autocomplete(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    guild_id = 8888888888
    bot = MagicMock()

    cog = ProjectCog(bot=bot, project_service=proj_srv, team_service=team_srv)

    # Seed projects
    await proj_srv.create_project(guild_id=guild_id, name="Frontend UI", prefix="FUI")
    await proj_srv.create_project(guild_id=guild_id, name="Backend API", prefix="BAPI")
    p3 = await proj_srv.create_project(guild_id=guild_id, name="Legacy System", prefix="LEG")
    await proj_srv.archive_project(p3.id)

    # Seed team
    await team_srv.create_team(guild_id=guild_id, name="Core Infra", discord_role_id=111222333)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id

    # 1. Project autocomplete for active projects
    choices_all = await cog.project_autocomplete(interaction, current="")
    assert len(choices_all) == 2  # Only active projects
    choice_names = [c.name for c in choices_all]
    assert "Frontend UI (FUI)" in choice_names
    assert "Backend API (BAPI)" in choice_names

    # 2. Filtered project autocomplete
    choices_filtered = await cog.project_autocomplete(interaction, current="front")
    assert len(choices_filtered) == 1
    assert choices_filtered[0].value == "Frontend UI"

    # 3. Team autocomplete
    team_choices = await cog.team_autocomplete(interaction, current="infra")
    assert len(team_choices) == 1
    assert team_choices[0].value == "Core Infra"

    # 4. Archived project autocomplete
    archived_choices = await cog.archived_project_autocomplete(interaction, current="")
    assert len(archived_choices) == 1
    assert archived_choices[0].value == "Legacy System"


@pytest.mark.asyncio
async def test_task_action_view_and_modals(services):
    from src.adapters.discord_bot.views.task_buttons import TaskActionView
    from src.adapters.discord_bot.views.task_modals import TaskEditModal
    from src.domain.enums import PriorityLevel

    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 7777777777

    project = await proj_srv.create_project(guild_id=guild_id, name="Security Operations", prefix="SEC")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Firewall Rules Audit",
        creator_discord_id=1001,
        project_id=project.id,
        priority=PriorityLevel.NORMAL,
    )

    # 1. Test TaskActionView component structure
    view = TaskActionView(
        task_id=task.id,
        current_status=task.status,
        current_priority=task.priority,
        task_service=task_srv,
    )

    # Check children: start_btn, complete_btn, note_btn, edit_btn, priority_select, assignee_select, due_select
    custom_ids = [item.custom_id for item in view.children if hasattr(item, "custom_id")]
    assert f"task:start:{task.id}" in custom_ids
    assert f"task:complete:{task.id}" in custom_ids
    assert f"task:note:{task.id}" in custom_ids
    assert f"task:edit:{task.id}" in custom_ids
    assert f"task:priority:{task.id}" in custom_ids
    assert f"task:assignee:{task.id}" in custom_ids
    assert f"task:due:{task.id}" in custom_ids

    # 2. Test priority select callback
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 1002
    mock_interaction.response = MagicMock()
    mock_interaction.response.edit_message = AsyncMock()

    view.priority_select._values = ["high"]
    await view._on_priority_selected(mock_interaction)
    mock_interaction.response.edit_message.assert_awaited_once()

    refreshed = await task_srv.get_by_id(task.id)
    assert refreshed.priority == PriorityLevel.HIGH

    # 3. Test due date preset select callback
    due_interaction = MagicMock(spec=discord.Interaction)
    due_interaction.user = MagicMock()
    due_interaction.user.id = 1002
    due_interaction.response = MagicMock()
    due_interaction.response.edit_message = AsyncMock()

    view.due_select._values = ["3days"]
    await view._on_due_selected(due_interaction)
    due_interaction.response.edit_message.assert_awaited_once()

    due_refreshed = await task_srv.get_by_id(task.id)
    assert due_refreshed.due_at is not None

    # 4. Test TaskEditModal with natural language date
    edit_modal = TaskEditModal(task=due_refreshed, task_service=task_srv)
    edit_modal.title_input._value = "Firewall & WAF Rules Audit"
    edit_modal.body_input._value = "Comprehensive review of all WAF rules"
    edit_modal.due_input._value = "in 2 weeks"
    edit_modal.cc_input._value = "<@1001> <@1003>"

    modal_interaction = MagicMock(spec=discord.Interaction)
    modal_interaction.user = MagicMock()
    modal_interaction.user.id = 1001
    modal_interaction.message = MagicMock()
    modal_interaction.message.edit = AsyncMock()
    modal_interaction.response = MagicMock()
    modal_interaction.response.send_message = AsyncMock()

    await edit_modal.on_submit(modal_interaction)

    updated = await task_srv.get_by_id(task.id)
    assert updated.title == "Firewall & WAF Rules Audit"
    assert updated.body == "Comprehensive review of all WAF rules"
    assert updated.due_at is not None
    assert set(updated.watchers) == {1001, 1003}
