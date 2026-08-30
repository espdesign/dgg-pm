from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed
from src.adapters.discord_bot.views.project_menu import (
    ProjectCreateModal,
    ProjectMenuView,
    build_project_menu_embed,
)
from src.adapters.discord_bot.views.task_menu import (
    TaskCreateModal,
    TaskMenuView,
    build_task_menu_embed,
)
from src.adapters.discord_bot.views.team_menu import (
    TeamCreateModalWithName,
    TeamCreateRoleSelectView,
    TeamMenuView,
    build_team_menu_embed,
)
from src.domain.enums import PriorityLevel


@pytest.mark.asyncio
async def test_project_menu_and_modal(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    guild_id = 9999999999

    # 1. Test ProjectMenuView and embed
    view = ProjectMenuView(proj_srv, team_srv)
    embed = build_project_menu_embed()
    assert "Project Management Control Center" in embed.title
    assert len(view.children) == 4  # New Project, Active Projects, Archive, Restore

    # 2. Test ProjectCreateModal submission
    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 123456789

    modal = ProjectCreateModal(project_service=proj_srv, channel=mock_channel)
    modal.name_input._value = "Cloud Infrastructure"
    modal.prefix_input._value = "CLD"
    modal.desc_input._value = "AWS & Kubernetes migration"
    modal.cat_input._value = "DevOps"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)
    interaction.response.send_message.assert_awaited_once()

    created_proj = await proj_srv.get_by_name(guild_id, "Cloud Infrastructure")
    assert created_proj is not None
    assert created_proj.prefix == "CLD"
    assert created_proj.discord_channel_id == 123456789


@pytest.mark.asyncio
async def test_team_menu_and_modal(services):
    team_srv = services["team"]
    guild_id = 8888888888

    # 1. Test TeamMenuView and embed
    view = TeamMenuView(team_srv)
    embed = build_team_menu_embed()
    assert "Team Management Control Center" in embed.title
    assert len(view.children) == 3  # Create Team, Assign Member, Team Roster

    # 2. Test TeamCreateRoleSelectView
    role_view = TeamCreateRoleSelectView(team_srv)
    assert len(role_view.children) == 1

    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 555666777
    mock_role.name = "Site Reliability"
    role_view.role_select._values = [mock_role]

    select_interaction = MagicMock(spec=discord.Interaction)
    select_interaction.response = MagicMock()
    select_interaction.response.send_modal = AsyncMock()
    await role_view._on_role_selected(select_interaction)
    select_interaction.response.send_modal.assert_awaited_once()

    # 3. Test TeamCreateModalWithName submission
    modal = TeamCreateModalWithName(team_service=team_srv, selected_role=mock_role)
    assert modal.name_input.default == "Site Reliability"
    modal.name_input._value = "Site Reliability Engineering"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)
    interaction.response.send_message.assert_awaited_once()

    created_team = await team_srv.get_by_name(guild_id, "Site Reliability Engineering")
    assert created_team is not None
    assert created_team.discord_role_id == 555666777

    # 4. Test TeamAssignMemberSelectView (Case A: User missing team role)
    from src.adapters.discord_bot.views.team_menu import TeamAssignMemberSelectView

    assign_view = TeamAssignMemberSelectView(teams=[created_team], team_service=team_srv)
    assert len(assign_view.children) == 4  # Team, User, Role, Confirm Button

    mock_member_no_role = MagicMock(spec=discord.Member)
    mock_member_no_role.id = 3001
    mock_member_no_role.roles = []

    assign_view.user_select._values = [mock_member_no_role]
    assign_interaction = MagicMock(spec=discord.Interaction)
    assign_interaction.guild = MagicMock()
    assign_interaction.guild.id = guild_id
    assign_interaction.guild.get_member.return_value = mock_member_no_role
    assign_interaction.response = MagicMock()
    assign_interaction.response.defer = AsyncMock()
    assign_interaction.response.send_message = AsyncMock()

    await assign_view._on_user_selected(assign_interaction)
    await assign_view.confirm_btn.callback(assign_interaction)
    assign_interaction.response.send_message.assert_awaited_once()
    msg = assign_interaction.response.send_message.call_args[0][0]
    assert "is not part of team" in msg

    # Case B: User has team role, select lead role and confirm
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 555666777
    mock_member_with_role = MagicMock(spec=discord.Member)
    mock_member_with_role.id = 3002
    mock_member_with_role.roles = [mock_role]

    assign_view.user_select._values = [mock_member_with_role]
    assign_view.role_select._values = ["lead"]
    assign_interaction.guild.get_member.return_value = mock_member_with_role
    assign_interaction.response.send_message.reset_mock()

    await assign_view._on_user_selected(assign_interaction)
    await assign_view._on_role_selected(assign_interaction)
    await assign_view.confirm_btn.callback(assign_interaction)
    assign_interaction.response.send_message.assert_awaited_once()
    success_msg = assign_interaction.response.send_message.call_args[0][0]
    assert "Assigned <@3002> as **Team Lead ⭐**" in success_msg

    # 5. Test TeamRosterDetailView
    from src.adapters.discord_bot.views.team_menu import TeamRosterDetailView

    roster_view = TeamRosterDetailView(teams=[created_team], team_service=team_srv)
    roster_view.select._values = [str(created_team.id)]

    roster_interaction = MagicMock(spec=discord.Interaction)
    roster_interaction.response = MagicMock()
    roster_interaction.response.send_message = AsyncMock()

    await roster_view._on_select_team(roster_interaction)
    roster_interaction.response.send_message.assert_awaited_once()
    roster_embed = roster_interaction.response.send_message.call_args[1]["embed"]
    assert "Site Reliability Engineering" in roster_embed.title


@pytest.mark.asyncio
async def test_task_menu_and_modal(services):
    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 7777777777

    project = await proj_srv.create_project(guild_id=guild_id, name="Security Ops", prefix="SEC")

    # 1. Test TaskMenuView and embed
    view = TaskMenuView(task_srv, proj_srv)
    embed = build_task_menu_embed()
    assert "Task Operations Control Center" in embed.title
    assert len(view.children) == 4  # New Project Task, Standalone, Refresh, Status Filter

    # 2. Test TaskCreateModal submission
    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.id = 987654321
    mock_channel.send = AsyncMock()
    mock_msg = MagicMock()
    mock_msg.id = 111222333
    mock_msg.create_thread = AsyncMock()
    mock_thread = MagicMock()
    mock_thread.id = 444555666
    mock_msg.create_thread.return_value = mock_thread
    mock_channel.send.return_value = mock_msg

    modal = TaskCreateModal(task_service=task_srv, project=project, target_channel=mock_channel)
    modal.title_input._value = "Zero-Trust Network Setup"
    modal.desc_input._value = "Configure Tailscale mesh and ACLs"
    modal.due_input._value = "tomorrow 5pm"
    modal.assignee_input._value = "<@1002>"
    modal.priority_input._value = "high"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock()
    interaction.guild.id = guild_id
    interaction.user = MagicMock()
    interaction.user.id = 1001
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await modal.on_submit(interaction)
    interaction.response.send_message.assert_awaited_once()

    tasks, total = await task_srv.list_tasks(guild_id=guild_id, project_id=project.id)
    assert total == 1
    t = tasks[0]
    assert t.title == "Zero-Trust Network Setup"
    assert t.priority == PriorityLevel.HIGH
    assert t.assignee_discord_id == 1002
    assert t.due_at is not None


@pytest.mark.asyncio
async def test_pm_hub_navigation(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]

    hub_view = PmHubView(proj_srv, team_srv, task_srv)
    welcome_embed = build_hub_welcome_embed()
    assert "Control Hub" in welcome_embed.title
    assert len(hub_view.children) == 4  # Projects, Teams, Tasks, Guides

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.response = MagicMock()
    mock_interaction.response.edit_message = AsyncMock()

    # Switch to projects tab
    await hub_view.projects_tab.callback(mock_interaction)
    mock_interaction.response.edit_message.assert_awaited_once()

    # Switch to tasks tab
    await hub_view.tasks_tab.callback(mock_interaction)
    assert mock_interaction.response.edit_message.await_count == 2
