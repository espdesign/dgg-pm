import logging
from uuid import UUID

import discord

from src.adapters.discord_bot.views.forum_helpers import setup_forum_tags
from src.domain.enums import TaskStatus
from src.domain.models import Project, Team
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.views.project_menu")


class ProjectCreateModal(discord.ui.Modal):
    def __init__(
        self, project_service: ProjectService, channel: discord.ForumChannel | discord.TextChannel | discord.Thread
    ):
        raw_name = getattr(channel, "name", None)
        if isinstance(raw_name, str) and raw_name.strip():
            chan_name = raw_name.strip()
        elif hasattr(channel, "id"):
            chan_name = str(channel.id)
        else:
            chan_name = "channel"

        is_forum = isinstance(channel, discord.ForumChannel)
        type_prefix = "Forum" if is_forum else "Channel"

        # Max title length in Discord modal is 45 characters
        title_str = f"New Project in #{chan_name}"
        if len(title_str) > 45:
            title_str = title_str[:42] + "..."

        super().__init__(title=title_str)
        self.project_service = project_service
        self.channel = channel

        name_label = f"Project Name ({type_prefix} #{chan_name})"
        if len(name_label) > 45:
            name_label = name_label[:42] + "..."

        name_placeholder = f"e.g. Mobile Redesign (bound to #{chan_name})"
        if len(name_placeholder) > 100:
            name_placeholder = name_placeholder[:97] + "..."

        self.name_input = discord.ui.TextInput(
            label=name_label,
            placeholder=name_placeholder,
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
            is_forum = isinstance(self.channel, discord.ForumChannel)
            chan_type_label = "Forum Post Board" if is_forum else "Text Channel"
            tag_note = ""

            if is_forum:
                tags_added, _total_tags, tag_err = await setup_forum_tags(self.channel)
                if tags_added > 0:
                    tag_note = f" • Setup {tags_added} PM tags"
                elif tag_err:
                    tag_note = f" • ⚠️ {tag_err}"

            embed = discord.Embed(
                title=f"✅ Project Created: {project.name} (`{project.prefix}`)",
                description=project.description or "No description provided.",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Bound Channel",
                value=f"<#{project.discord_channel_id}> ({chan_type_label}{tag_note})",
                inline=True,
            )
            if project.category:
                embed.add_field(name="Category", value=project.category, inline=True)
            embed.set_footer(text=f"Project ID: {project.id}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.exception("Error creating project via modal: %s", e)
            await interaction.response.send_message(f"❌ Failed to create project: {e}", ephemeral=True)


class ProjectChannelSelectView(discord.ui.View):
    """Interactive view allowing the user to select any Forum or Text channel for a new project."""

    def __init__(
        self,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        # Row 0: Channel Select dropdown
        self.channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.forum, discord.ChannelType.text],
            placeholder="📢 Select target Forum or Text channel...",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.channel_select.callback = self._on_channel_selected
        self.add_item(self.channel_select)

        # Row 1: Quick button to use current channel
        self.current_chan_btn = discord.ui.Button(
            label="Use Current Channel",
            emoji="📍",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        self.current_chan_btn.callback = self._on_current_channel_clicked
        self.add_item(self.current_chan_btn)

        # Row 1: Back button
        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_channel_selected(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        selected = self.channel_select.values[0]
        chan = interaction.guild.get_channel(selected.id) if hasattr(selected, "id") else selected
        if not chan or not isinstance(chan, (discord.ForumChannel, discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Invalid channel selected.", ephemeral=True)
            return

        modal = ProjectCreateModal(self.project_service, channel=chan)
        await interaction.response.send_modal(modal)

    async def _on_current_channel_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(
            interaction.channel, (discord.ForumChannel, discord.TextChannel, discord.Thread)
        ):
            await interaction.response.send_message(
                "❌ Current channel must be a Forum or Text channel.", ephemeral=True
            )
            return
        modal = ProjectCreateModal(self.project_service, channel=interaction.channel)
        await interaction.response.send_modal(modal)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectActiveListView(discord.ui.View):
    """View displaying active projects with a Back button."""

    def __init__(
        self,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectArchiveSelectView(discord.ui.View):
    """Interactive select menu to archive an active project."""

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

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
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id = UUID(self.select.values[0])
        try:
            tasks = []
            if self.task_service and interaction.guild:
                tasks, _ = await self.task_service.list_tasks(
                    guild_id=interaction.guild.id,
                    project_id=project_id,
                    include_archived=False,
                    limit=500,
                )

            archived = await self.project_service.archive_project(project_id)

            if hasattr(interaction.client, "sync_task_thread"):
                for t in tasks:
                    if t.discord_thread_id:
                        await interaction.client.sync_task_thread(t, action="archive")

            view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
            embed = build_project_menu_embed()
            embed.description = (
                f"📦 **Project Archived!**\n"
                f"Project **{archived.name} (`{archived.prefix}`)** and its active tasks have been archived.\n\n"
                + (embed.description or "")
            )
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to archive project: {e}", ephemeral=True)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectRestoreSelectView(discord.ui.View):
    """Interactive select menu to restore an archived project."""

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

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
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id = UUID(self.select.values[0])
        try:
            restored = await self.project_service.unarchive_project(project_id)

            if self.task_service and interaction.guild and hasattr(interaction.client, "sync_task_thread"):
                restored_tasks, _ = await self.task_service.list_tasks(
                    guild_id=interaction.guild.id,
                    project_id=project_id,
                    include_archived=False,
                    limit=500,
                )
                for t in restored_tasks:
                    if t.discord_thread_id and t.status != TaskStatus.COMPLETED:
                        await interaction.client.sync_task_thread(t, action="unarchive")

            view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
            embed = build_project_menu_embed()
            embed.description = (
                f"♻️ **Project Restored!**\n"
                f"Project **{restored.name} (`{restored.prefix}`)** has been reactivated.\n\n"
                + (embed.description or "")
            )
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to restore project: {e}", ephemeral=True)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectAssignTimelineModal(discord.ui.Modal):
    """Modal to specify timeline when assigning a team to a project."""

    def __init__(
        self,
        project_service: ProjectService,
        project: Project,
        team: Team,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(title=f"Assign Team to [{project.prefix}]"[:45])
        self.project_service = project_service
        self.project = project
        self.team = team
        self.team_service = team_service
        self.task_service = task_service

        self.timeline_input = discord.ui.TextInput(
            label="Target Timeline (Optional)",
            placeholder="e.g. Q3 2026, 6 weeks, Sprint 1-4",
            required=False,
            max_length=100,
        )
        self.add_item(self.timeline_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        timeline = self.timeline_input.value.strip() or None
        try:
            await self.project_service.assign_team_to_project(
                project_id=self.project.id,
                team_id=self.team.id,
                timeline=timeline,
            )
            embed = discord.Embed(
                title="✅ Team Mapped to Project",
                description=(
                    f"Successfully mapped team **{self.team.name}** (<@&{self.team.discord_role_id}>) "
                    f"to project **{self.project.name}** (`{self.project.prefix}`)."
                    + (f"\n\n• **Target Timeline:** `{timeline}`" if timeline else "")
                ),
                color=discord.Color.green(),
            )
            view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            logger.exception("Error assigning team to project via modal: %s", e)
            await interaction.response.send_message(f"❌ Failed to assign team: {e}", ephemeral=True)


class ProjectAssignTeamView(discord.ui.View):
    """Interactive view to map a team to a project with optional timeline."""

    def __init__(
        self,
        projects: list[Project],
        teams: list[Team],
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.projects = projects
        self.teams = teams
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        self.selected_project_id: UUID = projects[0].id
        self.selected_team_id: UUID = teams[0].id

        # Row 0: Select Project
        proj_options = [
            discord.SelectOption(
                label=f"{p.name} ({p.prefix})"[:100],
                value=str(p.id),
                description=(p.description[:50] if p.description else "Active Project"),
                emoji="📁",
                default=(i == 0),
            )
            for i, p in enumerate(projects[:25])
        ]
        self.proj_select = discord.ui.Select(
            placeholder="📁 Select Project...",
            options=proj_options,
            min_values=1,
            max_values=1,
            row=0,
        )
        self.proj_select.callback = self._on_project_changed
        self.add_item(self.proj_select)

        # Row 1: Select Team
        team_options = [
            discord.SelectOption(
                label=t.name[:100],
                value=str(t.id),
                description=f"Discord Role: @{t.discord_role_id}"[:50],
                emoji="👥",
                default=(i == 0),
            )
            for i, t in enumerate(teams[:25])
        ]
        self.team_select = discord.ui.Select(
            placeholder="👥 Select Team...",
            options=team_options,
            min_values=1,
            max_values=1,
            row=1,
        )
        self.team_select.callback = self._on_team_changed
        self.add_item(self.team_select)

        # Row 2: Action Buttons
        self.assign_btn = discord.ui.Button(
            label="Map Team (Quick)",
            emoji="🤝",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        self.assign_btn.callback = self._on_assign_quick_clicked
        self.add_item(self.assign_btn)

        self.timeline_btn = discord.ui.Button(
            label="Set Timeline & Map...",
            emoji="⏱️",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        self.timeline_btn.callback = self._on_timeline_clicked
        self.add_item(self.timeline_btn)

        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        self.back_btn.callback = self._on_back_clicked
        self.add_item(self.back_btn)

    def _get_selected_project(self) -> Project | None:
        return next((p for p in self.projects if p.id == self.selected_project_id), None)

    def _get_selected_team(self) -> Team | None:
        return next((t for t in self.teams if t.id == self.selected_team_id), None)

    async def _on_project_changed(self, interaction: discord.Interaction) -> None:
        self.selected_project_id = UUID(self.proj_select.values[0])
        for opt in self.proj_select.options:
            opt.default = opt.value == str(self.selected_project_id)
        await interaction.response.edit_message(view=self)

    async def _on_team_changed(self, interaction: discord.Interaction) -> None:
        self.selected_team_id = UUID(self.team_select.values[0])
        for opt in self.team_select.options:
            opt.default = opt.value == str(self.selected_team_id)
        await interaction.response.edit_message(view=self)

    async def _on_assign_quick_clicked(self, interaction: discord.Interaction) -> None:
        proj = self._get_selected_project()
        team = self._get_selected_team()
        if not proj or not team:
            await interaction.response.send_message("❌ Selection error.", ephemeral=True)
            return

        try:
            await self.project_service.assign_team_to_project(
                project_id=proj.id,
                team_id=team.id,
                timeline=None,
            )
            embed = discord.Embed(
                title="✅ Team Mapped to Project",
                description=(
                    f"Successfully mapped team **{team.name}** (<@&{team.discord_role_id}>) "
                    f"to project **{proj.name}** (`{proj.prefix}`)."
                ),
                color=discord.Color.green(),
            )
            view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            logger.exception("Error assigning team to project: %s", e)
            await interaction.response.send_message(f"❌ Failed to assign team: {e}", ephemeral=True)

    async def _on_timeline_clicked(self, interaction: discord.Interaction) -> None:
        proj = self._get_selected_project()
        team = self._get_selected_team()
        if not proj or not team:
            await interaction.response.send_message("❌ Selection error.", ephemeral=True)
            return

        modal = ProjectAssignTimelineModal(
            project_service=self.project_service,
            project=proj,
            team=team,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        await interaction.response.send_modal(modal)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectMenuView(discord.ui.View):
    """Control Center View for Project Operations."""

    def __init__(
        self,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=None)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        if self.task_service:
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

        if self.task_service:
            view = PmHubView(self.project_service, self.team_service, self.task_service)
            embed = build_hub_welcome_embed()
            await interaction.response.edit_message(content=None, embed=embed, view=view)

    @discord.ui.button(label="New Project", emoji="➕", style=discord.ButtonStyle.primary, row=0)
    async def new_project_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be run in a Discord server.", ephemeral=True)
            return
        view = ProjectChannelSelectView(self.project_service, self.team_service, self.task_service)
        embed = discord.Embed(
            title="📁 Create Project: Select Channel / Forum",
            description=(
                "Choose a **Forum Channel** (recommended) or **Text Channel** to bind as the project's task board.\n\n"
                "• **Forum Channel**: Tasks become organized forum post cards with native Discord tag filtering.\n"
                "• **Text Channel**: Tasks are posted as embeds with discussion threads."
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)

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
        view = ProjectActiveListView(self.project_service, self.team_service, self.task_service)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Assign Team", emoji="🤝", style=discord.ButtonStyle.secondary, row=0)
    async def assign_team_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message(
                "📁 No active projects found. Create a project first!", ephemeral=True
            )
            return
        teams = await self.team_service.list_teams(interaction.guild.id)
        if not teams:
            await interaction.response.send_message(
                "👥 No teams found. Create a team in `/team-menu` first!", ephemeral=True
            )
            return
        view = ProjectAssignTeamView(projects, teams, self.project_service, self.team_service, self.task_service)
        embed = discord.Embed(
            title="🤝 Map Team to Project",
            description="Select a project and a functional team container to map together:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Archive Project", emoji="📦", style=discord.ButtonStyle.secondary, row=1)
    async def archive_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message("📁 No active projects available to archive.", ephemeral=True)
            return
        view = ProjectArchiveSelectView(projects, self.project_service, self.team_service, self.task_service)
        embed = discord.Embed(
            title="📦 Archive Project",
            description="Select an active project below to archive:",
            color=discord.Color.orange(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Restore Project", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def restore_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        all_proj = await self.project_service.list_projects(interaction.guild.id, include_archived=True)
        archived = [p for p in all_proj if p.is_archived]
        if not archived:
            await interaction.response.send_message("📁 No archived projects to restore.", ephemeral=True)
            return
        view = ProjectRestoreSelectView(archived, self.project_service, self.team_service, self.task_service)
        embed = discord.Embed(
            title="♻️ Restore Project",
            description="Select an archived project below to restore:",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=view)


def build_project_menu_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📁 Project Management Control Center",
        description=(
            "Manage project containers, channel bindings, and team assignments without typing commands.\n\n"
            "• **`➕ New Project`**: Create a project container bound to any Forum or Text channel\n"
            "• **`📋 Active Projects`**: View all running projects and key prefixes\n"
            "• **`🤝 Assign Team`**: Map a functional team to a project container (with optional timeline)\n"
            "• **`📦 Archive Project`**: Soft-delete a completed project\n"
            "• **`♻️ Restore Project`**: Bring back an archived project"
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="dgg-pm • Zero-typing project management")
    return embed
