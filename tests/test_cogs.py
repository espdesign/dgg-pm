from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.cogs.pm_cog import PmCog
from src.adapters.discord_bot.cogs.project_cog import ProjectCog
from src.adapters.discord_bot.cogs.settings_cog import SettingsCog
from src.domain.enums import NotificationPreference


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

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
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

    # Check children: action buttons, priority, assignee, due select, watchers select
    custom_ids = [item.custom_id for item in view.children if hasattr(item, "custom_id")]
    assert f"task:start:{task.id}" in custom_ids
    assert f"task:complete:{task.id}" in custom_ids
    assert f"task:note:{task.id}" in custom_ids
    assert f"task:edit:{task.id}" in custom_ids
    assert f"task:unassign:{task.id}" in custom_ids
    assert f"task:priority:{task.id}" in custom_ids
    assert f"task:assignee:{task.id}" in custom_ids
    assert f"task:due:{task.id}" in custom_ids
    assert f"task:watchers:{task.id}" in custom_ids

    # Completed view has Reopen button
    from src.domain.enums import TaskStatus

    completed_view = TaskActionView(
        task_id=task.id,
        current_status=TaskStatus.COMPLETED,
        current_priority=task.priority,
        task_service=task_srv,
    )
    completed_ids = [item.custom_id for item in completed_view.children if hasattr(item, "custom_id")]
    assert f"task:reopen:{task.id}" in completed_ids
    assert f"task:start:{task.id}" not in completed_ids

    # 2. Test unassign button via dynamic dispatcher
    from src.adapters.discord_bot.bot import DggPmBot

    bot = DggPmBot(
        task_service=task_srv,
        project_service=proj_srv,
        team_service=services["team"],
    )

    unassign_interaction = MagicMock(spec=discord.Interaction)
    unassign_interaction.guild_id = guild_id
    unassign_interaction.user = MagicMock()
    unassign_interaction.user.id = 1002
    unassign_interaction.response = MagicMock()
    unassign_interaction.response.is_done.return_value = False
    unassign_interaction.response.edit_message = AsyncMock()

    await bot._handle_dynamic_task_button(unassign_interaction, "unassign", task.id)
    unassign_interaction.response.edit_message.assert_awaited_once()

    unassigned_task = await task_srv.get_by_id(task.id)
    assert unassigned_task.assignee_discord_id is None

    # 3. Test priority select via dynamic dispatcher
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild_id = guild_id
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 1002
    mock_interaction.data = {"values": ["high"]}
    mock_interaction.response = MagicMock()
    mock_interaction.response.is_done.return_value = False
    mock_interaction.response.edit_message = AsyncMock()

    await bot._handle_dynamic_task_button(mock_interaction, "priority", task.id)
    mock_interaction.response.edit_message.assert_awaited_once()

    refreshed = await task_srv.get_by_id(task.id)
    assert refreshed.priority == PriorityLevel.HIGH

    # 4. Test due date preset select via dynamic dispatcher
    due_interaction = MagicMock(spec=discord.Interaction)
    due_interaction.guild_id = guild_id
    due_interaction.user = MagicMock()
    due_interaction.user.id = 1002
    due_interaction.data = {"values": ["3days"]}
    due_interaction.response = MagicMock()
    due_interaction.response.is_done.return_value = False
    due_interaction.response.edit_message = AsyncMock()

    await bot._handle_dynamic_task_button(due_interaction, "due", task.id)
    due_interaction.response.edit_message.assert_awaited_once()

    due_refreshed = await task_srv.get_by_id(task.id)
    assert due_refreshed.due_at is not None

    # 5. Test watchers multi-select via dynamic dispatcher
    watchers_interaction = MagicMock(spec=discord.Interaction)
    watchers_interaction.guild_id = guild_id
    watchers_interaction.user = MagicMock()
    watchers_interaction.user.id = 1002
    watchers_interaction.data = {"values": ["2001", "2002"]}
    watchers_interaction.response = MagicMock()
    watchers_interaction.response.is_done.return_value = False
    watchers_interaction.response.edit_message = AsyncMock()

    await bot._handle_dynamic_task_button(watchers_interaction, "watchers", task.id)
    watchers_interaction.response.edit_message.assert_awaited_once()

    watchers_refreshed = await task_srv.get_by_id(task.id)
    assert 2001 in watchers_refreshed.watchers
    assert 2002 in watchers_refreshed.watchers

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


@pytest.mark.asyncio
async def test_dynamic_task_button_rejects_cross_guild(services):
    """Buttons must not act on tasks that don't belong to the interaction's guild."""
    from src.adapters.discord_bot.bot import DggPmBot

    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 1000000001

    project = await proj_srv.create_project(guild_id=guild_id, name="Trusted Server", prefix="TRU")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Secret Task",
        creator_discord_id=1001,
        project_id=project.id,
    )

    bot = DggPmBot(
        task_service=task_srv,
        project_service=proj_srv,
        team_service=services["team"],
    )

    # Interaction from a DIFFERENT guild attempting to act on the task
    foreign_interaction = MagicMock(spec=discord.Interaction)
    foreign_interaction.guild_id = 8888888888
    foreign_interaction.user = MagicMock()
    foreign_interaction.user.id = 9999
    foreign_interaction.response = MagicMock()
    foreign_interaction.response.is_done.return_value = False
    foreign_interaction.response.send_message = AsyncMock()

    await bot._handle_dynamic_task_button(foreign_interaction, "note", task.id)

    foreign_interaction.response.send_message.assert_awaited_once()
    error_msg = foreign_interaction.response.send_message.await_args.args[0]
    assert "does not belong to this server" in error_msg

    # Task unchanged
    refreshed = await task_srv.get_by_id(task.id)
    assert refreshed.title == "Secret Task"


@pytest.mark.asyncio
async def test_thread_workspace_content_leads_with_description(services):
    """The thread workspace message should lead with the task description for clarity."""
    from src.adapters.discord_bot.views.task_embed import build_thread_workspace_content
    from src.domain.enums import PriorityLevel

    task_srv = services["task"]
    guild_id = 1000000003

    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Workspace Clarity",
        creator_discord_id=1001,
        assignee_discord_id=2001,
        priority=PriorityLevel.LOW,
        body="Deploy the new API gateway and wire up monitoring dashboards.",
        project_id=None,
    )

    content = build_thread_workspace_content(task)
    lines = content.splitlines()
    # First line is the description; assignee/priority summary follows on a separate line
    assert lines[0] == "Deploy the new API gateway and wire up monitoring dashboards."
    assert "Assignee: <@2001>" in content
    assert "Priority: `LOW`" in content

    # Long descriptions are truncated safely within Discord's 2000-char limit
    task.body = "X" * 2500
    truncated = build_thread_workspace_content(task)
    assert len(truncated) <= 2000
    assert truncated.splitlines()[0].endswith("...")

    # Unassigned + no description fallbacks
    task.assignee_discord_id = None
    task.body = None
    fallback = build_thread_workspace_content(task)
    assert fallback.startswith("*No additional description provided.*")
    assert "Assignee: Unassigned" in fallback


@pytest.mark.asyncio
async def test_dynamic_task_button_same_guild_note_modal(services):
    """A note button from the correct guild should open the note modal."""
    from src.adapters.discord_bot.bot import DggPmBot

    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 1000000002

    project = await proj_srv.create_project(guild_id=guild_id, name="Local Server", prefix="LOC")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Local Task",
        creator_discord_id=1001,
        project_id=project.id,
    )

    bot = DggPmBot(
        task_service=task_srv,
        project_service=proj_srv,
        team_service=services["team"],
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild_id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = 1002
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_modal = AsyncMock()

    await bot._handle_dynamic_task_button(interaction, "note", task.id)

    interaction.response.send_modal.assert_awaited_once()
    interaction.response.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_settings_cog_my_settings(services):
    user_srv = services["user"]
    bot = MagicMock()
    cog = SettingsCog(
        bot=bot,
        user_service=user_srv,
        project_service=services["project"],
        team_service=services["team"],
        task_service=services["task"],
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = 123456789
    interaction.user = MagicMock()
    interaction.user.id = 987654321
    interaction.user.display_name = "Charlie"
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # 1. Run /my-settings without argument
    await cog.my_settings.callback(cog, interaction=interaction, notify=None)
    interaction.response.send_message.assert_awaited_once()

    # 2. Run /my-settings with notify choice
    choice = MagicMock()
    choice.value = "both"
    await cog.my_settings.callback(cog, interaction=interaction, notify=choice)
    assert interaction.response.send_message.await_count == 2

    pref = await user_srv.get_preference(123456789, 987654321)
    assert pref == NotificationPreference.BOTH


def test_seed_script_production_safety_guards(monkeypatch):
    """Verify check_production_safety_guard blocks execution in unsafe environments."""
    from scripts.seed_dev_data import check_production_safety_guard
    from src.config import settings

    # 1. Blocks if ENVIRONMENT is production
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="cannot be run in production"):
        check_production_safety_guard(1543430283250901023)

    # 2. Blocks if DISCORD_GUILD_ID is not configured
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DISCORD_GUILD_ID", None)
    with pytest.raises(RuntimeError, match="requires DISCORD_GUILD_ID"):
        check_production_safety_guard(1543430283250901023)

    # 3. Blocks if target guild does not match dev guild
    monkeypatch.setattr(settings, "DISCORD_GUILD_ID", 1543430283250901023)
    with pytest.raises(RuntimeError, match="does not match configured dev guild"):
        check_production_safety_guard(999999999999999999)

    # 4. Blocks if DATABASE_URL points to a production cloud database
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:pass@production-db.rds.amazonaws.com:5432/dgg_pm",
    )
    with pytest.raises(RuntimeError, match="appears to point to a production/cloud database"):
        check_production_safety_guard(1543430283250901023)


@pytest.mark.asyncio
async def test_pm_project_create_with_required_role(services):
    """Verify /pm project create requires role, creates team, and assigns squad to project."""
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 1122334455

    pm_cog = PmCog(
        bot=MagicMock(),
        project_service=proj_srv,
        team_service=team_srv,
        task_service=task_srv,
    )

    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 55667788
    mock_role.name = "Mobile Engineers"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await pm_cog.project_create.callback(
        pm_cog,
        interaction=interaction,
        name="Mobile Redesign",
        prefix="MOB",
        role=mock_role,
        channel=None,
    )

    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.call_args.kwargs.get("embed")
    assert embed is not None
    assert "Mobile Redesign" in embed.title

    # Verify project exists and team is mapped
    project = await proj_srv.get_by_name(guild_id, "Mobile Redesign")
    assert project is not None
    assert project.prefix == "MOB"

    teams = await proj_srv.list_teams_for_project(project.id)
    assert len(teams) == 1
    assert teams[0].discord_role_id == 55667788


@pytest.mark.asyncio
async def test_pm_project_role_and_lead_commands(services):
    """Verify /pm project role (add/remove) and /pm project lead (add/remove)."""
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 9988776655

    pm_cog = PmCog(
        bot=MagicMock(),
        project_service=proj_srv,
        team_service=team_srv,
        task_service=task_srv,
    )

    # 1. Seed project with primary role
    p = await proj_srv.create_project(guild_id=guild_id, name="Cloud Backend", prefix="CLD")
    t1 = await team_srv.create_team(guild_id=guild_id, name="Backend", discord_role_id=1001)
    await proj_srv.assign_team_to_project(p.id, t1.id)

    # 2. Add second role via /pm project role add
    mock_role_qa = MagicMock(spec=discord.Role)
    mock_role_qa.id = 1002
    mock_role_qa.name = "QA Engineers"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.guild_permissions = MagicMock(manage_guild=True, administrator=True)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await pm_cog.project_role.callback(
        pm_cog,
        interaction=interaction,
        project_name="Cloud Backend",
        role=mock_role_qa,
        action="add",
    )

    teams = await proj_srv.list_teams_for_project(p.id)
    assert len(teams) == 2
    role_ids = {t.discord_role_id for t in teams}
    assert 1001 in role_ids
    assert 1002 in role_ids

    # 3. Designate lead via /pm project lead add
    mock_user_lead = MagicMock(spec=discord.Member)
    mock_user_lead.id = 5050
    mock_user_lead.roles = [mock_role_qa]

    await pm_cog.project_lead.callback(
        pm_cog,
        interaction=interaction,
        project_name="Cloud Backend",
        user=mock_user_lead,
        action="add",
    )

    t2 = next(t for t in teams if t.discord_role_id == 1002)
    leads = await team_srv.list_team_leads(t2.id)
    assert 5050 in leads

    # 4. Remove role via /pm project role remove
    await pm_cog.project_role.callback(
        pm_cog,
        interaction=interaction,
        project_name="Cloud Backend",
        role=mock_role_qa,
        action="remove",
    )
    teams_after = await proj_srv.list_teams_for_project(p.id)
    assert len(teams_after) == 1
    assert teams_after[0].discord_role_id == 1001
