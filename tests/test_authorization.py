from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.adapters.discord_bot.bot import DggPmBot
from src.adapters.discord_bot.cogs.task_cog import TaskCog
from src.adapters.discord_bot.cogs.team_cog import TeamCog
from src.adapters.discord_bot.views.task_modals import TaskEditModal, TaskNoteModal
from src.domain.enums import TeamRoleType
from src.domain.exceptions import PermissionDeniedError
from src.services.auth_service import AuthService


def _make_mock_member(
    user_id: int,
    role_ids: list[int] | None = None,
    manage_guild: bool = False,
    administrator: bool = False,
) -> MagicMock:
    """Helper to create a discord.Member mock with permissions and roles."""
    member = MagicMock(spec=discord.Member)
    member.id = user_id

    # Roles
    role_mocks = []
    for rid in role_ids or []:
        r = MagicMock(spec=discord.Role)
        r.id = rid
        role_mocks.append(r)
    member.roles = role_mocks

    # Permissions
    perms = MagicMock()
    perms.manage_guild = manage_guild
    perms.administrator = administrator
    member.guild_permissions = perms

    return member


@pytest.mark.asyncio
async def test_auth_service_server_manager_bypass(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)

    guild_id = 9990001
    project = await proj_srv.create_project(guild_id=guild_id, name="Project Alpha", prefix="ALP")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Admin Test Task",
        creator_discord_id=1001,
        assignee_discord_id=1002,
        project_id=project.id,
    )

    admin_member = _make_mock_member(9999, manage_guild=True)
    assert auth_srv.is_server_manager(admin_member) is True
    assert await auth_srv.can_mutate_task(admin_member, task) is True
    assert await auth_srv.can_create_task_in_project(admin_member, project.id) is True


@pytest.mark.asyncio
async def test_auth_service_task_assignee_and_creator(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)

    guild_id = 9990002
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Creator Assignee Task",
        creator_discord_id=1001,
        assignee_discord_id=1002,
        project_id=None,
    )

    creator = _make_mock_member(1001)
    assignee = _make_mock_member(1002)
    random_user = _make_mock_member(1003)

    assert await auth_srv.can_mutate_task(creator, task) is True
    assert await auth_srv.can_mutate_task(assignee, task) is True
    assert await auth_srv.can_mutate_task(random_user, task) is False


@pytest.mark.asyncio
async def test_auth_service_project_team_role_scoping(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)

    guild_id = 9990003
    team_role_id = 888801
    team = await team_srv.create_team(guild_id=guild_id, name="Core Devs", discord_role_id=team_role_id)
    project = await proj_srv.create_project(guild_id=guild_id, name="Platform V2", prefix="PLT")
    await proj_srv.assign_team_to_project(project_id=project.id, team_id=team.id)

    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Implement gRPC Gateway",
        creator_discord_id=1001,
        project_id=project.id,
    )

    team_member = _make_mock_member(2001, role_ids=[team_role_id])
    outsider = _make_mock_member(2002, role_ids=[999999])

    # Team member with role is authorized to create and mutate
    assert await auth_srv.can_create_task_in_project(team_member, project.id) is True
    assert await auth_srv.can_mutate_task(team_member, task) is True

    # Outsider without role is rejected
    assert await auth_srv.can_create_task_in_project(outsider, project.id) is False
    assert await auth_srv.can_mutate_task(outsider, task) is False


@pytest.mark.asyncio
async def test_auth_service_strict_default_for_unassigned_project(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)

    guild_id = 9990004
    project = await proj_srv.create_project(guild_id=guild_id, name="Secret Lab", prefix="SEC")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Unassigned Project Task",
        creator_discord_id=1001,
        assignee_discord_id=1002,
        project_id=project.id,
    )

    random_member = _make_mock_member(3001)
    admin_member = _make_mock_member(3002, manage_guild=True)

    # Random member cannot create or mutate
    assert await auth_srv.can_create_task_in_project(random_member, project.id) is False
    assert await auth_srv.can_mutate_task(random_member, task) is False

    # Server manager can create and mutate
    assert await auth_srv.can_create_task_in_project(admin_member, project.id) is True
    assert await auth_srv.can_mutate_task(admin_member, task) is True


@pytest.mark.asyncio
async def test_team_lead_roster_management(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    auth_srv = AuthService(proj_srv, team_srv)

    guild_id = 9990005
    team = await team_srv.create_team(guild_id=guild_id, name="Security Team", discord_role_id=555111)

    lead_id = 4001
    regular_id = 4002
    outsider_id = 4003

    await team_srv.assign_member(team_id=team.id, user_discord_id=lead_id, role_type=TeamRoleType.LEAD)
    await team_srv.assign_member(team_id=team.id, user_discord_id=regular_id, role_type=TeamRoleType.MEMBER)

    lead_member = _make_mock_member(lead_id, role_ids=[555111])
    regular_member = _make_mock_member(regular_id, role_ids=[555111])
    outsider_member = _make_mock_member(outsider_id, role_ids=[])
    admin_member = _make_mock_member(9999, manage_guild=True)

    # Team lead can manage roster
    assert await auth_srv.can_manage_team_roster(lead_member, team.id) is True
    # Server manager can manage roster
    assert await auth_srv.can_manage_team_roster(admin_member, team.id) is True
    # Regular team member cannot manage roster
    assert await auth_srv.can_manage_team_roster(regular_member, team.id) is False
    # Outsider cannot manage roster
    assert await auth_srv.can_manage_team_roster(outsider_member, team.id) is False


@pytest.mark.asyncio
async def test_team_lead_cog_enforcement(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)
    guild_id = 9990006

    bot = MagicMock()
    team_cog = TeamCog(
        bot=bot,
        team_service=team_srv,
        project_service=proj_srv,
        task_service=task_srv,
        auth_service=auth_srv,
    )

    team = await team_srv.create_team(guild_id=guild_id, name="DevOps", discord_role_id=777888)
    lead_id = 5001
    await team_srv.add_team_lead(team_id=team.id, user_discord_id=lead_id)

    # 1. Lead designates a new team lead with the discord role
    target_user = _make_mock_member(5002, role_ids=[777888])
    interaction_lead = MagicMock(spec=discord.Interaction)
    interaction_lead.guild = MagicMock()
    interaction_lead.guild.id = guild_id
    interaction_lead.user = _make_mock_member(lead_id, role_ids=[777888])
    interaction_lead.response = MagicMock()
    interaction_lead.response.defer = AsyncMock()
    interaction_lead.followup = MagicMock()
    interaction_lead.followup.send = AsyncMock()

    await team_cog.team_lead.callback(
        team_cog,
        interaction=interaction_lead,
        action="add",
        team_name="DevOps",
        user=target_user,
    )

    interaction_lead.followup.send.assert_awaited_once()
    msg = interaction_lead.followup.send.await_args.args[0]
    assert "Designated" in msg
    assert await team_srv.is_team_lead(team.id, 5002) is True

    # 2. Unauthorized member tries to add team lead
    interaction_unauth = MagicMock(spec=discord.Interaction)
    interaction_unauth.guild = MagicMock()
    interaction_unauth.guild.id = guild_id
    interaction_unauth.user = _make_mock_member(5099)
    interaction_unauth.response = MagicMock()
    interaction_unauth.response.defer = AsyncMock()
    interaction_unauth.followup = MagicMock()
    interaction_unauth.followup.send = AsyncMock()

    await team_cog.team_lead.callback(
        team_cog,
        interaction=interaction_unauth,
        action="add",
        team_name="DevOps",
        user=target_user,
    )

    interaction_unauth.followup.send.assert_awaited_once()
    unauth_msg = interaction_unauth.followup.send.await_args.args[0]
    assert "You do not have permission" in unauth_msg

    # 3. Lead removes team lead status
    interaction_remove = MagicMock(spec=discord.Interaction)
    interaction_remove.guild = MagicMock()
    interaction_remove.guild.id = guild_id
    interaction_remove.user = _make_mock_member(lead_id, role_ids=[777888])
    interaction_remove.response = MagicMock()
    interaction_remove.response.defer = AsyncMock()
    interaction_remove.followup = MagicMock()
    interaction_remove.followup.send = AsyncMock()

    await team_cog.team_lead.callback(
        team_cog,
        interaction=interaction_remove,
        action="remove",
        team_name="DevOps",
        user=target_user,
    )

    interaction_remove.followup.send.assert_awaited_once()
    rem_msg = interaction_remove.followup.send.await_args.args[0]
    assert "Removed Team Lead status" in rem_msg
    assert await team_srv.is_team_lead(team.id, 5002) is False


@pytest.mark.asyncio
async def test_task_assignment_role_eligibility_enforcement(services):
    """Task assignment must strictly enforce that the assignee holds the project team's Discord role."""
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)
    guild_id = 9990010

    bot = MagicMock()
    task_cog = TaskCog(
        bot=bot,
        task_service=task_srv,
        project_service=proj_srv,
        team_service=team_srv,
        auth_service=auth_srv,
    )

    team_role_id = 444555
    team = await team_srv.create_team(guild_id=guild_id, name="Backend Squad", discord_role_id=team_role_id)
    project = await proj_srv.create_project(guild_id=guild_id, name="Payment Engine", prefix="PAY")
    await proj_srv.assign_team_to_project(project_id=project.id, team_id=team.id)

    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Stripe Webhook Handler",
        creator_discord_id=1001,
        project_id=project.id,
    )

    eligible_member = _make_mock_member(8001, role_ids=[team_role_id])
    ineligible_member = _make_mock_member(8002, role_ids=[999999])

    # 1. /task-assign with eligible member succeeds
    interaction_ok = MagicMock(spec=discord.Interaction)
    interaction_ok.guild = MagicMock()
    interaction_ok.guild.id = guild_id
    interaction_ok.guild.get_member.return_value = eligible_member
    interaction_ok.user = eligible_member
    interaction_ok.response = MagicMock()
    interaction_ok.response.defer = AsyncMock()
    interaction_ok.followup = MagicMock()
    interaction_ok.followup.send = AsyncMock()

    await task_cog.task_assign.callback(
        task_cog,
        interaction=interaction_ok,
        task=task.short_id,
        assignee=eligible_member,
    )

    interaction_ok.followup.send.assert_awaited_once()
    assert "Assigned" in interaction_ok.followup.send.await_args.args[0]

    # 2. /task-assign with ineligible member fails
    interaction_fail = MagicMock(spec=discord.Interaction)
    interaction_fail.guild = MagicMock()
    interaction_fail.guild.id = guild_id
    interaction_fail.guild.get_member.return_value = ineligible_member
    interaction_fail.user = eligible_member
    interaction_fail.response = MagicMock()
    interaction_fail.response.defer = AsyncMock()
    interaction_fail.followup = MagicMock()
    interaction_fail.followup.send = AsyncMock()

    await task_cog.task_assign.callback(
        task_cog,
        interaction=interaction_fail,
        task=task.short_id,
        assignee=ineligible_member,
    )

    interaction_fail.followup.send.assert_awaited_once()
    fail_msg = interaction_fail.followup.send.await_args.args[0]
    assert "is not a member of any team assigned to this project" in fail_msg

    # 3. Dynamic button assignee selection with ineligible member fails
    dgg_bot = DggPmBot(task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    dynamic_fail = MagicMock(spec=discord.Interaction)
    dynamic_fail.guild_id = guild_id
    dynamic_fail.guild = MagicMock()
    dynamic_fail.guild.get_member.return_value = ineligible_member
    dynamic_fail.user = eligible_member
    dynamic_fail.data = {"values": ["8002"]}
    dynamic_fail.response = MagicMock()
    dynamic_fail.response.is_done.return_value = False
    dynamic_fail.response.send_message = AsyncMock()

    await dgg_bot._handle_dynamic_task_button(dynamic_fail, "assignee", task.id)
    dynamic_fail.response.send_message.assert_awaited_once()
    dyn_err = dynamic_fail.response.send_message.await_args.args[0]
    assert "is not a member of any team assigned to this project" in dyn_err


@pytest.mark.asyncio
async def test_task_cog_watchers_self_service_vs_third_party(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)
    guild_id = 9990007

    bot = MagicMock()
    task_cog = TaskCog(
        bot=bot,
        task_service=task_srv,
        project_service=proj_srv,
        team_service=team_srv,
        auth_service=auth_srv,
    )

    project = await proj_srv.create_project(guild_id=guild_id, name="Core Lib", prefix="LIB")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Watcher Testing",
        creator_discord_id=1001,
        project_id=project.id,
    )

    # 1. Any member can add themselves as a watcher
    user_self = _make_mock_member(6001)
    interaction_self = MagicMock(spec=discord.Interaction)
    interaction_self.guild = MagicMock()
    interaction_self.guild.id = guild_id
    interaction_self.user = user_self
    interaction_self.response = MagicMock()
    interaction_self.response.defer = AsyncMock()
    interaction_self.followup = MagicMock()
    interaction_self.followup.send = AsyncMock()

    await task_cog.task_watchers.callback(
        task_cog,
        interaction=interaction_self,
        task=task.short_id,
        action="add",
        member=user_self,
    )

    interaction_self.followup.send.assert_awaited_once()
    assert "Updated watchers" in interaction_self.followup.send.await_args.args[0]

    # 2. Unauthorized user cannot clear all watchers
    interaction_clear = MagicMock(spec=discord.Interaction)
    interaction_clear.guild = MagicMock()
    interaction_clear.guild.id = guild_id
    interaction_clear.user = user_self
    interaction_clear.response = MagicMock()
    interaction_clear.response.defer = AsyncMock()
    interaction_clear.followup = MagicMock()
    interaction_clear.followup.send = AsyncMock()

    await task_cog.task_watchers.callback(
        task_cog,
        interaction=interaction_clear,
        task=task.short_id,
        action="clear",
        member=None,
    )

    interaction_clear.followup.send.assert_awaited_once()
    assert "You do not have permission" in interaction_clear.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_modal_authorization_rejection(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    auth_srv = AuthService(proj_srv, team_srv)
    guild_id = 9990008

    project = await proj_srv.create_project(guild_id=guild_id, name="Secure Vault", prefix="VAU")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Restricted Task",
        creator_discord_id=1001,
        project_id=project.id,
    )

    unauth_member = _make_mock_member(7001)

    # Note modal rejection
    note_modal = TaskNoteModal(task_id=task.id, short_id=task.short_id, task_service=task_srv, auth_service=auth_srv)
    note_modal.note_input._value = "Attempted note from unauthorized user"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = unauth_member
    interaction.response = MagicMock()
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()

    await note_modal.on_submit(interaction)
    interaction.response.send_message.assert_awaited_once()
    msg = interaction.response.send_message.await_args.args[0]
    assert "You do not have permission" in msg

    # Edit modal rejection
    edit_modal = TaskEditModal(task=task, task_service=task_srv, auth_service=auth_srv)
    edit_modal.title_input._value = "Hacked Title"

    await edit_modal.on_submit(interaction)
    msg2 = interaction.response.send_message.await_args.args[0]
    assert "You do not have permission" in msg2


@pytest.mark.asyncio
async def test_dynamic_button_authorization_rejection(services):
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 9990009

    bot = DggPmBot(
        task_service=task_srv,
        project_service=proj_srv,
        team_service=team_srv,
    )

    project = await proj_srv.create_project(guild_id=guild_id, name="Project Gate", prefix="GAT")
    task = await task_srv.create_task(
        guild_id=guild_id,
        title="Gated Operation",
        creator_discord_id=1001,
        project_id=project.id,
    )

    unauth_interaction = MagicMock(spec=discord.Interaction)
    unauth_interaction.guild_id = guild_id
    unauth_interaction.user = _make_mock_member(8001)
    unauth_interaction.response = MagicMock()
    unauth_interaction.response.is_done.return_value = False
    unauth_interaction.response.send_message = AsyncMock()

    await bot._handle_dynamic_task_button(unauth_interaction, "start", task.id)

    unauth_interaction.response.send_message.assert_awaited_once()
    err_msg = unauth_interaction.response.send_message.await_args.args[0]
    assert "You do not have permission" in err_msg


@pytest.mark.asyncio
async def test_orphaned_team_lead_permission_denial(services):
    """If a user is in DB as a lead but loses their Discord role, they lose team lead management powers."""
    proj_srv = services["project"]
    team_srv = services["team"]
    auth_srv = AuthService(proj_srv, team_srv)
    guild_id = 9990011

    team = await team_srv.create_team(guild_id=guild_id, name="Security Squad", discord_role_id=888999)
    user_id = 9001
    await team_srv.add_team_lead(team.id, user_id)

    # 1. User with the role has team lead permissions
    member_with_role = _make_mock_member(user_id, role_ids=[888999])
    assert await auth_srv.can_manage_team_leads(member_with_role, team.id) is True

    # 2. User whose role was removed loses team lead permissions
    member_without_role = _make_mock_member(user_id, role_ids=[111222])  # missing 888999
    assert await auth_srv.can_manage_team_leads(member_without_role, team.id) is False

    with pytest.raises(PermissionDeniedError, match="You do not have permission"):
        await auth_srv.require_team_lead_management(member_without_role, team.id)


@pytest.mark.asyncio
async def test_on_member_update_auto_prunes_team_lead(services):
    """Removing a team's Discord role from a member automatically prunes their DB lead record."""
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 9990012

    bot = DggPmBot(task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    team_role_id = 333444
    team = await team_srv.create_team(guild_id=guild_id, name="Platform Squad", discord_role_id=team_role_id)
    user_id = 9002
    await team_srv.add_team_lead(team.id, user_id)
    assert await team_srv.is_team_lead(team.id, user_id) is True

    mock_guild = MagicMock()
    mock_guild.id = guild_id

    before_member = _make_mock_member(user_id, role_ids=[team_role_id])
    before_member.guild = mock_guild
    after_member = _make_mock_member(user_id, role_ids=[])
    after_member.guild = mock_guild

    await bot.on_member_update(before_member, after_member)

    # Verify DB lead record was automatically removed
    assert await team_srv.is_team_lead(team.id, user_id) is False


@pytest.mark.asyncio
async def test_on_member_remove_auto_prunes_team_lead(services):
    """When a member leaves the server, all their DB team lead records in that guild are cleaned up."""
    proj_srv = services["project"]
    team_srv = services["team"]
    task_srv = services["task"]
    guild_id = 9990013

    bot = DggPmBot(task_service=task_srv, project_service=proj_srv, team_service=team_srv)

    team1 = await team_srv.create_team(guild_id=guild_id, name="Frontend Squad", discord_role_id=111)
    team2 = await team_srv.create_team(guild_id=guild_id, name="Backend Squad", discord_role_id=222)
    user_id = 9003

    await team_srv.add_team_lead(team1.id, user_id)
    await team_srv.add_team_lead(team2.id, user_id)

    assert await team_srv.is_team_lead(team1.id, user_id) is True
    assert await team_srv.is_team_lead(team2.id, user_id) is True

    mock_guild = MagicMock()
    mock_guild.id = guild_id
    leaving_member = _make_mock_member(user_id)
    leaving_member.guild = mock_guild

    await bot.on_member_remove(leaving_member)

    # Verify DB records across both teams were automatically cleaned up
    assert await team_srv.is_team_lead(team1.id, user_id) is False
    assert await team_srv.is_team_lead(team2.id, user_id) is False
