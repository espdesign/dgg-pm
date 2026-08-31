from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from src.adapters.discord_bot.error_handler import send_interaction_error
from src.adapters.discord_bot.views.forum_helpers import ensure_pinned_hub_post, ensure_project_tag, setup_forum_tags
from src.domain.enums import TaskStatus
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.cogs.project")


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
        channel="Discord Forum Channel to bind as the project's task board",
        role="Discord server role representing the squad working on this project",
        lead="Designated Project Lead member with management permissions",
        prefix="Optional 3-4 letter prefix (e.g. INF)",
        description="Brief summary of the project goals",
        category="Category or domain (e.g. Engineering, Marketing)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_create(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.ForumChannel,
        role: discord.Role | None = None,
        lead: discord.Member | None = None,
        prefix: str | None = None,
        description: str | None = None,
        category: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        if not isinstance(channel, discord.ForumChannel):
            await interaction.response.send_message(
                "❌ Projects must be bound to a Discord Forum Channel.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            project = await self.project_service.create_project(
                guild_id=interaction.guild.id,
                name=name,
                prefix=prefix,
                description=description,
                discord_channel_id=channel.id,
                discord_role_id=role.id if role else None,
                lead_discord_id=lead.id if lead else None,
                category=category,
            )

            chan_type_label = "Forum Post Board"
            tag_note = ""

            tags_added, _total_tags, tag_err = await setup_forum_tags(channel)
            if tags_added > 0:
                tag_note = f" • Setup {tags_added} PM tags"
            elif tag_err:
                tag_note = f" • ⚠️ {tag_err}"
            proj_tag_err = await ensure_project_tag(channel, project.name)
            if proj_tag_err:
                tag_note += f" • ⚠️ {proj_tag_err}"

            # Auto-create and pin the PM Control Hub in the linked channel
            hub_ok, _hub_status = await ensure_pinned_hub_post(
                channel=channel,
                project_service=self.project_service,
                team_service=self.team_service,
                task_service=self.task_service,
                user_service=getattr(self.bot, "user_service", None),
                project_name=project.name,
            )
            if hub_ok:
                tag_note += " • 📌 Pinned Control Hub"

            embed = discord.Embed(
                title=f"📁 Project Created: {project.name} (`{project.prefix}`)",
                description=project.description or "*No description provided.*",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Task ID Prefix", value=f"`{project.prefix}-#`", inline=True)
            if project.discord_role_id:
                embed.add_field(name="Squad Role", value=f"<@&{project.discord_role_id}>", inline=True)
            if project.lead_discord_id:
                embed.add_field(name="👑 Project Lead", value=f"<@{project.lead_discord_id}>", inline=True)
            if project.discord_channel_id:
                embed.add_field(
                    name="Bound Channel",
                    value=f"<#{project.discord_channel_id}> ({chan_type_label}{tag_note})",
                    inline=True,
                )
            if project.category:
                embed.add_field(name="Category", value=project.category, inline=True)

            await interaction.followup.send(embed=embed)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"creating project '{name}'", logger, ephemeral=True)

    @app_commands.command(
        name="project-setup-forum",
        description="Automatically configure standard project management tags on a Forum Channel.",
    )
    @app_commands.describe(forum="The Discord Forum Channel to configure with PM tags")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_setup_forum(
        self,
        interaction: discord.Interaction,
        forum: discord.ForumChannel,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            tags_added, total_tags, err = await setup_forum_tags(forum)
            if err:
                await interaction.followup.send(f"❌ Failed to configure tags in <#{forum.id}>: {err}", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"🏷️ Forum Tags Configured: #{forum.name}",
                description=(
                    f"Successfully verified and updated tags in <#{forum.id}>!\n\n"
                    f"• **New Tags Added:** `{tags_added}`\n"
                    f"• **Total Available Tags:** `{total_tags}` / 20\n\n"
                    "**Standard Tags Managed:**\n"
                    "• **Status:** `⏳ Not Started`, `🟡 In Progress`, `✅ Completed`\n"
                    "• **Priority:** `🔴 High Priority`, `🟡 Normal Priority`, `🟢 Low Priority`\n"
                    "• **Project:** One `📁 <Project Name>` tag per project bound to this forum"
                ),
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"configuring forum tags for <#{forum.id}>", logger, ephemeral=True
            )

    async def project_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete active projects for current guild."""
        if not interaction.guild:
            return []
        try:
            projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
            choices = [
                app_commands.Choice(name=f"{p.name} ({p.prefix})", value=p.name)
                for p in projects
                if not current or current.lower() in p.name.lower() or current.lower() in p.prefix.lower()
            ]
            return choices[:25]
        except Exception as e:
            logger.exception("Error in project_autocomplete: %s", e)
            return []

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
            logger.exception("Error in team_autocomplete: %s", e)
            return []

    async def archived_project_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete archived projects for current guild."""
        if not interaction.guild:
            return []
        try:
            projects = await self.project_service.list_projects(interaction.guild.id, include_archived=True)
            archived = [p for p in projects if p.is_archived]
            choices = [
                app_commands.Choice(name=f"{p.name} ({p.prefix})", value=p.name)
                for p in archived
                if not current or current.lower() in p.name.lower() or current.lower() in p.prefix.lower()
            ]
            return choices[:25]
        except Exception as e:
            logger.exception("Error in archived_project_autocomplete: %s", e)
            return []

    @app_commands.command(name="project-set-role", description="Map or clear the squad Discord role for a project.")
    @app_commands.describe(
        project_name="Name of the project",
        role="Discord server role for the squad (leave empty to make Public / open)",
    )
    @app_commands.autocomplete(project_name=project_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_set_role(
        self,
        interaction: discord.Interaction,
        project_name: str,
        role: discord.Role | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            project = await self.project_service.get_by_name(interaction.guild.id, project_name)
            if not project:
                await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
                return

            role_id = role.id if role else None
            await self.project_service.set_project_role(project.id, role_id)

            if role:
                await interaction.followup.send(
                    f"✅ Mapped Discord role <@&{role.id}> to project **{project.name}** (`{project.prefix}`)."
                )
            else:
                await interaction.followup.send(
                    f"🌐 Cleared squad role for project **{project.name}** (`{project.prefix}`). It is now **Public**."
                )

            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"updating squad role for project '{project_name}'", logger, ephemeral=True
            )

    @app_commands.command(name="project-set-lead", description="Designate or clear the Project Lead for a project.")
    @app_commands.describe(
        project_name="Name of the project",
        lead="Discord member to designate as Project Lead (leave empty to clear)",
    )
    @app_commands.autocomplete(project_name=project_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_set_lead(
        self,
        interaction: discord.Interaction,
        project_name: str,
        lead: discord.Member | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            project = await self.project_service.get_by_name(interaction.guild.id, project_name)
            if not project:
                await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
                return

            lead_id = lead.id if lead else None
            await self.project_service.set_project_lead(project.id, lead_id)

            if lead:
                await interaction.followup.send(
                    f"👑 Designated <@{lead.id}> as the **Project Lead** for **{project.name}** (`{project.prefix}`)."
                )
            else:
                await interaction.followup.send(f"❌ Cleared Project Lead for **{project.name}** (`{project.prefix}`).")

            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"updating lead for project '{project_name}'", logger, ephemeral=True
            )

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

        await interaction.response.defer(ephemeral=True)
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
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"assigning team '{team_name}' to project '{project_name}'", logger, ephemeral=True
            )

    @app_commands.command(name="project-list", description="List all projects in this server.")
    async def project_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            projects = await self.project_service.list_projects(interaction.guild.id)
            if not projects:
                await interaction.followup.send("📁 No active projects found. Use `/project-create` to start one.")
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
                return

            from src.adapters.discord_bot.menu_manager import menu_manager
            from src.adapters.discord_bot.views.project_menu import ProjectActiveListView, build_active_projects_embed

            embed = build_active_projects_embed(projects, page=0, total_count=len(projects))
            view = ProjectActiveListView(projects, self.project_service, self.team_service, self.task_service)
            await interaction.followup.send(embed=embed, view=view)
            await menu_manager.register_menu(interaction)
        except Exception as e:
            await send_interaction_error(interaction, e, "listing projects", logger, ephemeral=True)

    @app_commands.command(name="project-archive", description="Archive a project and its associated tasks.")
    @app_commands.describe(project_name="Name of the project to archive")
    @app_commands.autocomplete(project_name=project_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_archive(self, interaction: discord.Interaction, project_name: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
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
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"archiving project '{project_name}'", logger, ephemeral=True)

    @app_commands.command(name="project-unarchive", description="Restore an archived project and its tasks.")
    @app_commands.describe(project_name="Name of the project to restore")
    @app_commands.autocomplete(project_name=archived_project_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def project_unarchive(self, interaction: discord.Interaction, project_name: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
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
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"restoring project '{project_name}'", logger, ephemeral=True)

    @app_commands.command(name="project-tree", description="Render tech-tree dependency graph for a project.")
    @app_commands.describe(
        project_name="Name of the project to visualize",
        orientation="Layout orientation: horizontal (lr) or vertical (tb)",
    )
    @app_commands.choices(
        orientation=[
            app_commands.Choice(name="Horizontal (Left to Right)", value="lr"),
            app_commands.Choice(name="Vertical (Top to Bottom)", value="tb"),
        ]
    )
    @app_commands.autocomplete(project_name=project_autocomplete)
    async def project_tree(
        self,
        interaction: discord.Interaction,
        project_name: str,
        orientation: app_commands.Choice[str] | None = None,
    ) -> None:
        if not interaction.guild or not self.task_service:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            project = await self.project_service.get_by_name(interaction.guild.id, project_name)
            if not project:
                await interaction.followup.send(f"❌ Project '{project_name}' not found.", ephemeral=True)
                return

            orient_val = orientation.value if orientation else "lr"
            buf = await self.task_service.render_project_tree(
                guild_id=interaction.guild.id,
                project_id=project.id,
                orientation=orient_val,
                member_resolver=interaction.guild,
            )
            file = discord.File(fp=buf, filename="tech_tree.png")
            orient_label = "Horizontal (Left to Right)" if orient_val == "lr" else "Vertical (Top to Bottom)"
            embed = discord.Embed(
                title=f"🌲 Tech Tree: [{project.prefix}] {project.name}",
                description=f"Showing dependency graph in **{orient_label}** layout.",
                color=discord.Color.from_rgb(16, 152, 247),
            )
            embed.set_image(url="attachment://tech_tree.png")
            from src.adapters.discord_bot.views.tree_view import TechTreeViewer

            view = TechTreeViewer(self.task_service, project, current_orientation=orient_val)
            await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"rendering tech tree for '{project_name}'", logger, ephemeral=True
            )

    @app_commands.command(name="project-menu", description="Open interactive Project Management Control Center.")
    async def project_menu(self, interaction: discord.Interaction) -> None:
        try:
            from src.adapters.discord_bot.menu_manager import menu_manager
            from src.adapters.discord_bot.views.project_menu import ProjectMenuView, build_project_menu_embed

            view = ProjectMenuView(
                self.project_service,
                self.team_service,
                self.task_service,
                initial_interaction=interaction,
            )
            embed = build_project_menu_embed(view.is_server_manager)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            await menu_manager.register_menu(interaction)
        except Exception as e:
            await send_interaction_error(interaction, e, "opening project menu", logger, ephemeral=True)
