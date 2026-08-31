from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import discord

from src.adapters.discord_bot.error_handler import send_interaction_error
from src.domain.enums import TeamRoleType
from src.domain.models import Team
from src.services.auth_service import AuthService
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

if TYPE_CHECKING:
    from src.services.user_service import UserService

logger = logging.getLogger("dgg_pm.views.team_menu")


class TeamCreateModalWithName(discord.ui.Modal):
    """Modal with pre-selected role where name defaults to role name."""

    def __init__(self, team_service: TeamService, selected_role: discord.Role):
        super().__init__(title=f"Create Team: @{selected_role.name[:25]}")
        self.team_service = team_service
        self.selected_role = selected_role

        self.name_input = discord.ui.TextInput(
            label="Team Name (Defaults to Role Name)",
            default=selected_role.name,
            required=True,
            max_length=100,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be run in a Discord server.", ephemeral=True)
            return

        name = self.name_input.value.strip() or self.selected_role.name
        try:
            team = await self.team_service.create_team(
                guild_id=interaction.guild.id,
                name=name,
                discord_role_id=self.selected_role.id,
            )
            embed = discord.Embed(
                title=f"✅ Team Created: {team.name}",
                description=f"Mapped to Discord role <@&{team.discord_role_id}>",
                color=discord.Color.green(),
            )
            embed.set_footer(text=f"Team ID: {team.id}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"creating team '{name}'", logger, ephemeral=True)


class TeamCreateRoleSelectView(discord.ui.View):
    """Native Discord RoleSelect picker for zero-typing team creation."""

    def __init__(
        self,
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

        self.role_select = discord.ui.RoleSelect(
            placeholder="🎭 Select Discord Server Role for Team...",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.role_select.callback = self._on_role_selected
        self.add_item(self.role_select)

        self.back_btn = discord.ui.Button(
            label="Back to Team Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def on_timeout(self) -> None:
        try:
            if (
                hasattr(self, "_initial_interaction")
                and self._initial_interaction
                and hasattr(self._initial_interaction, "delete_original_response")
            ):
                await self._initial_interaction.delete_original_response()
        except Exception:
            pass

    async def _on_role_selected(self, interaction: discord.Interaction) -> None:
        selected_role = self.role_select.values[0]
        modal = TeamCreateModalWithName(self.team_service, selected_role)
        await interaction.response.send_modal(modal)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamMenuView(
            self.team_service,
            self.project_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_team_menu_embed(view.can_create_teams, view.can_assign_members)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TeamAssignMemberSelectView(discord.ui.View):
    """View to select a team, pick a user, choose a role type, and confirm assignment."""

    def __init__(
        self,
        teams: list[Team],
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.teams = {t.id: t for t in teams}
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

        self.selected_team_id: UUID = teams[0].id
        self.selected_user: discord.Member | discord.User | None = None
        self.selected_role_type_str: str = "member"

        # Row 0: Select Team Dropdown
        team_options = [
            discord.SelectOption(
                label=t.name,
                value=str(t.id),
                description=f"Role: {t.discord_role_id}",
                emoji="👥",
                default=(i == 0),
            )
            for i, t in enumerate(teams[:25])
        ]
        self.team_select = discord.ui.Select(
            placeholder="👥 Select Target Team...",
            options=team_options,
            min_values=1,
            max_values=1,
            row=0,
        )
        self.team_select.callback = self._on_team_changed
        self.add_item(self.team_select)

        # Row 1: Select User / Member
        self.user_select = discord.ui.UserSelect(
            placeholder="👤 Select Discord Member...",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.user_select.callback = self._on_user_selected
        self.add_item(self.user_select)

        # Row 2: Select Role Type (Member, Lead, Remove Lead)
        role_type_options = [
            discord.SelectOption(
                label="Team Member (Regular)",
                value="member",
                description="Assign member to squad roster",
                emoji="👤",
                default=True,
            ),
            discord.SelectOption(
                label="Team Lead (Elevated)",
                value="lead",
                description="Designate lead with team management permissions",
                emoji="⭐",
            ),
            discord.SelectOption(
                label="Remove Lead Status",
                value="remove_lead",
                description="Demote from Team Lead back to regular member",
                emoji="⬇️",
            ),
        ]
        self.role_select = discord.ui.Select(
            placeholder="🎭 Select Role Type...",
            options=role_type_options,
            min_values=1,
            max_values=1,
            row=2,
        )
        self.role_select.callback = self._on_role_type_selected
        self.add_item(self.role_select)

        # Row 3: Action Buttons
        self.confirm_btn = discord.ui.Button(
            label="Confirm Assignment",
            emoji="✅",
            style=discord.ButtonStyle.primary,
            row=3,
        )
        self.confirm_btn.callback = self._on_confirm_clicked
        self.add_item(self.confirm_btn)

        self.cancel_btn = discord.ui.Button(
            label="Cancel",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        self.cancel_btn.callback = self._on_cancel_clicked
        self.add_item(self.cancel_btn)

    async def on_timeout(self) -> None:
        try:
            if (
                hasattr(self, "_initial_interaction")
                and self._initial_interaction
                and hasattr(self._initial_interaction, "delete_original_response")
            ):
                await self._initial_interaction.delete_original_response()
        except Exception:
            pass

    async def _on_team_changed(self, interaction: discord.Interaction) -> None:
        self.selected_team_id = UUID(self.team_select.values[0])
        for opt in self.team_select.options:
            opt.default = opt.value == str(self.selected_team_id)
        await interaction.response.defer()

    async def _on_user_selected(self, interaction: discord.Interaction) -> None:
        self.selected_user = self.user_select.values[0]
        await interaction.response.defer()

    async def _on_role_type_selected(self, interaction: discord.Interaction) -> None:
        val = self.role_select.values[0]
        self.selected_role_type_str = val
        for opt in self.role_select.options:
            opt.default = opt.value == val
        await interaction.response.defer()

    _on_role_selected = _on_role_type_selected

    async def _on_cancel_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamMenuView(
            self.team_service,
            self.project_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_team_menu_embed(view.can_create_teams, view.can_assign_members)
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_confirm_clicked(self, interaction: discord.Interaction) -> None:
        if not self.selected_team_id:
            await interaction.response.send_message("❌ Please select a team first.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        if not self.selected_user:
            if self.user_select.values:
                self.selected_user = self.user_select.values[0]
            else:
                await interaction.response.send_message("❌ Please select a Discord member first.", ephemeral=True)
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
                return

        action_type = self.selected_role_type_str
        team = self.teams.get(self.selected_team_id)

        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            return

        # Check authorization
        if not AuthService.is_server_manager(interaction.user):
            is_lead = await self.team_service.is_team_lead(self.selected_team_id, interaction.user.id)
            if not is_lead:
                await interaction.response.send_message(
                    "❌ You do not have permission to manage this team's roster. "
                    "You must be a Team Lead or a server manager.",
                    ephemeral=True,
                )
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
                return

        # Validate that the user actually has the team's Discord role for add/verify
        user = self.selected_user
        if action_type != "remove_lead" and interaction.guild:
            member = interaction.guild.get_member(user.id) if hasattr(interaction.guild, "get_member") else user
            member = member or user
            if hasattr(member, "roles"):
                has_role = any(r.id == team.discord_role_id for r in member.roles)
                if not has_role:
                    await interaction.response.send_message(
                        f"❌ <@{user.id}> is not part of team **{team.name}** "
                        f"(missing role <@&{team.discord_role_id}>).\n"
                        f"Please assign them the Discord role first.",
                        ephemeral=True,
                    )
                    from src.adapters.discord_bot.menu_manager import menu_manager

                    menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
                    return

        try:
            if action_type == "remove_lead":
                await self.team_service.remove_team_lead(self.selected_team_id, self.selected_user.id)
                success_msg = f"✅ Removed Team Lead status from <@{self.selected_user.id}> for **{team.name}**."
            elif action_type == "lead":
                await self.team_service.add_team_lead(self.selected_team_id, self.selected_user.id)
                success_msg = f"⭐ Designated <@{self.selected_user.id}> as **Team Lead** for **{team.name}**."
            else:
                await self.team_service.assign_member(
                    team_id=self.selected_team_id,
                    user_discord_id=self.selected_user.id,
                    role_type=TeamRoleType.MEMBER,
                )
                success_msg = f"✅ Verified <@{self.selected_user.id}> as **Team Member** for **{team.name}**."

            view = TeamMenuView(
                self.team_service,
                self.project_service,
                self.task_service,
                initial_interaction=interaction,
            )
            embed = build_team_menu_embed(view.can_create_teams, view.can_assign_members)
            embed.description = f"{success_msg}\n\n" + (embed.description or "")
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"updating team settings for '{team.name}'", logger, ephemeral=True
            )


class TeamRosterDetailView(discord.ui.View):
    """Interactive view allowing inspection of squad members for any team."""

    def __init__(
        self,
        teams: list[Team],
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self.teams = {t.id: t for t in teams}
        self._initial_interaction = initial_interaction

        options = [
            discord.SelectOption(
                label=t.name,
                value=str(t.id),
                description=f"Role: {t.discord_role_id}",
                emoji="👥",
            )
            for t in teams[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="👥 Select Team to Inspect Members...",
            options=options,
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

        self.back_btn = discord.ui.Button(
            label="Back to Team Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def on_timeout(self) -> None:
        try:
            if (
                hasattr(self, "_initial_interaction")
                and self._initial_interaction
                and hasattr(self._initial_interaction, "delete_original_response")
            ):
                await self._initial_interaction.delete_original_response()
        except Exception:
            pass

    async def _on_select(self, interaction: discord.Interaction) -> None:
        val = self.select.values[0]
        team_id = UUID(val)
        team = self.teams.get(team_id)
        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        members = await self.team_service.list_members(team.id)
        leads = [m for m in members if m.role_type == TeamRoleType.LEAD]
        regular = [m for m in members if m.role_type == TeamRoleType.MEMBER]

        embed = discord.Embed(
            title=f"👥 Squad Roster: {team.name}",
            description=f"**Discord Role:** <@&{team.discord_role_id}>\n**Total Members:** `{len(members)}`",
            color=discord.Color.blurple(),
        )

        leads_str = "\n".join(f"• ⭐ <@{m.user_discord_id}> (Team Lead)" for m in leads) or "*None assigned*"
        embed.add_field(name=f"⭐ Team Leads ({len(leads)})", value=leads_str, inline=False)

        members_str = "\n".join(f"• 👤 <@{m.user_discord_id}>" for m in regular) or "*None assigned*"
        embed.add_field(name=f"👤 Verified Members ({len(regular)})", value=members_str, inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    _on_select_team = _on_select

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamMenuView(
            self.team_service,
            self.project_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_team_menu_embed(view.can_create_teams, view.can_assign_members)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TeamMenuView(discord.ui.View):
    """Control Center View for Team Operations."""

    def __init__(
        self,
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
        user: discord.Member | discord.User | None = None,
        can_create_teams: bool | None = None,
        can_assign_members: bool | None = None,
        user_service: UserService | None = None,
        return_to: str = "dashboard",
    ):
        super().__init__(timeout=180)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self.user_service = user_service
        self.return_to = return_to
        self._initial_interaction = initial_interaction

        effective_user = user or (initial_interaction.user if initial_interaction else None)
        if can_create_teams is not None:
            self.can_create_teams = can_create_teams
        elif effective_user is not None:
            self.can_create_teams = AuthService.is_server_manager(effective_user)
        else:
            self.can_create_teams = True

        if can_assign_members is not None:
            self.can_assign_members = can_assign_members
        elif effective_user is not None:
            self.can_assign_members = AuthService.is_server_manager(effective_user)
        else:
            self.can_assign_members = True

        self._rebuild_items()

    def _rebuild_items(self) -> None:
        self.clear_items()

        if self.can_create_teams:
            self.create_team_btn = discord.ui.Button(
                label="Create Team",
                emoji="➕",
                style=discord.ButtonStyle.primary,
                row=0,
            )
            self.create_team_btn.callback = self._on_create_team_clicked
            self.add_item(self.create_team_btn)
        else:
            self.create_team_btn = None

        if self.can_assign_members:
            self.assign_member_btn = discord.ui.Button(
                label="Assign Member",
                emoji="👤",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            self.assign_member_btn.callback = self._on_assign_member_clicked
            self.add_item(self.assign_member_btn)
        else:
            self.assign_member_btn = None

        # Row 0: Team Roster (Always visible)
        self.list_teams_btn = discord.ui.Button(
            label="Team Roster",
            emoji="📋",
            style=discord.ButtonStyle.secondary
            if (self.can_create_teams or self.can_assign_members)
            else discord.ButtonStyle.primary,
            row=0,
        )
        self.list_teams_btn.callback = self._on_list_teams_clicked
        self.roster_btn = self.list_teams_btn
        self.add_item(self.list_teams_btn)

        if self.project_service and self.task_service:
            self.hub_btn = discord.ui.Button(
                label="PM Main Menu",
                emoji="🏠",
                style=discord.ButtonStyle.secondary,
                row=1 if (self.can_create_teams or self.can_assign_members) else 0,
            )
            self.hub_btn.callback = self._on_hub_clicked
            self.add_item(self.hub_btn)
        else:
            self.hub_btn = None

    async def on_timeout(self) -> None:
        try:
            if (
                hasattr(self, "_initial_interaction")
                and self._initial_interaction
                and hasattr(self._initial_interaction, "delete_original_response")
            ):
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.unregister_menu(self._initial_interaction)
                await self._initial_interaction.delete_original_response()
        except Exception:
            pass

    async def _on_hub_clicked(self, interaction: discord.Interaction) -> None:
        if self.return_to == "dashboard" and interaction.guild:
            from src.adapters.discord_bot.views.admin_menu import PmDashboardView, build_pm_dashboard_embed
            from src.domain.enums import NotificationPreference

            projects = (
                await self.project_service.list_projects(interaction.guild.id, include_archived=False)
                if self.project_service
                else []
            )
            _, count = (
                await self.task_service.list_tasks(interaction.guild.id, limit=1) if self.task_service else ([], 0)
            )
            current_pref = (
                await self.user_service.get_preference(interaction.guild.id, interaction.user.id)
                if self.user_service
                else NotificationPreference.DM
            )
            view = PmDashboardView(
                self.project_service,
                self.team_service,
                self.task_service,
                self.user_service,
                initial_interaction=interaction,
            )
            embed = build_pm_dashboard_embed(
                guild=interaction.guild,
                user=interaction.user,
                active_projects=projects,
                active_tasks_count=count,
                current_pref=current_pref,
                is_server_manager=view.is_server_manager,
            )
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        else:
            from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed

            if self.project_service and self.task_service:
                view = PmHubView(self.project_service, self.team_service, self.task_service, self.user_service)
                embed = build_hub_welcome_embed()
                await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_create_team_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamCreateRoleSelectView(
            self.team_service,
            self.project_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = discord.Embed(
            title="➕ Create New Team",
            description="Select the Discord Server Role below to map to this team container:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_assign_member_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        teams = await self.team_service.list_teams(interaction.guild.id)
        if not teams:
            await interaction.response.send_message(
                "👥 No teams found. Click **Create Team** to set one up first!",
                ephemeral=True,
            )
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        view = TeamAssignMemberSelectView(
            teams,
            self.team_service,
            self.project_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = discord.Embed(
            title="👤 Assign Team Member",
            description="Select a team, pick a Discord member, choose Member or Lead, and confirm:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_list_teams_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        teams = await self.team_service.list_teams(interaction.guild.id)
        if not teams:
            await interaction.response.send_message("👥 No teams configured in this server.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        embed = discord.Embed(
            title=f"👥 Server Teams ({len(teams)})",
            description="Select a team below to inspect assigned leads and members:",
            color=discord.Color.blurple(),
        )
        for t in teams:
            members = await self.team_service.list_members(t.id)
            leads_count = sum(1 for m in members if m.role_type == TeamRoleType.LEAD)
            members_count = sum(1 for m in members if m.role_type == TeamRoleType.MEMBER)
            embed.add_field(
                name=f"👥 {t.name}",
                value=f"• Role: <@&{t.discord_role_id}>\n• Leads: {leads_count} | Members: {members_count}",
                inline=False,
            )

        view = TeamRosterDetailView(
            teams,
            self.team_service,
            self.project_service,
            self.task_service,
            initial_interaction=interaction,
        )
        await interaction.response.edit_message(embed=embed, view=view)


def build_team_menu_embed(can_create_teams: bool = True, can_assign_members: bool = True) -> discord.Embed:
    embed = discord.Embed(
        title="👥 Squad & Team Management Hub",
        color=discord.Color.dark_theme(),
    )
    bullets = []
    if can_create_teams:
        bullets.append("• **`➕ Create Team`**: Define a new team and map it to a Discord role")
    if can_assign_members:
        bullets.append("• **`👤 Assign Member`**: Pick a user and assign them as a Team Member or Lead")
    bullets.append("• **`📋 Team Roster`**: View all teams and their configured role mappings")

    if can_create_teams or can_assign_members:
        desc = (
            "> 👥 **Contributor Squads & Permission Mappings**\n"
            "> Configure functional squads, map Discord roles, and assign team leads.\n\n" + "\n".join(bullets)
        )
    else:
        desc = (
            "> 👥 **Server Squad Rosters**\n"
            "> Inspect configured functional squads and server team rosters.\n\n" + "\n".join(bullets)
        )

    embed.description = desc
    embed.set_footer(text="dgg-pm • Discord-Native Team Management")
    return embed
