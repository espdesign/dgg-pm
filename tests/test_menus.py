from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.views.hub_menu import (
    HubBoardProjectSelectView,
    HubTaskProjectSelectView,
    PmHubView,
    build_hub_welcome_embed,
)
from src.adapters.discord_bot.views.project_menu import (
    ProjectActiveListView,
    ProjectArchiveConfirmView,
    ProjectArchiveSelectView,
    ProjectAssignTeamView,
    ProjectAssignTimelineModal,
    ProjectChannelSelectView,
    ProjectCreateModal,
    ProjectMenuView,
    ProjectRestoreConfirmView,
    ProjectRestoreSelectView,
    ProjectSearchModal,
    build_active_projects_embed,
    build_project_menu_embed,
)
from src.adapters.discord_bot.views.settings_menu import (
    UserSettingsView,
)
from src.adapters.discord_bot.views.task_menu import (
    TaskCreateModal,
    TaskMenuView,
    TaskProjectSearchModal,
    TaskSelectProjectView,
    build_task_board_embed,
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

    # 3b. ProjectCreateModal creates the Control Hub + project tag on a ForumChannel
    mock_forum = MagicMock(spec=discord.ForumChannel)
    mock_forum.id = 37373737
    mock_forum.name = "mobile-dev"
    mock_forum.available_tags = []
    mock_forum.edit = AsyncMock()
    mock_thread = MagicMock()
    mock_thread.id = 42424242
    mock_thread.edit = AsyncMock()
    mock_forum.create_thread = AsyncMock(return_value=mock_thread)

    modal2 = ProjectCreateModal(
        project_service=proj_srv,
        channel=mock_forum,
        team_service=team_srv,
        task_service=services["task"],
    )
    modal2.name_input._value = "Mobile Redesign"
    modal2.prefix_input._value = "MOB"
    modal2.desc_input._value = ""
    modal2.cat_input._value = ""

    interaction2 = MagicMock(spec=discord.Interaction)
    interaction2.guild = MagicMock()
    interaction2.guild.id = guild_id
    interaction2.response = MagicMock()
    interaction2.response.send_message = AsyncMock()

    await modal2.on_submit(interaction2)

    # Hub thread created in the forum
    mock_forum.create_thread.assert_awaited_once()
    assert "Control Hub" in mock_forum.create_thread.call_args.kwargs["name"]
    mock_thread.edit.assert_awaited_once_with(pinned=True)

    # Per-project tag added to the forum
    saved = [
        c.kwargs.get("available_tags", []) for c in mock_forum.edit.await_args_list if "available_tags" in c.kwargs
    ]
    assert any(t.name == "📁 Mobile Redesign" for tags in saved for t in tags)

    # Confirm note surfaced in the embed
    embed2 = interaction2.response.send_message.call_args.kwargs.get("embed")
    bound_field = next(f for f in embed2.fields if f.name == "Bound Channel")
    assert "Pinned Control Hub" in bound_field.value

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
    assert "Designated" in success_embed.description and "Team Lead" in success_embed.description

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

    # 1. Test TaskMenuView and embeds
    view = TaskMenuView(task_srv, proj_srv, team_service=services["team"], projects=[project])
    embed = build_task_menu_embed()
    assert "Task Operations Control Center" in embed.title
    assert len(view.children) == 9

    board_embed = build_task_board_embed([], 0, "Global Scope", "Active", "All")
    assert "Task Board" in board_embed.title
    assert "No Tasks Found" in board_embed.fields[0].name

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
    assert len(hub_view.children) == 6  # New Task, Task Board, Projects, Teams, My Settings, Guides

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = MagicMock()
    mock_interaction.guild.id = 9999999999
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 123456789
    mock_interaction.user.display_name = "testuser"
    mock_interaction.channel = MagicMock()
    mock_interaction.channel.id = 1111111111
    mock_interaction.channel.parent_id = None
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.response.send_modal = AsyncMock()

    # Click New Task (opens modal)
    await hub_view.new_task_btn.callback(mock_interaction)
    mock_interaction.response.send_modal.assert_awaited_once()

    # Switch to projects tab (ephemeral)
    await hub_view.projects_tab.callback(mock_interaction)
    assert mock_interaction.response.send_message.await_count == 1
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    # Switch to tasks tab (ephemeral)
    await hub_view.tasks_tab.callback(mock_interaction)
    assert mock_interaction.response.send_message.await_count == 2
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True

    # Switch to settings tab (ephemeral)
    await hub_view.settings_tab.callback(mock_interaction)
    assert mock_interaction.response.send_message.await_count == 3
    assert mock_interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_pm_hub_multi_project_flows(services):
    """Verify PmHubView in multi-project forums shows project selection for tasks and board."""
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    user_srv = services["user"]
    guild_id = 9988776655
    channel_id = 33445566

    p1 = await proj_srv.create_project(
        guild_id=guild_id,
        name="Project Alpha",
        prefix="ALPH",
        discord_channel_id=channel_id,
    )
    p2 = await proj_srv.create_project(
        guild_id=guild_id,
        name="Project Beta",
        prefix="BETA",
        discord_channel_id=channel_id,
    )

    hub_view = PmHubView(proj_srv, team_srv, task_srv, user_service=user_srv)

    mock_channel = MagicMock(spec=discord.ForumChannel)
    mock_channel.id = channel_id
    mock_channel.name = "multi-forum"

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = MagicMock()
    mock_interaction.guild.id = guild_id
    mock_interaction.user = MagicMock()
    mock_interaction.user.id = 123456789
    mock_interaction.user.display_name = "testuser"
    mock_interaction.channel = mock_channel
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.response.send_modal = AsyncMock()
    mock_interaction.response.edit_message = AsyncMock()

    # 1. Clicking New Task in multi-project forum should send ephemeral HubTaskProjectSelectView
    await hub_view.new_task_btn.callback(mock_interaction)
    mock_interaction.response.send_message.assert_awaited_once()
    send_args = mock_interaction.response.send_message.call_args
    assert send_args.kwargs.get("ephemeral") is True
    picker_view = send_args.kwargs.get("view")
    assert isinstance(picker_view, HubTaskProjectSelectView)
    assert len(picker_view.select.options) == 3  # Alpha, Beta, Standalone

    # 2. Select Project Alpha -> opens TaskCreateModal for Alpha
    picker_view.select._values = [str(p1.id)]
    select_interaction = MagicMock(spec=discord.Interaction)
    select_interaction.response = MagicMock()
    select_interaction.response.send_modal = AsyncMock()
    await picker_view._on_select(select_interaction)
    select_interaction.response.send_modal.assert_awaited_once()
    modal = select_interaction.response.send_modal.call_args.args[0]
    assert isinstance(modal, TaskCreateModal)
    assert modal.project.id == p1.id

    # 3. Select Standalone -> opens TaskCreateModal with project=None
    picker_view.select._values = ["standalone"]
    select_interaction2 = MagicMock(spec=discord.Interaction)
    select_interaction2.response = MagicMock()
    select_interaction2.response.send_modal = AsyncMock()
    await picker_view._on_select(select_interaction2)
    select_interaction2.response.send_modal.assert_awaited_once()
    modal2 = select_interaction2.response.send_modal.call_args.args[0]
    assert isinstance(modal2, TaskCreateModal)
    assert modal2.project is None

    # 4. Clicking Task Board in multi-project forum should send ephemeral HubBoardProjectSelectView
    board_interaction = MagicMock(spec=discord.Interaction)
    board_interaction.guild = MagicMock()
    board_interaction.guild.id = guild_id
    board_interaction.channel = mock_channel
    board_interaction.response = MagicMock()
    board_interaction.response.send_message = AsyncMock()

    await hub_view.tasks_tab.callback(board_interaction)
    board_interaction.response.send_message.assert_awaited_once()
    board_send_args = board_interaction.response.send_message.call_args
    assert board_send_args.kwargs.get("ephemeral") is True
    board_picker_view = board_send_args.kwargs.get("view")
    assert isinstance(board_picker_view, HubBoardProjectSelectView)
    assert len(board_picker_view.select.options) == 3  # All, Alpha, Beta

    # 5. Select Project Beta in board picker -> edits message to TaskMenuView scoped to Beta
    board_picker_view.select._values = [str(p2.id)]
    board_select_interaction = MagicMock(spec=discord.Interaction)
    board_select_interaction.guild = MagicMock()
    board_select_interaction.guild.id = guild_id
    board_select_interaction.response = MagicMock()
    board_select_interaction.response.edit_message = AsyncMock()
    await board_picker_view._on_select(board_select_interaction)
    board_select_interaction.response.edit_message.assert_awaited_once()
    task_view = board_select_interaction.response.edit_message.call_args.kwargs.get("view")
    assert isinstance(task_view, TaskMenuView)
    assert task_view.selected_project_id == p2.id


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


@pytest.mark.asyncio
async def test_project_archive_and_restore_confirmation_flows(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 9995554443

    # 1. Setup project and task
    project = await proj_srv.create_project(
        guild_id=guild_id,
        name="Security Audit",
        prefix="SEC",
        description="Quarterly security audit",
        discord_channel_id=123456,
    )
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Penetration Testing",
        creator_discord_id=1,
        project_id=project.id,
    )
    await task_srv.update_discord_message_ids(task_id=task.id, discord_message_id=111222, discord_thread_id=987654321)

    # 2. Test ProjectMenuView -> Archive Project button opens ProjectArchiveSelectView
    menu_view = ProjectMenuView(proj_srv, team_srv, task_srv)
    archive_btn_interaction = MagicMock(spec=discord.Interaction)
    archive_btn_interaction.guild = MagicMock()
    archive_btn_interaction.guild.id = guild_id
    archive_btn_interaction.response = MagicMock()
    archive_btn_interaction.response.edit_message = AsyncMock()

    await menu_view.archive_btn.callback(archive_btn_interaction)
    archive_btn_interaction.response.edit_message.assert_awaited_once()
    select_view = archive_btn_interaction.response.edit_message.call_args.kwargs["view"]
    assert isinstance(select_view, ProjectArchiveSelectView)

    # 3. Test Selecting project from ProjectArchiveSelectView opens ProjectArchiveConfirmView
    select_view.select._values = [str(project.id)]
    select_interaction = MagicMock(spec=discord.Interaction)
    select_interaction.guild = MagicMock()
    select_interaction.guild.id = guild_id
    select_interaction.response = MagicMock()
    select_interaction.response.edit_message = AsyncMock()

    await select_view._on_select(select_interaction)
    select_interaction.response.edit_message.assert_awaited_once()
    confirm_view = select_interaction.response.edit_message.call_args.kwargs["view"]
    confirm_embed = select_interaction.response.edit_message.call_args.kwargs["embed"]
    assert isinstance(confirm_view, ProjectArchiveConfirmView)
    assert "Confirm Project Archival" in confirm_embed.title
    assert "Security Audit" in confirm_embed.description

    # 4. Test clicking Cancel on ProjectArchiveConfirmView aborts and returns to ProjectMenuView
    cancel_interaction = MagicMock(spec=discord.Interaction)
    cancel_interaction.response = MagicMock()
    cancel_interaction.response.edit_message = AsyncMock()

    await confirm_view.cancel_btn.callback(cancel_interaction)
    cancel_interaction.response.edit_message.assert_awaited_once()
    returned_view = cancel_interaction.response.edit_message.call_args.kwargs["view"]
    assert isinstance(returned_view, ProjectMenuView)

    # Project is still active
    unchanged_proj = await proj_srv.get_by_id(project.id)
    assert unchanged_proj is not None
    assert not unchanged_proj.is_archived

    # 5. Test clicking Confirm Archive on ProjectArchiveConfirmView archives project and syncs threads
    client_mock = MagicMock()
    client_mock.sync_task_thread = AsyncMock()
    confirm_archive_interaction = MagicMock(spec=discord.Interaction)
    confirm_archive_interaction.guild = MagicMock()
    confirm_archive_interaction.guild.id = guild_id
    confirm_archive_interaction.client = client_mock
    confirm_archive_interaction.response = MagicMock()
    confirm_archive_interaction.response.edit_message = AsyncMock()

    await confirm_view.confirm_btn.callback(confirm_archive_interaction)
    confirm_archive_interaction.response.edit_message.assert_awaited_once()
    archived_embed = confirm_archive_interaction.response.edit_message.call_args.kwargs["embed"]
    assert "Project Archived!" in archived_embed.description

    # Project is now archived
    archived_proj = await proj_srv.get_by_id(project.id)
    assert archived_proj is not None
    assert archived_proj.is_archived
    client_mock.sync_task_thread.assert_awaited_once()

    # 6. Test ProjectMenuView -> Restore Project button opens ProjectRestoreSelectView
    restore_btn_interaction = MagicMock(spec=discord.Interaction)
    restore_btn_interaction.guild = MagicMock()
    restore_btn_interaction.guild.id = guild_id
    restore_btn_interaction.response = MagicMock()
    restore_btn_interaction.response.edit_message = AsyncMock()

    await menu_view.restore_btn.callback(restore_btn_interaction)
    restore_btn_interaction.response.edit_message.assert_awaited_once()
    restore_select_view = restore_btn_interaction.response.edit_message.call_args.kwargs["view"]
    assert isinstance(restore_select_view, ProjectRestoreSelectView)

    # 7. Test Selecting project from ProjectRestoreSelectView opens ProjectRestoreConfirmView
    restore_select_view.select._values = [str(project.id)]
    restore_select_interaction = MagicMock(spec=discord.Interaction)
    restore_select_interaction.guild = MagicMock()
    restore_select_interaction.guild.id = guild_id
    restore_select_interaction.response = MagicMock()
    restore_select_interaction.response.edit_message = AsyncMock()

    await restore_select_view._on_select(restore_select_interaction)
    restore_select_interaction.response.edit_message.assert_awaited_once()
    restore_confirm_view = restore_select_interaction.response.edit_message.call_args.kwargs["view"]
    restore_confirm_embed = restore_select_interaction.response.edit_message.call_args.kwargs["embed"]
    assert isinstance(restore_confirm_view, ProjectRestoreConfirmView)
    assert "Confirm Project Restoration" in restore_confirm_embed.title
    assert "Security Audit" in restore_confirm_embed.description

    # 8. Test clicking Cancel on ProjectRestoreConfirmView aborts and returns to ProjectMenuView
    restore_cancel_interaction = MagicMock(spec=discord.Interaction)
    restore_cancel_interaction.response = MagicMock()
    restore_cancel_interaction.response.edit_message = AsyncMock()

    await restore_confirm_view.cancel_btn.callback(restore_cancel_interaction)
    restore_cancel_interaction.response.edit_message.assert_awaited_once()
    assert isinstance(restore_cancel_interaction.response.edit_message.call_args.kwargs["view"], ProjectMenuView)

    # Project is still archived
    still_archived_proj = await proj_srv.get_by_id(project.id)
    assert still_archived_proj.is_archived

    # 9. Test clicking Confirm Restore on ProjectRestoreConfirmView reactivates project
    client_mock.reset_mock()
    confirm_restore_interaction = MagicMock(spec=discord.Interaction)
    confirm_restore_interaction.guild = MagicMock()
    confirm_restore_interaction.guild.id = guild_id
    confirm_restore_interaction.client = client_mock
    confirm_restore_interaction.response = MagicMock()
    confirm_restore_interaction.response.edit_message = AsyncMock()

    await restore_confirm_view.confirm_btn.callback(confirm_restore_interaction)
    confirm_restore_interaction.response.edit_message.assert_awaited_once()
    restored_embed = confirm_restore_interaction.response.edit_message.call_args.kwargs["embed"]
    assert "Project Restored!" in restored_embed.description

    # Project is reactivated
    restored_proj = await proj_srv.get_by_id(project.id)
    assert not restored_proj.is_archived
    client_mock.sync_task_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_search_and_pagination_flows(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 9991112233

    # 1. Create 30 projects for testing pagination (> 25 items)
    created_projects = []
    for i in range(1, 31):
        p = await proj_srv.create_project(
            guild_id=guild_id,
            name=f"Project Alpha {i:02d}",
            prefix=f"P{i:02d}",
            description=f"Description for project {i}",
        )
        created_projects.append(p)

    # 2. Test ProjectActiveListView pagination
    active_view = ProjectActiveListView(
        projects=created_projects,
        project_service=proj_srv,
        team_service=team_srv,
        task_service=task_srv,
        page_size=8,
    )
    # 30 items / 8 per page = 4 pages
    assert active_view.current_page == 0
    embed = build_active_projects_embed(created_projects, 0, len(created_projects), page_size=8)
    assert "Active Projects (30)" in embed.title
    assert len(embed.fields) == 8
    assert "Project Alpha 01" in embed.fields[0].name

    # Next page callback
    next_interaction = MagicMock(spec=discord.Interaction)
    next_interaction.response = MagicMock()
    next_interaction.response.edit_message = AsyncMock()
    await active_view._on_next_clicked(next_interaction)
    next_interaction.response.edit_message.assert_awaited_once()
    assert active_view.current_page == 1

    # Prev page callback
    prev_interaction = MagicMock(spec=discord.Interaction)
    prev_interaction.response = MagicMock()
    prev_interaction.response.edit_message = AsyncMock()
    await active_view._on_prev_clicked(prev_interaction)
    prev_interaction.response.edit_message.assert_awaited_once()
    assert active_view.current_page == 0

    # 3. Test Search in ProjectActiveListView and ProjectSearchModal
    search_cb_mock = AsyncMock()
    modal = ProjectSearchModal(on_search_callback=search_cb_mock, current_query="Alpha")
    modal.query_input._value = "Alpha 12"
    modal_interaction = MagicMock(spec=discord.Interaction)
    await modal.on_submit(modal_interaction)
    search_cb_mock.assert_awaited_once_with(modal_interaction, "Alpha 12")

    search_interaction = MagicMock(spec=discord.Interaction)
    search_interaction.response = MagicMock()
    search_interaction.response.edit_message = AsyncMock()
    await active_view._apply_search(search_interaction, query="Alpha 12")
    search_interaction.response.edit_message.assert_awaited_once()
    search_embed = search_interaction.response.edit_message.call_args.kwargs["embed"]
    assert "Filter: `Alpha 12`" in search_embed.title
    assert len(search_embed.fields) == 1
    assert "Project Alpha 12" in search_embed.fields[0].name

    # Clear search filter
    clear_interaction = MagicMock(spec=discord.Interaction)
    clear_interaction.response = MagicMock()
    clear_interaction.response.edit_message = AsyncMock()
    await active_view._on_clear_filter_clicked(clear_interaction)
    clear_interaction.response.edit_message.assert_awaited_once()
    cleared_embed = clear_interaction.response.edit_message.call_args.kwargs["embed"]
    assert len(cleared_embed.fields) == 8

    # 4. Test ProjectArchiveSelectView with 30 items
    archive_select_view = ProjectArchiveSelectView(
        projects=created_projects,
        project_service=proj_srv,
        team_service=team_srv,
        task_service=task_srv,
    )
    # Page 0 has 25 items (max select options)
    assert len(archive_select_view.select.options) == 25
    assert archive_select_view.current_page == 0

    # Next page switch in archive select view
    archive_next_interaction = MagicMock(spec=discord.Interaction)
    archive_next_interaction.response = MagicMock()
    archive_next_interaction.response.edit_message = AsyncMock()
    await archive_select_view._on_next_clicked(archive_next_interaction)
    archive_next_interaction.response.edit_message.assert_awaited_once()
    assert archive_select_view.current_page == 1
    assert len(archive_select_view.select.options) == 5  # remaining 5 items

    # Search in archive select view
    archive_search_interaction = MagicMock(spec=discord.Interaction)
    archive_search_interaction.response = MagicMock()
    archive_search_interaction.response.edit_message = AsyncMock()
    await archive_select_view._apply_search(archive_search_interaction, query="P29")
    archive_search_interaction.response.edit_message.assert_awaited_once()
    assert len(archive_select_view.select.options) == 1
    assert "P29" in archive_select_view.select.options[0].label

    # 5. Test ProjectRestoreSelectView with 30 archived items
    for p in created_projects:
        await proj_srv.archive_project(p.id)

    archived_list = await proj_srv.list_projects(guild_id, include_archived=True)
    archived_projects = [p for p in archived_list if p.is_archived]
    assert len(archived_projects) == 30

    restore_select_view = ProjectRestoreSelectView(
        projects=archived_projects,
        project_service=proj_srv,
        team_service=team_srv,
        task_service=task_srv,
    )
    assert len(restore_select_view.select.options) == 25
    assert restore_select_view.current_page == 0

    # Next page in restore select view
    restore_next_interaction = MagicMock(spec=discord.Interaction)
    restore_next_interaction.response = MagicMock()
    restore_next_interaction.response.edit_message = AsyncMock()
    await restore_select_view._on_next_clicked(restore_next_interaction)
    restore_next_interaction.response.edit_message.assert_awaited_once()
    assert restore_select_view.current_page == 1
    assert len(restore_select_view.select.options) == 5

    # Search in restore select view
    restore_search_interaction = MagicMock(spec=discord.Interaction)
    restore_search_interaction.response = MagicMock()
    restore_search_interaction.response.edit_message = AsyncMock()
    await restore_select_view._apply_search(restore_search_interaction, query="Alpha 07")
    restore_search_interaction.response.edit_message.assert_awaited_once()
    assert len(restore_select_view.select.options) == 1
    assert "Project Alpha 07" in restore_select_view.select.options[0].label


@pytest.mark.asyncio
async def test_task_menu_channel_scoping_and_global_search(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 999333444

    # 1. Setup two projects, one bound to channel 12345
    proj_a = await proj_srv.create_project(
        guild_id=guild_id,
        name="Mobile iOS",
        prefix="IOS",
        discord_channel_id=12345,
    )
    proj_b = await proj_srv.create_project(
        guild_id=guild_id,
        name="Backend Microservices",
        prefix="BACK",
        discord_channel_id=67890,
    )
    all_projects = [proj_a, proj_b]

    # Create tasks for proj_a
    await task_srv.create_task(
        guild_id=guild_id,
        title="SwiftUI Navigation Flow",
        creator_discord_id=1,
        project_id=proj_a.id,
    )

    # 2. Test opening TaskMenuView in channel 12345 (channel-bound to proj_a)
    view_channel = TaskMenuView(
        task_service=task_srv,
        project_service=proj_srv,
        team_service=team_srv,
        projects=all_projects,
        current_channel_id=12345,
    )
    # Verify default scope is automatically proj_a
    assert view_channel.selected_project_id == proj_a.id
    assert view_channel.new_task_btn.label == "New Task [IOS]"

    # Verify channel project is marked with "📍 (This Channel)"
    this_chan_option = next((opt for opt in view_channel.project_select.options if opt.value == str(proj_a.id)), None)
    assert this_chan_option is not None
    assert "📍" in this_chan_option.label
    assert this_chan_option.default is True

    # 3. Test opening TaskMenuView in an unbound channel (99999) -> defaults to Global Scope
    view_unbound = TaskMenuView(
        task_service=task_srv,
        project_service=proj_srv,
        team_service=team_srv,
        projects=all_projects,
        current_channel_id=99999,
    )
    assert view_unbound.selected_project_id is None
    global_option = next((opt for opt in view_unbound.project_select.options if opt.value == "all"), None)
    assert global_option is not None
    assert global_option.default is True

    # 4. Test TaskProjectSearchModal submission and scope switching
    search_cb_mock = AsyncMock()
    modal = TaskProjectSearchModal(on_search_callback=search_cb_mock, current_query="")
    modal.query_input._value = "Backend"
    modal_interaction = MagicMock(spec=discord.Interaction)
    await modal.on_submit(modal_interaction)
    search_cb_mock.assert_awaited_once_with(modal_interaction, "Backend")

    # Apply search in view_unbound to switch scope to proj_b
    search_interaction = MagicMock(spec=discord.Interaction)
    search_interaction.guild = MagicMock()
    search_interaction.guild.id = guild_id
    search_interaction.response = MagicMock()
    search_interaction.response.edit_message = AsyncMock()

    await view_unbound._apply_scope_search(search_interaction, query="Backend")
    search_interaction.response.edit_message.assert_awaited_once()
    assert view_unbound.selected_project_id == proj_b.id
    assert view_unbound.new_task_btn.label == "New Task [BACK]"

    # 5. Test clicking New Project Task when scoped to a project opens TaskCreateModal directly
    new_task_interaction = MagicMock(spec=discord.Interaction)
    new_task_interaction.guild = MagicMock()
    new_task_interaction.guild.id = guild_id
    new_task_interaction.response = MagicMock()
    new_task_interaction.response.send_modal = AsyncMock()

    await view_unbound._on_new_task_clicked(new_task_interaction)
    new_task_interaction.response.send_modal.assert_awaited_once()
    created_modal = new_task_interaction.response.send_modal.call_args.args[0]
    assert isinstance(created_modal, TaskCreateModal)
    assert created_modal.project.id == proj_b.id

    # 6. Test TaskSelectProjectView search and pagination
    select_view = TaskSelectProjectView(
        projects=all_projects,
        task_service=task_srv,
        project_service=proj_srv,
        team_service=team_srv,
        current_channel_id=12345,
    )
    # Channel project is sorted first
    assert select_view.select.options[0].value == str(proj_a.id)
    assert "📍" in select_view.select.options[0].label

    # Search in TaskSelectProjectView
    filter_interaction = MagicMock(spec=discord.Interaction)
    filter_interaction.response = MagicMock()
    filter_interaction.response.edit_message = AsyncMock()
    await select_view._apply_search(filter_interaction, query="Backend")
    filter_interaction.response.edit_message.assert_awaited_once()
    assert len(select_view.select.options) == 1
    assert select_view.select.options[0].value == str(proj_b.id)
