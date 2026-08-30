import discord
from discord import app_commands
from discord.ext import commands

from src.domain.enums import TaskStatus
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService


class ProjectCog(commands.Cog):
    """Slash commands for managing projects and containers."""

    def __init__(
        self,
        bot: commands.Bot,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        self.bot = bot
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

    @app_commands.command(name="project-create", description="Instantiate a top-level project container.")
    @app_commands.describe(
        name="Name of the project (e.g. Infrastructure)",
        channel="Discord text channel to bind as the project's task feed",
        prefix="Optional 3-4 letter prefix (e.g. INF)",
        description="Brief summary of the project goals",
        category="Category or domain (e.g. Engineering, Marketing)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_create(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        prefix: str | None = None,
        description: str | None = None,
        category: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        try:
            project = await self.project_service.create_project(
                guild_id=interaction.guild.id,
                name=name,
                prefix=prefix,
                description=description,
                discord_channel_id=channel.id,
                category=category,
            )

            embed = discord.Embed(
                title=f"📁 Project Created: {project.name} (`{project.prefix}`)",
                description=project.description or "*No description provided.*",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Task ID Prefix", value=f"`{project.prefix}-#`", inline=True)
            if project.discord_channel_id:
                embed.add_field(name="Bound Channel", value=f"<#{project.discord_channel_id}>", inline=True)
            if project.category:
                embed.add_field(name="Category", value=project.category, inline=True)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create project: {e}", ephemeral=True)

    async def project_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete active projects for current guild."""
        if not interaction.guild:
            return []
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        choices = [
            app_commands.Choice(name=f"{p.name} ({p.prefix})", value=p.name)
            for p in projects
            if not current or current.lower() in p.name.lower() or current.lower() in p.prefix.lower()
        ]
        return choices[:25]

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

    async def archived_project_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete archived projects for current guild."""
        if not interaction.guild:
            return []
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=True)
        archived = [p for p in projects if p.is_archived]
        choices = [
            app_commands.Choice(name=f"{p.name} ({p.prefix})", value=p.name)
            for p in archived
            if not current or current.lower() in p.name.lower() or current.lower() in p.prefix.lower()
        ]
        return choices[:25]

    @app_commands.command(name="project-assign", description="Map a functional team container to a project.")
    @app_commands.describe(
        project_name="Name of the project",
        team_name="Name of the team",
        timeline="Target timeline (e.g. Q2 2026, 6 weeks)",
    )
    @app_commands.autocomplete(project_name=project_autocomplete, team_name=team_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_assign(
        self,
        interaction: discord.Interaction,
        project_name: str,
        team_name: str,
        timeline: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            project = await self.project_service.get_by_name(interaction.guild.id, project_name)
            if not project:
                await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
                return

            team = await self.team_service.get_by_name(interaction.guild.id, team_name)
            if not team:
                await interaction.followup.send(f"❌ Team '{team_name}' not found.", ephemeral=True)
                return

            await self.project_service.assign_team_to_project(
                project_id=project.id,
                team_id=team.id,
                timeline=timeline,
            )

            await interaction.followup.send(
                f"✅ Assigned team **{team.name}** (<@&{team.discord_role_id}>) to project **{project.name}**."
                + (f" Timeline: `{timeline}`" if timeline else "")
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to assign team to project: {e}", ephemeral=True)

    @app_commands.command(name="project-list", description="List all projects in this server.")
    async def project_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        projects = await self.project_service.list_projects(interaction.guild.id)
        if not projects:
            await interaction.followup.send("📁 No active projects found. Use `/project-create` to start one.")
            return

        embed = discord.Embed(title="📁 Server Projects", color=discord.Color.blurple())
        for p in projects:
            chan_str = f" • <#{p.discord_channel_id}>" if p.discord_channel_id else ""
            desc = f"Prefix: `{p.prefix}`{chan_str}\n" + (f"> {p.description}" if p.description else "")
            embed.add_field(name=f"**{p.name}**", value=desc, inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="project-archive", description="Archive a project and its associated tasks.")
    @app_commands.describe(project_name="Name of the project to archive")
    @app_commands.autocomplete(project_name=project_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_archive(self, interaction: discord.Interaction, project_name: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        project = await self.project_service.get_by_name(interaction.guild.id, project_name)
        if not project:
            await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
            return

        tasks = []
        if self.task_service:
            tasks, _ = await self.task_service.list_tasks(
                guild_id=interaction.guild.id,
                project_id=project.id,
                include_archived=False,
                limit=500,
            )

        await self.project_service.archive_project(project.id)

        if hasattr(self.bot, "sync_task_thread"):
            for t in tasks:
                if t.discord_thread_id:
                    await self.bot.sync_task_thread(t, action="archive")

        await interaction.followup.send(f"📁 Project **{project.name}** and its active tasks have been archived.")

    @app_commands.command(name="project-unarchive", description="Restore an archived project and its tasks.")
    @app_commands.describe(project_name="Name of the project to restore")
    @app_commands.autocomplete(project_name=archived_project_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_unarchive(self, interaction: discord.Interaction, project_name: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        project = await self.project_service.get_by_name(interaction.guild.id, project_name)
        if not project:
            await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
            return

        await self.project_service.unarchive_project(project.id)

        if self.task_service and hasattr(self.bot, "sync_task_thread"):
            restored_tasks, _ = await self.task_service.list_tasks(
                guild_id=interaction.guild.id,
                project_id=project.id,
                include_archived=False,
                limit=500,
            )
            for t in restored_tasks:
                if t.discord_thread_id and t.status != TaskStatus.COMPLETED:
                    await self.bot.sync_task_thread(t, action="unarchive")

        await interaction.followup.send(f"📂 Project **{project.name}** and its active tasks have been restored.")

    @app_commands.command(name="project-menu", description="Open interactive Project Management Control Center.")
    async def project_menu(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.project_menu import ProjectMenuView, build_project_menu_embed

        embed = build_project_menu_embed()
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
