import discord
from discord import app_commands
from discord.ext import commands

from src.domain.enums import TeamRoleType
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService


class TeamCog(commands.Cog):
    """Slash commands for managing teams and functional roles."""

    def __init__(
        self,
        bot: commands.Bot,
        team_service: TeamService,
        project_service: ProjectService | None = None,
        task_service: TaskService | None = None,
    ):
        self.bot = bot
        self.team_service = team_service
        self.project_service = project_service
        self.task_service = task_service

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

        await interaction.response.defer()
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
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create team: {e}", ephemeral=True)

    async def team_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete functional teams for current guild."""
        if not interaction.guild:
            return []
        teams = await self.team_service.list_teams(interaction.guild.id)
        choices = [
            app_commands.Choice(name=t.name, value=t.name)
            for t in teams
            if not current or current.lower() in t.name.lower()
        ]
        return choices[:25]

    @app_commands.command(name="team-assign", description="Assign a Discord member to a team with domain role.")
    @app_commands.describe(
        user="Discord user to assign",
        team_name="Name of the team",
        role_type="Domain role (lead or member)",
    )
    @app_commands.choices(
        role_type=[
            app_commands.Choice(name="Member", value="member"),
            app_commands.Choice(name="Lead", value="lead"),
        ]
    )
    @app_commands.autocomplete(team_name=team_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def team_assign(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        team_name: str,
        role_type: str = "member",
    ) -> None:
        if not interaction.guild:
            return

        await interaction.response.defer()
        try:
            team = await self.team_service.get_by_name(interaction.guild.id, team_name)
            if not team:
                await interaction.followup.send(f"❌ Team '{team_name}' not found.", ephemeral=True)
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
                role_type=TeamRoleType(role_type),
            )

            msg = (
                f"✅ Assigned <@{user.id}> as **{role_type.upper()}** "
                f"to team **{team.name}** (<@&{team.discord_role_id}>)."
            )
            await interaction.followup.send(msg)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to assign team member: {e}", ephemeral=True)

    @app_commands.command(name="team-list", description="List all functional teams in this server.")
    async def team_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        teams = await self.team_service.list_teams(interaction.guild.id)
        if not teams:
            await interaction.followup.send("👥 No teams created yet. Use `/team-create` to set one up.")
            return

        embed = discord.Embed(title="👥 Server Teams", color=discord.Color.teal())
        for t in teams:
            embed.add_field(name=f"**{t.name}**", value=f"Role: <@&{t.discord_role_id}>", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="team-menu", description="Open interactive Team Management Control Center.")
    async def team_menu(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.team_menu import TeamMenuView, build_team_menu_embed

        embed = build_team_menu_embed()
        view = TeamMenuView(self.team_service, self.project_service, self.task_service)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
