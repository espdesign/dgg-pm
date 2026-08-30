import logging
from uuid import UUID

import discord

from src.domain.models import Project
from src.services.project_service import ProjectService
from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.views.project_menu")


class ProjectCreateModal(discord.ui.Modal):
    def __init__(self, project_service: ProjectService, channel: discord.TextChannel | discord.Thread):
        super().__init__(title="Create New Project")
        self.project_service = project_service
        self.channel = channel

        self.name_input = discord.ui.TextInput(
            label="Project Name",
            placeholder="e.g. Mobile App Redesign, Infrastructure V2",
            required=True,
            max_length=100,
        )
        self.add_item(self.name_input)

        self.prefix_input = discord.ui.TextInput(
            label="Key Prefix (Optional, 2-5 uppercase chars)",
            placeholder="e.g. MOB, INF (Leave empty for auto-generated)",
            required=False,
            max_length=10,
        )
        self.add_item(self.prefix_input)

        self.desc_input = discord.ui.TextInput(
            label="Description (Optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Mission statement, architecture goals, or deliverables...",
            required=False,
            max_length=1000,
        )
        self.add_item(self.desc_input)

        self.cat_input = discord.ui.TextInput(
            label="Category (Optional)",
            placeholder="e.g. Engineering, Marketing, Operations",
            required=False,
            max_length=50,
        )
        self.add_item(self.cat_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This action must be run in a Discord server.", ephemeral=True)
            return

        name = self.name_input.value.strip()
        prefix = self.prefix_input.value.strip() or None
        desc = self.desc_input.value.strip() or None
        cat = self.cat_input.value.strip() or None

        try:
            project = await self.project_service.create_project(
                guild_id=interaction.guild.id,
                name=name,
                prefix=prefix,
                description=desc,
                discord_channel_id=self.channel.id,
                category=cat,
            )
            embed = discord.Embed(
                title=f"✅ Project Created: {project.name} (`{project.prefix}`)",
                description=project.description or "No description provided.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Bound Channel", value=f"<#{project.discord_channel_id}>", inline=True)
            if project.category:
                embed.add_field(name="Category", value=project.category, inline=True)
            embed.set_footer(text=f"Project ID: {project.id}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.exception("Error creating project via modal: %s", e)
            await interaction.response.send_message(f"❌ Failed to create project: {e}", ephemeral=True)


class ProjectArchiveSelectView(discord.ui.View):
    """Interactive select menu to archive an active project."""

    def __init__(self, projects: list[Project], project_service: ProjectService):
        super().__init__(timeout=120)
        self.project_service = project_service

        options = [
            discord.SelectOption(
                label=f"{p.name} ({p.prefix})",
                value=str(p.id),
                description=(p.description[:90] if p.description else "Active Project"),
                emoji="📁",
            )
            for p in projects[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="📦 Select project to archive...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id = UUID(self.select.values[0])
        try:
            archived = await self.project_service.archive_project(project_id)
            msg = f"📦 Project **{archived.name} (`{archived.prefix}`)** and its active tasks have been archived."
            await interaction.response.edit_message(content=msg, view=None)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to archive project: {e}", ephemeral=True)


class ProjectRestoreSelectView(discord.ui.View):
    """Interactive select menu to restore an archived project."""

    def __init__(self, projects: list[Project], project_service: ProjectService):
        super().__init__(timeout=120)
        self.project_service = project_service

        options = [
            discord.SelectOption(
                label=f"{p.name} ({p.prefix})",
                value=str(p.id),
                description="Archived Project",
                emoji="♻️",
            )
            for p in projects[:25]
        ]
        self.select = discord.ui.Select(
            placeholder="♻️ Select project to restore...",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id = UUID(self.select.values[0])
        try:
            restored = await self.project_service.unarchive_project(project_id)
            await interaction.response.edit_message(
                content=f"♻️ Project **{restored.name} (`{restored.prefix}`)** has been restored.",
                view=None,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to restore project: {e}", ephemeral=True)


class ProjectMenuView(discord.ui.View):
    """Control Center View for Project Operations."""

    def __init__(self, project_service: ProjectService, team_service: TeamService):
        super().__init__(timeout=None)
        self.project_service = project_service
        self.team_service = team_service

    @discord.ui.button(label="New Project", emoji="➕", style=discord.ButtonStyle.primary, row=0)
    async def new_project_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Must be run in a guild text channel.", ephemeral=True)
            return
        modal = ProjectCreateModal(self.project_service, channel=interaction.channel)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Active Projects", emoji="📋", style=discord.ButtonStyle.secondary, row=0)
    async def list_projects_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message("📁 No active projects found in this server.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📁 Active Projects ({len(projects)})",
            color=discord.Color.blurple(),
        )
        for p in projects:
            chan_str = f"<#{p.discord_channel_id}>" if p.discord_channel_id else "No channel"
            desc_str = p.description or "No description"
            embed.add_field(
                name=f"{p.name} (`{p.prefix}`)",
                value=f"• Channel: {chan_str}\n• Next Task: #{p.next_task_number}\n• {desc_str}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Archive Project", emoji="📦", style=discord.ButtonStyle.secondary, row=0)
    async def archive_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message("📁 No active projects available to archive.", ephemeral=True)
            return
        view = ProjectArchiveSelectView(projects, self.project_service)
        await interaction.response.send_message("Select an active project to archive:", view=view, ephemeral=True)

    @discord.ui.button(label="Restore Project", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def restore_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        all_proj = await self.project_service.list_projects(interaction.guild.id, include_archived=True)
        archived = [p for p in all_proj if p.is_archived]
        if not archived:
            await interaction.response.send_message("📁 No archived projects to restore.", ephemeral=True)
            return
        view = ProjectRestoreSelectView(archived, self.project_service)
        await interaction.response.send_message("Select an archived project to restore:", view=view, ephemeral=True)


def build_project_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📁 Project Management Control Center",
        description=(
            "Manage project containers, channel bindings, and project lifecycles without typing commands.\n\n"
            "• **`➕ New Project`**: Create a project container bound to the current channel\n"
            "• **`📋 Active Projects`**: View all running projects and key prefixes\n"
            "• **`📦 Archive Project`**: Soft-delete a completed project\n"
            "• **`♻️ Restore Project`**: Bring back an archived project"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="dgg-pm • Zero-typing project management")
    return embed
