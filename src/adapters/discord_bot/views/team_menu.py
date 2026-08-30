import logging
from uuid import UUID

import discord

from src.adapters.discord_bot.error_handler import send_interaction_error
from src.domain.enums import TeamRoleType
from src.domain.models import Team
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

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

            menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"creating team '{name}'", logger, ephemeral=True)


class TeamCreateRoleSelectView(discord.ui.View):
    """Native Discord RoleSelect picker for zero-typing team creation."""

    def __init__(
        self,
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service

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

    async def _on_role_selected(self, interaction: discord.Interaction) -> None:
        selected_role = self.role_select.values[0]
        modal = TeamCreateModalWithName(self.team_service, selected_role)
        await interaction.response.send_modal(modal)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamMenuView(self.team_service, self.project_service, self.task_service)
        embed = build_team_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TeamAssignMemberSelectView(discord.ui.View):
    """View to select a team, pick a user, choose a role type, and confirm assignment."""

    def __init__(
        self,
        teams: list[Team],
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self.teams = {t.id: t for t in teams}
        self.selected_team_id: UUID | None = UUID(str(teams[0].id)) if teams else None
        self.selected_user: discord.User | discord.Member | None = None
        self.selected_role_type: TeamRoleType = TeamRoleType.MEMBER

        # Row 0: Team select
        team_options = [
            discord.SelectOption(
                label=t.name,
                value=str(t.id),
                description=f"Role: {t.discord_role_id}",
                default=(i == 0),
            )
            for i, t in enumerate(teams[:25])
        ]
        self.team_select = discord.ui.Select(
            placeholder="👥 Select Team...",
            options=team_options,
            row=0,
        )
        self.team_select.callback = self._on_team_selected
        self.add_item(self.team_select)

        # Row 1: User Select
        self.user_select = discord.ui.UserSelect(
            placeholder="👤 Pick Discord Member...",
            row=1,
            min_values=1,
            max_values=1,
        )
        self.user_select.callback = self._on_user_selected
        self.add_item(self.user_select)

        # Row 2: Role Type Select (Default: Team Member)
        role_options = [
            discord.SelectOption(label="Team Member", value="member", emoji="👤", default=True),
            discord.SelectOption(label="Team Lead", value="lead", emoji="⭐"),
        ]
        self.role_select = discord.ui.Select(
            placeholder="Role Type: Team Member / Team Lead",
            options=role_options,
            row=2,
        )
        self.role_select.callback = self._on_role_selected
        self.add_item(self.role_select)

        # Row 3: Confirm Button & Back Button
        self.confirm_btn = discord.ui.Button(
            label="Confirm Team Assignment",
            emoji="✅",
            style=discord.ButtonStyle.primary,
            row=3,
        )
        self.confirm_btn.callback = self._on_confirm_clicked
        self.add_item(self.confirm_btn)

        self.back_btn = discord.ui.Button(
            label="Back",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_team_selected(self, interaction: discord.Interaction) -> None:
        self.selected_team_id = UUID(self.team_select.values[0])
        await interaction.response.defer()

    async def _on_user_selected(self, interaction: discord.Interaction) -> None:
        self.selected_user = self.user_select.values[0]
        await interaction.response.defer()

    async def _on_role_selected(self, interaction: discord.Interaction) -> None:
        self.selected_role_type = TeamRoleType(self.role_select.values[0])
        await interaction.response.defer()

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamMenuView(self.team_service, self.project_service, self.task_service)
        embed = build_team_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_confirm_clicked(self, interaction: discord.Interaction) -> None:
        if not self.selected_team_id:
            await interaction.response.send_message("❌ Please select a team first.", ephemeral=True)
            return

        if not self.selected_user:
            if self.user_select.values:
                self.selected_user = self.user_select.values[0]
            else:
                await interaction.response.send_message("❌ Please select a Discord member to assign.", ephemeral=True)
                return

        self.selected_role_type = self.selected_role_type or TeamRoleType.MEMBER

        team = self.teams.get(self.selected_team_id)
        if not team and interaction.guild:
            teams_list = await self.team_service.list_teams(interaction.guild.id)
            team = next((t for t in teams_list if t.id == self.selected_team_id), None)

        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            return

        # Validate that the user actually has the team's Discord role
        user = self.selected_user
        if interaction.guild:
            member = interaction.guild.get_member(user.id) or user
            if hasattr(member, "roles"):
                has_role = any(r.id == team.discord_role_id for r in member.roles)
                if not has_role:
                    await interaction.response.send_message(
                        f"❌ <@{user.id}> is not part of team **{team.name}** "
                        f"(missing role <@&{team.discord_role_id}>).\n"
                        f"Please assign them the Discord role first.",
                        ephemeral=True,
                    )
                    return

        try:
            await self.team_service.assign_member(
                team_id=self.selected_team_id,
                user_discord_id=user.id,
                role_type=self.selected_role_type,
            )
            role_label = "Team Lead ⭐" if self.selected_role_type == TeamRoleType.LEAD else "Team Member 👤"

            # Return to main team menu with success notification
            view = TeamMenuView(self.team_service, self.project_service, self.task_service)
            embed = build_team_menu_embed()
            embed.description = (
                f"✅ **Assignment Successful!**\n"
                f"Assigned <@{user.id}> as **{role_label}** to **{team.name}**.\n\n" + (embed.description or "")
            )
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"assigning user to team '{team.name}'", logger, ephemeral=True
            )


class TeamRosterDetailView(discord.ui.View):
    """Interactive view allowing inspection of squad members for any team."""

    def __init__(
        self,
        teams: list[Team],
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self.teams = {t.id: t for t in teams}

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
            placeholder="👥 Show Members for Team...",
            options=options,
            row=0,
        )
        self.select.callback = self._on_select_team
        self.add_item(self.select)

        self.back_btn = discord.ui.Button(
            label="Back to Team Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_select_team(self, interaction: discord.Interaction) -> None:
        team_id = UUID(self.select.values[0])
        team = self.teams.get(team_id)
        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            return

        members = await self.team_service.list_members(team_id)
        leads = [f"<@{m.user_discord_id}>" for m in members if m.role_type == TeamRoleType.LEAD]
        regular = [f"<@{m.user_discord_id}>" for m in members if m.role_type == TeamRoleType.MEMBER]

        embed = discord.Embed(
            title=f"👥 Squad Roster: {team.name}",
            description=f"Mapped Discord Role: <@&{team.discord_role_id}>",
            color=discord.Color.teal(),
        )
        embed.add_field(
            name=f"⭐ Team Leads ({len(leads)})",
            value=", ".join(leads) if leads else "*None assigned*",
            inline=False,
        )
        embed.add_field(
            name=f"👤 Team Members ({len(regular)})",
            value=", ".join(regular) if regular else "*None assigned*",
            inline=False,
        )
        embed.set_footer(text=f"Total: {len(members)} squad members • Team ID: {team.id}")
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = TeamMenuView(self.team_service, self.project_service, self.task_service)
        embed = build_team_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class TeamMenuView(discord.ui.View):
    """Control Center View for Team Operations."""

    def __init__(
        self,
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=None)
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service

        if self.project_service and self.task_service:
            hub_btn = discord.ui.Button(
                label="PM Main Menu",
                emoji="🏠",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            hub_btn.callback = self._on_hub_clicked
            self.add_item(hub_btn)

    async def _on_hub_clicked(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed

        if self.project_service and self.task_service:
            view = PmHubView(self.project_service, self.team_service, self.task_service)
            embed = build_hub_welcome_embed()
            await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="Create Team", emoji="➕", style=discord.ButtonStyle.primary, row=0)
    async def create_team_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = TeamCreateRoleSelectView(self.team_service, self.project_service, self.task_service)
        embed = discord.Embed(
            title="➕ Create New Team",
            description="Select the Discord Server Role below to map to this team container:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Assign Member", emoji="👤", style=discord.ButtonStyle.secondary, row=0)
    async def assign_member_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        teams = await self.team_service.list_teams(interaction.guild.id)
        if not teams:
            await interaction.response.send_message(
                "👥 No teams found. Click **Create Team** to set one up first!",
                ephemeral=True,
            )
            return
        view = TeamAssignMemberSelectView(teams, self.team_service, self.project_service, self.task_service)
        embed = discord.Embed(
            title="👤 Assign Team Member",
            description="Select a team, pick a Discord member, choose Member or Lead, and confirm:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Team Roster", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def list_teams_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        teams = await self.team_service.list_teams(interaction.guild.id)
        if not teams:
            await interaction.response.send_message("👥 No teams configured in this server.", ephemeral=True)
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

        view = TeamRosterDetailView(teams, self.team_service, self.project_service, self.task_service)
        await interaction.response.edit_message(embed=embed, view=view)


def build_team_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="👥 Team Management Control Center",
        description=(
            "Configure functional squads, map Discord roles, and assign team leads.\n\n"
            "• **`➕ Create Team`**: Define a new team and map it to a Discord role\n"
            "• **`👤 Assign Member`**: Pick a user and assign them as a Team Member or Lead\n"
            "• **`📋 Team Roster`**: View all teams and their configured role mappings"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="dgg-pm • Zero-typing team management")
    return embed
