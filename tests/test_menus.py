from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed
from src.adapters.discord_bot.views.project_menu import (
    ProjectAssignTeamView,
    ProjectAssignTimelineModal,
    ProjectChannelSelectView,
    ProjectCreateModal,
    ProjectMenuView,
    build_project_menu_embed,
)
from src.adapters.discord_bot.views.settings_menu import (
    UserSettingsView,
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
from src.domain.enums import PriorityLevel, TaskStatus


@pytest.mark.asyncio
async def test_project_menu_and_modal(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    guild_id = 9999999999

    # 1. Test ProjectMenuView and embed
    view = ProjectMenuView(proj_srv, team_srv, task_service=services["task"])
    embed = build_project_menu_embed()
    assert "Project Management Control Center" in embed.title
    assert len(view.children) == 6  # New Project, Active Projects, Assign Team, Archive, Restore, PM Main Menu

    # Test clicking New Project opens ProjectChannelSelectView
    new_proj_interaction = MagicMock(spec=discord.Interaction)
    new_proj_interaction.guild = MagicMock()
    new_proj_interaction.response = MagicMock()
    new_proj_interaction.response.edit_message = AsyncMock()
    await view.new_project_btn.callback(new_proj_interaction)
    new_proj_interaction.response.edit_message.assert_awaited_once()
    called_view = new_proj_interaction.response.edit_message.call_args.kwargs.get("view")
    assert isinstance(called_view, ProjectChannelSelectView)

    # 2. Test ProjectChannelSelectView callbacks
    chan_select_view = ProjectChannelSelectView(proj_srv, team_srv, services["task"])
    mock_forum_channel = MagicMock(spec=discord.ForumChannel)
    mock_forum_channel.id = 555666777

    # Select channel from dropdown
    chan_select_view.channel_select._values = [mock_forum_channel]
    select_interaction = MagicMock(spec=discord.Interaction)
    select_interaction.guild = MagicMock()
    select_interaction.guild.get_channel = MagicMock(return_value=mock_forum_channel)
    select_interaction.response = MagicMock()
    select_interaction.response.send_modal = AsyncMock()
    await chan_select_view._on_channel_selected(select_interaction)
    select_interaction.response.send_modal.assert_awaited_once()
    sent_modal = select_interaction.response.send_modal.call_args.args[0]
    assert isinstance(sent_modal, ProjectCreateModal)
    assert sent_modal.channel == mock_forum_channel

    # 3. Test ProjectCreateModal submission
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

    # 4. Test Assign Team Flow (ProjectAssignTeamView & ProjectAssignTimelineModal)
    team = await team_srv.create_team(guild_id=guild_id, name="DevOps Squad", discord_role_id=987654)
    projects = [created_proj]
    teams = [team]

    assign_view = ProjectAssignTeamView(projects, teams, proj_srv, team_srv, services["task"])
    assert len(assign_view.proj_select.options) == 1
    assert len(assign_view.team_select.options) == 1

    # Test quick assign
    quick_interaction = MagicMock(spec=discord.Interaction)
    quick_interaction.response = MagicMock()
    quick_interaction.response.edit_message = AsyncMock()
    await assign_view._on_assign_quick_clicked(quick_interaction)
    quick_interaction.response.edit_message.assert_awaited_once()

    # Test timeline modal assign
    timeline_modal = ProjectAssignTimelineModal(
        project_service=proj_srv,
        project=created_proj,
        team=team,
        team_service=team_srv,
        task_service=services["task"],
    )
    timeline_modal.timeline_input._value = "Q3 2026 (4 sprints)"
    modal_interaction = MagicMock(spec=discord.Interaction)
    modal_interaction.response = MagicMock()
    modal_interaction.response.edit_message = AsyncMock()
    await timeline_modal.on_submit(modal_interaction)
    modal_interaction.response.edit_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_team_menu_and_modal(services):
    team_srv = services["team"]
    guild_id = 8888888888

    # 1. Test TeamMenuView and embed
    view = TeamMenuView(team_srv, project_service=services["project"], task_service=services["task"])
    embed = build_team_menu_embed()
    assert "Team Management Control Center" in embed.title
    assert len(view.children) == 4  # Create Team, Assign Member, Team Roster, PM Main Menu

    # Test clicking PM Main Menu
    main_menu_interaction = MagicMock(spec=discord.Interaction)
    main_menu_interaction.response = MagicMock()
    main_menu_interaction.response.edit_message = AsyncMock()
    await view._on_hub_clicked(main_menu_interaction)
    main_menu_interaction.response.edit_message.assert_awaited_once()

    # 2. Test TeamCreateRoleSelectView
    role_view = TeamCreateRoleSelectView(team_srv)
    assert len(role_view.children) == 2  # Role Select + Back Button

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
    assert len(assign_view.children) == 5  # Team, User, Role, Confirm, Back

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
    assign_interaction.response.edit_message = AsyncMock()

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

    await assign_view._on_user_selected(assign_interaction)
    await assign_view._on_role_selected(assign_interaction)
    await assign_view.confirm_btn.callback(assign_interaction)
    assign_interaction.response.edit_message.assert_awaited_once()
    success_embed = assign_interaction.response.edit_message.call_args[1]["embed"]
    assert "Assignment Successful!" in success_embed.description

    # 5. Test TeamRosterDetailView
    from src.adapters.discord_bot.views.team_menu import TeamRosterDetailView

    roster_view = TeamRosterDetailView(teams=[created_team], team_service=team_srv)
    assert len(roster_view.children) == 2  # Team Select + Back Button
    roster_view.select._values = [str(created_team.id)]

    roster_interaction = MagicMock(spec=discord.Interaction)
    roster_interaction.response = MagicMock()
    roster_interaction.response.edit_message = AsyncMock()

    await roster_view._on_select_team(roster_interaction)
    roster_interaction.response.edit_message.assert_awaited_once()
    roster_embed = roster_interaction.response.edit_message.call_args[1]["embed"]
    assert "Site Reliability Engineering" in roster_embed.title


@pytest.mark.asyncio
async def test_task_menu_and_modal(services):
    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 7777777777

    project = await proj_srv.create_project(guild_id=guild_id, name="Security Ops", prefix="SEC")

    # 1. Test TaskMenuView and embed
    view = TaskMenuView(task_srv, proj_srv, team_service=services["team"], projects=[project])
    embed = build_task_menu_embed()
    assert "Task Operations Control Center" in embed.title
    assert len(view.children) == 8  # New, Standalone, Reset, PM Main Menu, Project, Status, Assignee, Clear Member

    # Test project filter callback
    project_interaction = MagicMock(spec=discord.Interaction)
    project_interaction.guild = MagicMock()
    project_interaction.guild.id = guild_id
    project_interaction.response = MagicMock()
    project_interaction.response.edit_message = AsyncMock()
    view.project_select._values = [str(project.id)]
    await view._on_project_filter_changed(project_interaction)
    project_interaction.response.edit_message.assert_awaited_once()
    assert view.selected_project_id == project.id

    # Test status filter callback
    status_interaction = MagicMock(spec=discord.Interaction)
    status_interaction.guild = MagicMock()
    status_interaction.guild.id = guild_id
    status_interaction.response = MagicMock()
    status_interaction.response.edit_message = AsyncMock()
    view.status_select._values = ["inProgress"]
    await view._on_status_filter_changed(status_interaction)
    status_interaction.response.edit_message.assert_awaited_once()
    assert view.selected_status == TaskStatus.IN_PROGRESS

    # Test assignee filter callback
    mock_filter_user = MagicMock(spec=discord.Member)
    mock_filter_user.id = 1002
    assignee_interaction = MagicMock(spec=discord.Interaction)
    assignee_interaction.guild = MagicMock()
    assignee_interaction.guild.id = guild_id
    assignee_interaction.response = MagicMock()
    assignee_interaction.response.edit_message = AsyncMock()
    view.assignee_select._values = [mock_filter_user]
    await view._on_assignee_filter_changed(assignee_interaction)
    assignee_interaction.response.edit_message.assert_awaited_once()
    assert view.selected_assignee_id == 1002

    # Test clicking PM Main Menu
    main_menu_interaction = MagicMock(spec=discord.Interaction)
    main_menu_interaction.response = MagicMock()
    main_menu_interaction.response.edit_message = AsyncMock()
    await view._on_hub_clicked(main_menu_interaction)
    main_menu_interaction.response.edit_message.assert_awaited_once()

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
    user_srv = services["user"]

    hub_view = PmHubView(proj_srv, team_srv, task_srv, user_service=user_srv)
    welcome_embed = build_hub_welcome_embed()
    assert "Control Hub" in welcome_embed.title
    assert len(hub_view.children) == 5  # Projects, Teams, Tasks, My Settings, Guides

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = MagicMock()
    mock_interaction.guild.id = 9999999999
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 123456789
    mock_interaction.user.display_name = "testuser"
    mock_interaction.response = MagicMock()
    mock_interaction.response.edit_message = AsyncMock()

    # Switch to projects tab
    await hub_view.projects_tab.callback(mock_interaction)
    mock_interaction.response.edit_message.assert_awaited_once()

    # Switch to tasks tab
    await hub_view.tasks_tab.callback(mock_interaction)
    assert mock_interaction.response.edit_message.await_count == 2

    # Switch to settings tab
    await hub_view.settings_tab.callback(mock_interaction)
    assert mock_interaction.response.edit_message.await_count == 3


@pytest.mark.asyncio
async def test_user_settings_menu_and_toggle(services):
    user_srv = services["user"]
    guild_id = 9999999999
    from src.domain.enums import NotificationPreference

    view = UserSettingsView(
        user_service=user_srv,
        current_pref=NotificationPreference.DM,
        project_service=services["project"],
        team_service=services["team"],
        task_service=services["task"],
    )
    assert len(view.children) == 6  # 4 prefs + 1 test + 1 back

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = MagicMock()
    mock_interaction.guild.id = guild_id
    mock_interaction.guild.name = "Test Guild"
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 777888
    mock_interaction.user.display_name = "Alice"
    mock_interaction.user.send = AsyncMock()
    mock_interaction.response = MagicMock()
    mock_interaction.response.edit_message = AsyncMock()
    mock_interaction.response.send_message = AsyncMock()

    # 1. Click Channel Ping preference
    await view._on_pref_clicked(mock_interaction, NotificationPreference.CHANNEL)
    mock_interaction.response.edit_message.assert_awaited_once()

    pref = await user_srv.get_preference(guild_id, 777888)
    assert pref == NotificationPreference.CHANNEL

    # 2. Click Test Notification button
    await view._on_test_clicked(mock_interaction)
    mock_interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_menu_and_list_excludes_completed_by_default(services):
    proj_srv = services["project"]
    task_srv = services["task"]
    guild_id = 9991234567

    p = await proj_srv.create_project(guild_id=guild_id, name="Core Board", prefix="CRB")
    await task_srv.create_task(guild_id=guild_id, title="Active 1", creator_discord_id=1, project_id=p.id)
    await task_srv.create_task(guild_id=guild_id, title="Active 2", creator_discord_id=1, project_id=p.id)
    t3 = await task_srv.create_task(guild_id=guild_id, title="Done 1", creator_discord_id=1, project_id=p.id)
    await task_srv.update_status(
        task_id=t3.id, new_status=TaskStatus.COMPLETED, expected_version=t3.version, actor_discord_id=1
    )

    # 1. Default list_tasks with exclude_completed=True
    active_tasks, total = await task_srv.list_tasks(guild_id=guild_id, exclude_completed=True)
    assert total == 2
    titles = [t.title for t in active_tasks]
    assert "Active 1" in titles
    assert "Active 2" in titles
    assert "Done 1" not in titles

    # 2. list_tasks with exclude_completed=False
    _, total_all = await task_srv.list_tasks(guild_id=guild_id, exclude_completed=False)
    assert total_all == 3

    # 3. list_tasks with status=TaskStatus.COMPLETED
    completed_tasks, total_completed = await task_srv.list_tasks(guild_id=guild_id, status=TaskStatus.COMPLETED)
    assert total_completed == 1
    assert completed_tasks[0].title == "Done 1"
