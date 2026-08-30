import logging
import math
from collections.abc import Callable
from typing import Any
from uuid import UUID

import discord

from src.adapters.discord_bot.error_handler import send_interaction_error
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
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=60.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"creating project '{name}'", logger, ephemeral=True)


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


class ProjectSearchModal(discord.ui.Modal):
    """Modal to enter a search query for filtering projects."""

    def __init__(self, on_search_callback: Callable[[discord.Interaction, str], Any], current_query: str = ""):
        super().__init__(title="Search Projects")
        self.on_search_callback = on_search_callback

        self.query_input = discord.ui.TextInput(
            label="Project Name, Prefix, or Category",
            placeholder="e.g. INF, Security, Mobile, DevOps...",
            default=current_query,
            required=False,
            max_length=100,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = self.query_input.value.strip()
        await self.on_search_callback(interaction, query)


def build_active_projects_embed(
    projects: list[Project],
    page: int,
    total_count: int,
    query: str = "",
    page_size: int = 8,
) -> discord.Embed:
    total_pages = max(1, math.ceil(total_count / page_size))
    start_idx = page * page_size
    page_projects = projects[start_idx : start_idx + page_size]

    filter_str = f" • Filter: `{query}`" if query else ""
    embed = discord.Embed(
        title=f"📁 Active Projects ({total_count}){filter_str}",
        color=discord.Color.blurple(),
    )
    if not page_projects:
        embed.description = "*No active projects match your search.*"
        embed.set_footer(text=f"Page {page + 1} of {total_pages}")
        return embed

    for p in page_projects:
        chan_str = f"<#{p.discord_channel_id}>" if p.discord_channel_id else "No channel"
        desc_str = p.description or "No description"
        cat_str = f" • [{p.category}]" if p.category else ""
        embed.add_field(
            name=f"{p.name} (`{p.prefix}`){cat_str}",
            value=f"• Channel: {chan_str}\n• Next Task: #{p.next_task_number}\n• {desc_str}",
            inline=False,
        )
    embed.set_footer(text=f"Page {page + 1} of {total_pages} • Total: {total_count} projects")
    return embed


class ProjectActiveListView(discord.ui.View):
    """Paginated and searchable view for active projects."""

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
        current_page: int = 0,
        query: str = "",
        page_size: int = 8,
    ):
        super().__init__(timeout=180)
        self.all_projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.current_page = current_page
        self.query = query
        self.page_size = page_size
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()

    def _filter_projects(self) -> list[Project]:
        if not self.query:
            return self.all_projects
        q = self.query.lower()
        return [
            p
            for p in self.all_projects
            if q in p.name.lower() or q in p.prefix.lower() or (p.category and q in p.category.lower())
        ]

    def _rebuild_items(self) -> None:
        self.clear_items()
        total_count = len(self._filtered_projects)
        total_pages = max(1, math.ceil(total_count / self.page_size))
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        # Row 0: Search, Clear, Back
        search_btn = discord.ui.Button(
            label="Search",
            emoji="🔍",
            style=discord.ButtonStyle.primary,
            row=0,
        )
        search_btn.callback = self._on_search_clicked
        self.add_item(search_btn)

        if self.query:
            clear_btn = discord.ui.Button(
                label="Clear Filter",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            clear_btn.callback = self._on_clear_filter_clicked
            self.add_item(clear_btn)

        back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        back_btn.callback = self._on_back_clicked
        self.add_item(back_btn)

        # Row 1: Pagination buttons
        if total_pages > 1:
            prev_btn = discord.ui.Button(
                label="◀ Previous",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page <= 0),
                row=1,
            )
            prev_btn.callback = self._on_prev_clicked
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page >= total_pages - 1),
                row=1,
            )
            next_btn.callback = self._on_next_clicked
            self.add_item(next_btn)

    async def _on_search_clicked(self, interaction: discord.Interaction) -> None:
        modal = ProjectSearchModal(self._apply_search, current_query=self.query)
        await interaction.response.send_modal(modal)

    async def _apply_search(self, interaction: discord.Interaction, query: str) -> None:
        self.query = query
        self.current_page = 0
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()
        embed = build_active_projects_embed(
            self._filtered_projects, self.current_page, len(self._filtered_projects), self.query, self.page_size
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_clear_filter_clicked(self, interaction: discord.Interaction) -> None:
        self.query = ""
        self.current_page = 0
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()
        embed = build_active_projects_embed(
            self._filtered_projects, self.current_page, len(self._filtered_projects), page_size=self.page_size
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_prev_clicked(self, interaction: discord.Interaction) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self._rebuild_items()
            embed = build_active_projects_embed(
                self._filtered_projects, self.current_page, len(self._filtered_projects), self.query, self.page_size
            )
            await interaction.response.edit_message(embed=embed, view=self)

    async def _on_next_clicked(self, interaction: discord.Interaction) -> None:
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.page_size))
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._rebuild_items()
            embed = build_active_projects_embed(
                self._filtered_projects, self.current_page, len(self._filtered_projects), self.query, self.page_size
            )
            await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectArchiveConfirmView(discord.ui.View):
    """Interactive confirmation view prior to archiving a project and active tasks."""

    def __init__(
        self,
        project: Project,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.project = project
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        self.confirm_btn = discord.ui.Button(
            label="Confirm Archive",
            emoji="📦",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        self.confirm_btn.callback = self._on_confirm_clicked
        self.add_item(self.confirm_btn)

        self.cancel_btn = discord.ui.Button(
            label="Cancel",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        self.cancel_btn.callback = self._on_cancel_clicked
        self.add_item(self.cancel_btn)

    async def _on_confirm_clicked(self, interaction: discord.Interaction) -> None:
        try:
            tasks = []
            if self.task_service and interaction.guild:
                tasks, _ = await self.task_service.list_tasks(
                    guild_id=interaction.guild.id,
                    project_id=self.project.id,
                    include_archived=False,
                    limit=500,
                )

            archived = await self.project_service.archive_project(self.project.id)
            if not archived:
                archived = self.project

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
            await send_interaction_error(
                interaction, e, f"archiving project '{self.project.name}'", logger, ephemeral=True
            )

    async def _on_cancel_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectRestoreConfirmView(discord.ui.View):
    """Interactive confirmation view prior to restoring an archived project."""

    def __init__(
        self,
        project: Project,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.project = project
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        self.confirm_btn = discord.ui.Button(
            label="Confirm Restore",
            emoji="♻️",
            style=discord.ButtonStyle.success,
            row=0,
        )
        self.confirm_btn.callback = self._on_confirm_clicked
        self.add_item(self.confirm_btn)

        self.cancel_btn = discord.ui.Button(
            label="Cancel",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        self.cancel_btn.callback = self._on_cancel_clicked
        self.add_item(self.cancel_btn)

    async def _on_confirm_clicked(self, interaction: discord.Interaction) -> None:
        try:
            restored = await self.project_service.unarchive_project(self.project.id)
            if not restored:
                restored = self.project

            if self.task_service and interaction.guild and hasattr(interaction.client, "sync_task_thread"):
                restored_tasks, _ = await self.task_service.list_tasks(
                    guild_id=interaction.guild.id,
                    project_id=self.project.id,
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
            await send_interaction_error(
                interaction, e, f"restoring project '{self.project.name}'", logger, ephemeral=True
            )

    async def _on_cancel_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


def build_archive_select_embed(
    total_count: int,
    page: int,
    total_pages: int,
    query: str = "",
) -> discord.Embed:
    filter_note = f"\n🔎 **Search Filter Active:** `{query}`" if query else ""
    embed = discord.Embed(
        title="📦 Archive Project",
        description=(
            f"Select an active project below to archive:{filter_note}\n\n"
            f"• **Available Projects:** `{total_count}`\n"
            f"• **Page:** `{page + 1}` of `{total_pages}`\n\n"
            "Selecting a project will open a confirmation screen."
        ),
        color=discord.Color.orange(),
    )
    embed.set_footer(text="Use Search or Page buttons to browse larger collections.")
    return embed


class ProjectArchiveSelectView(discord.ui.View):
    """Interactive select menu to choose an active project to archive with search and pagination."""

    PAGE_SIZE = 25

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
        current_page: int = 0,
        query: str = "",
    ):
        super().__init__(timeout=120)
        self.all_projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.current_page = current_page
        self.query = query
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()

    def _filter_projects(self) -> list[Project]:
        if not self.query:
            return self.all_projects
        q = self.query.lower()
        return [
            p
            for p in self.all_projects
            if q in p.name.lower() or q in p.prefix.lower() or (p.category and q in p.category.lower())
        ]

    def _rebuild_items(self) -> None:
        self.clear_items()
        total_count = len(self._filtered_projects)
        total_pages = max(1, math.ceil(total_count / self.PAGE_SIZE))
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        start_idx = self.current_page * self.PAGE_SIZE
        page_projects = self._filtered_projects[start_idx : start_idx + self.PAGE_SIZE]

        # Row 0: Select dropdown (up to 25 options)
        if page_projects:
            options = [
                discord.SelectOption(
                    label=f"{p.name} ({p.prefix})"[:100],
                    value=str(p.id),
                    description=(p.description[:90] if p.description else "Active Project"),
                    emoji="📁",
                )
                for p in page_projects
            ]
            self.select = discord.ui.Select(
                placeholder=f"📦 Select project to archive (Page {self.current_page + 1}/{total_pages})...",
                options=options,
                min_values=1,
                max_values=1,
                row=0,
            )
            self.select.callback = self._on_select
            self.add_item(self.select)

        # Row 1: Search, Clear, Back
        search_btn = discord.ui.Button(
            label="Search",
            emoji="🔍",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        search_btn.callback = self._on_search_clicked
        self.add_item(search_btn)

        if self.query:
            clear_btn = discord.ui.Button(
                label="Clear Filter",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            clear_btn.callback = self._on_clear_filter_clicked
            self.add_item(clear_btn)

        back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back_btn.callback = self._on_back_clicked
        self.add_item(back_btn)

        # Row 2: Pagination (if > 1 page)
        if total_pages > 1:
            prev_btn = discord.ui.Button(
                label="◀ Previous",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page <= 0),
                row=2,
            )
            prev_btn.callback = self._on_prev_clicked
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page >= total_pages - 1),
                row=2,
            )
            next_btn.callback = self._on_next_clicked
            self.add_item(next_btn)

    async def _on_search_clicked(self, interaction: discord.Interaction) -> None:
        modal = ProjectSearchModal(self._apply_search, current_query=self.query)
        await interaction.response.send_modal(modal)

    async def _apply_search(self, interaction: discord.Interaction, query: str) -> None:
        self.query = query
        self.current_page = 0
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
        embed = build_archive_select_embed(len(self._filtered_projects), self.current_page, total_pages, self.query)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_clear_filter_clicked(self, interaction: discord.Interaction) -> None:
        self.query = ""
        self.current_page = 0
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
        embed = build_archive_select_embed(len(self._filtered_projects), self.current_page, total_pages)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_prev_clicked(self, interaction: discord.Interaction) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self._rebuild_items()
            total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
            embed = build_archive_select_embed(len(self._filtered_projects), self.current_page, total_pages, self.query)
            await interaction.response.edit_message(embed=embed, view=self)

    async def _on_next_clicked(self, interaction: discord.Interaction) -> None:
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._rebuild_items()
            embed = build_archive_select_embed(len(self._filtered_projects), self.current_page, total_pages, self.query)
            await interaction.response.edit_message(embed=embed, view=self)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id = UUID(self.select.values[0])
        project = next((p for p in self.all_projects if p.id == project_id), None)
        if not project and interaction.guild:
            project = await self.project_service.get_by_id(project_id)

        if not project:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        task_count_note = ""
        if self.task_service and interaction.guild:
            _tasks, total_tasks = await self.task_service.list_tasks(
                guild_id=interaction.guild.id,
                project_id=project_id,
                include_archived=False,
                limit=500,
            )
            task_count_note = f"\n• **Active Tasks:** `{total_tasks}` task(s) will be archived."

        chan_note = f"\n• **Channel:** <#{project.discord_channel_id}>" if project.discord_channel_id else ""

        embed = discord.Embed(
            title="⚠️ Confirm Project Archival",
            description=(
                f"Are you sure you want to archive project **{project.name} (`{project.prefix}`)**?\n"
                f"{chan_note}"
                f"{task_count_note}\n"
                "• **Discord Threads:** Associated task discussion threads will be archived.\n\n"
                "⚠️ This will hide the project from active selectors and board views."
            ),
            color=discord.Color.red(),
        )
        embed.set_footer(text="Click 'Confirm Archive' to execute or 'Cancel' to abort.")

        view = ProjectArchiveConfirmView(
            project=project,
            project_service=self.project_service,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        embed = build_project_menu_embed()
        await interaction.response.edit_message(content=None, embed=embed, view=view)


def build_restore_select_embed(
    total_count: int,
    page: int,
    total_pages: int,
    query: str = "",
) -> discord.Embed:
    filter_note = f"\n🔎 **Search Filter Active:** `{query}`" if query else ""
    embed = discord.Embed(
        title="♻️ Restore Project",
        description=(
            f"Select an archived project below to restore:{filter_note}\n\n"
            f"• **Archived Projects Available:** `{total_count}`\n"
            f"• **Page:** `{page + 1}` of `{total_pages}`\n\n"
            "Selecting a project will open a confirmation screen."
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Use Search or Page buttons to browse larger collections.")
    return embed


class ProjectRestoreSelectView(discord.ui.View):
    """Interactive select menu to choose an archived project to restore with search and pagination."""

    PAGE_SIZE = 25

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
        current_page: int = 0,
        query: str = "",
    ):
        super().__init__(timeout=120)
        self.all_projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.current_page = current_page
        self.query = query
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()

    def _filter_projects(self) -> list[Project]:
        if not self.query:
            return self.all_projects
        q = self.query.lower()
        return [
            p
            for p in self.all_projects
            if q in p.name.lower() or q in p.prefix.lower() or (p.category and q in p.category.lower())
        ]

    def _rebuild_items(self) -> None:
        self.clear_items()
        total_count = len(self._filtered_projects)
        total_pages = max(1, math.ceil(total_count / self.PAGE_SIZE))
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        start_idx = self.current_page * self.PAGE_SIZE
        page_projects = self._filtered_projects[start_idx : start_idx + self.PAGE_SIZE]

        # Row 0: Select dropdown (up to 25 options)
        if page_projects:
            options = [
                discord.SelectOption(
                    label=f"{p.name} ({p.prefix})"[:100],
                    value=str(p.id),
                    description=(p.description[:90] if p.description else "Archived Project"),
                    emoji="♻️",
                )
                for p in page_projects
            ]
            self.select = discord.ui.Select(
                placeholder=f"♻️ Select project to restore (Page {self.current_page + 1}/{total_pages})...",
                options=options,
                min_values=1,
                max_values=1,
                row=0,
            )
            self.select.callback = self._on_select
            self.add_item(self.select)

        # Row 1: Search, Clear, Back
        search_btn = discord.ui.Button(
            label="Search",
            emoji="🔍",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        search_btn.callback = self._on_search_clicked
        self.add_item(search_btn)

        if self.query:
            clear_btn = discord.ui.Button(
                label="Clear Filter",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            clear_btn.callback = self._on_clear_filter_clicked
            self.add_item(clear_btn)

        back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back_btn.callback = self._on_back_clicked
        self.add_item(back_btn)

        # Row 2: Pagination (if > 1 page)
        if total_pages > 1:
            prev_btn = discord.ui.Button(
                label="◀ Previous",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page <= 0),
                row=2,
            )
            prev_btn.callback = self._on_prev_clicked
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page >= total_pages - 1),
                row=2,
            )
            next_btn.callback = self._on_next_clicked
            self.add_item(next_btn)

    async def _on_search_clicked(self, interaction: discord.Interaction) -> None:
        modal = ProjectSearchModal(self._apply_search, current_query=self.query)
        await interaction.response.send_modal(modal)

    async def _apply_search(self, interaction: discord.Interaction, query: str) -> None:
        self.query = query
        self.current_page = 0
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
        embed = build_restore_select_embed(len(self._filtered_projects), self.current_page, total_pages, self.query)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_clear_filter_clicked(self, interaction: discord.Interaction) -> None:
        self.query = ""
        self.current_page = 0
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
        embed = build_restore_select_embed(len(self._filtered_projects), self.current_page, total_pages)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_prev_clicked(self, interaction: discord.Interaction) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self._rebuild_items()
            total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
            embed = build_restore_select_embed(len(self._filtered_projects), self.current_page, total_pages, self.query)
            await interaction.response.edit_message(embed=embed, view=self)

    async def _on_next_clicked(self, interaction: discord.Interaction) -> None:
        total_pages = max(1, math.ceil(len(self._filtered_projects) / self.PAGE_SIZE))
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._rebuild_items()
            embed = build_restore_select_embed(len(self._filtered_projects), self.current_page, total_pages, self.query)
            await interaction.response.edit_message(embed=embed, view=self)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        project_id = UUID(self.select.values[0])
        project = next((p for p in self.all_projects if p.id == project_id), None)
        if not project and interaction.guild:
            project = await self.project_service.get_by_id(project_id)

        if not project:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        chan_note = f"\n• **Bound Channel:** <#{project.discord_channel_id}>" if project.discord_channel_id else ""

        embed = discord.Embed(
            title="♻️ Confirm Project Restoration",
            description=(
                f"Are you sure you want to restore project **{project.name} (`{project.prefix}`)**?\n"
                f"{chan_note}\n"
                "• **Project Status:** Reactivated and visible across project selectors.\n"
                "• **Active Tasks:** Incomplete tasks will be unarchived.\n"
                "• **Discord Threads:** Associated task threads will be reopened."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Click 'Confirm Restore' to execute or 'Cancel' to abort.")

        view = ProjectRestoreConfirmView(
            project=project,
            project_service=self.project_service,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)

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
            await send_interaction_error(
                interaction,
                e,
                f"assigning team '{self.team.name}' to project '{self.project.name}'",
                logger,
                ephemeral=True,
            )


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
            await send_interaction_error(
                interaction, e, f"assigning team '{team.name}' to project '{proj.name}'", logger, ephemeral=True
            )

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

        embed = build_active_projects_embed(projects, page=0, total_count=len(projects))
        view = ProjectActiveListView(projects, self.project_service, self.team_service, self.task_service)
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
        total_pages = max(1, math.ceil(len(projects) / ProjectArchiveSelectView.PAGE_SIZE))
        embed = build_archive_select_embed(len(projects), 0, total_pages)
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
        total_pages = max(1, math.ceil(len(archived) / ProjectRestoreSelectView.PAGE_SIZE))
        embed = build_restore_select_embed(len(archived), 0, total_pages)
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
