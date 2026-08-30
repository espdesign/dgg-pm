from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.adapters.discord_bot.error_handler import send_interaction_error
from src.domain.enums import TeamRoleType
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

if TYPE_CHECKING:
    from src.services.auth_service import AuthService

logger = logging.getLogger("dgg_pm.cogs.team")


class TeamCog(commands.Cog):
    """Slash commands for managing teams and functional roles."""

    def __init__(
        self,
        bot: commands.Bot,
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
        auth_service: AuthService | None = None,
    ):
        self.bot = bot
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service
        self.auth_service = auth_service

    @app_commands.command(name="team-create", description="Define a functional team entity linked to a Discord role.")
    @app_commands.describe(
        name="Name of the team (e.g. Frontend, Backend, Design)",
        role="Discord server role mapped to this team",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def team_create(
        self,
        interaction: discord.Interaction,
        name: str,
        role: discord.Role,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            team = await self.team_service.create_team(
                guild_id=interaction.guild.id,
                name=name,
                discord_role_id=role.id,
            )

            embed = discord.Embed(
                title=f"👥 Team Created: {team.name}",
                description=f"Linked to Discord Role: <@&{team.discord_role_id}>",
                color=discord.Color.teal(),
            )
            embed.set_footer(text=f"Team ID: {team.id}")
            await interaction.followup.send(embed=embed)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"creating team '{name}'", logger, ephemeral=True)

    async def team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete functional teams for current guild."""
        if not interaction.guild:
            return []
        try:
            teams = await self.team_service.list_teams(interaction.guild.id)
            choices = [
                app_commands.Choice(name=t.name, value=t.name)
                for t in teams
                if not current or current.lower() in t.name.lower()
            ]
            return choices[:25]
        except Exception as e:
            logger.exception("Error during team autocomplete: %s", e)
            return []

    @app_commands.command(name="team-lead", description="Designate or remove a Team Lead for a functional team.")
    @app_commands.describe(
        action="Action to perform (Add or Remove Team Lead)",
        team_name="Name of the functional team",
        user="Discord member to designate or remove as Team Lead",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Add Team Lead", value="add"),
            app_commands.Choice(name="Remove Team Lead", value="remove"),
        ]
    )
    @app_commands.autocomplete(team_name=team_autocomplete)
    async def team_lead(
        self,
        interaction: discord.Interaction,
        action: str,
        team_name: str,
        user: discord.Member,
    ) -> None:
        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=True)
        try:
            team = await self.team_service.get_by_name(interaction.guild.id, team_name)
            if not team:
                await interaction.followup.send(f"❌ Team '{team_name}' not found.", ephemeral=True)
                return

            if self.auth_service:
                await self.auth_service.require_team_lead_management(interaction.user, team.id)
            elif not AuthService.is_server_manager(interaction.user):
                is_lead = await self.team_service.is_team_lead(team.id, interaction.user.id)
                if not is_lead:
                    await interaction.followup.send(
                        "❌ You do not have permission to manage team leads for this team. "
                        "You must be a Team Lead or a server manager.",
                        ephemeral=True,
                    )
                    return

            if action == "add":
                # Validate that user holds the team's Discord role
                if hasattr(user, "roles"):
                    has_role = any(r.id == team.discord_role_id for r in user.roles)
                    if not has_role:
                        await interaction.followup.send(
                            f"❌ <@{user.id}> is not part of team **{team.name}** "
                            f"(missing role <@&{team.discord_role_id}>).\n"
                            f"Please assign them the Discord role first.",
                            ephemeral=True,
                        )
                        return

                await self.team_service.add_team_lead(team.id, user.id)
                msg = (
                    f"⭐ Designated <@{user.id}> as **Team Lead** "
                    f"for team **{team.name}** (<@&{team.discord_role_id}>)."
                )
            else:
                await self.team_service.remove_team_lead(team.id, user.id)
                msg = f"✅ Removed Team Lead status from <@{user.id}> for team **{team.name}**."

            await interaction.followup.send(msg)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"managing team lead for team '{team_name}'", logger, ephemeral=True
            )

    @app_commands.command(name="team-assign", description="Designate a Team Lead or record domain role.")
    @app_commands.describe(
        user="Discord member",
        team_name="Name of the functional team",
        role_type="Functional role (Lead or Member)",
    )
    @app_commands.choices(
        role_type=[
            app_commands.Choice(name="Lead", value="lead"),
            app_commands.Choice(name="Member", value="member"),
        ]
    )
    @app_commands.autocomplete(team_name=team_autocomplete)
    async def team_assign(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        team_name: str,
        role_type: str = "member",
    ) -> None:
        if role_type == "lead":
            await self.team_lead.callback(self, interaction, "add", team_name, user)
            return

        if not interaction.guild:
            return

        await interaction.response.defer(ephemeral=True)
        try:
            team = await self.team_service.get_by_name(interaction.guild.id, team_name)
            if not team:
                await interaction.followup.send(f"❌ Team '{team_name}' not found.", ephemeral=True)
                return

            if self.auth_service:
                await self.auth_service.require_team_lead_management(interaction.user, team.id)
            elif not AuthService.is_server_manager(interaction.user):
                is_lead = await self.team_service.is_team_lead(team.id, interaction.user.id)
                if not is_lead:
                    await interaction.followup.send(
                        "❌ You do not have permission to manage this team's roster. "
                        "You must be a Team Lead or a server manager.",
                        ephemeral=True,
                    )
                    return

            # Check if user has team's Discord role
            if hasattr(user, "roles"):
                has_role = any(r.id == team.discord_role_id for r in user.roles)
                if not has_role:
                    await interaction.followup.send(
                        f"❌ <@{user.id}> is not part of team **{team.name}** "
                        f"(missing role <@&{team.discord_role_id}>).\n"
                        f"Please assign them the Discord role first.",
                        ephemeral=True,
                    )
                    return

            await self.team_service.assign_member(
                team_id=team.id,
                user_discord_id=user.id,
                role_type=TeamRoleType.MEMBER,
            )

            msg = f"✅ Verified <@{user.id}> as **MEMBER** for team **{team.name}** (<@&{team.discord_role_id}>)."
            await interaction.followup.send(msg)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"assigning member to team '{team_name}'", logger, ephemeral=True
            )

    @app_commands.command(name="team-list", description="List all functional teams with live Discord members.")
    async def team_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            teams = await self.team_service.list_teams(interaction.guild.id)
            if not teams:
                await interaction.followup.send("👥 No teams created yet. Use `/team-create` to set one up.")
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
                return

            embed = discord.Embed(title="👥 Server Teams & Rosters", color=discord.Color.teal())
            for t in teams:
                leads = await self.team_service.list_team_leads(t.id)
                role = interaction.guild.get_role(t.discord_role_id) if hasattr(interaction.guild, "get_role") else None
                role_members = getattr(role, "members", []) if role else []

                lead_strs = [f"<@{uid}>" for uid in leads]
                if lead_strs:
                    lead_line = f"⭐ **Team Lead**: {', '.join(lead_strs)}"
                else:
                    lead_line = "⭐ **Team Lead**: None designated"

                other_members = [f"<@{m.id}>" for m in role_members if m.id not in leads]
                member_count = len(role_members)
                if other_members:
                    sample = ", ".join(other_members[:8])
                    if len(other_members) > 8:
                        sample += f" *(+{len(other_members) - 8} more)*"
                    members_line = f"👤 **Members ({member_count})**: {sample}"
                elif role_members:
                    members_line = f"👤 **Members ({member_count})**: (All leads)"
                else:
                    members_line = f"👤 **Members ({member_count})**: None with role <@&{t.discord_role_id}>"

                field_val = f"Role: <@&{t.discord_role_id}>\n{lead_line}\n{members_line}"
                embed.add_field(name=f"**{t.name}**", value=field_val, inline=False)

            await interaction.followup.send(embed=embed)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
        except Exception as e:
            await send_interaction_error(interaction, e, "listing teams", logger, ephemeral=True)

    @app_commands.command(name="team-menu", description="Open interactive Team Management Control Center.")
    async def team_menu(self, interaction: discord.Interaction) -> None:
        try:
            from src.adapters.discord_bot.menu_manager import menu_manager
            from src.adapters.discord_bot.views.team_menu import TeamMenuView, build_team_menu_embed

            embed = build_team_menu_embed()
            view = TeamMenuView(self.team_service, self.project_service, self.task_service)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            await menu_manager.register_menu(interaction)
        except Exception as e:
            await send_interaction_error(interaction, e, "opening team menu", logger, ephemeral=True)
