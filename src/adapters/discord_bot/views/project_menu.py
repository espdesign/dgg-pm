import logging
import math
from collections.abc import Callable
from typing import Any
from uuid import UUID

import discord

from src.adapters.discord_bot.error_handler import send_interaction_error
from src.adapters.discord_bot.views.forum_helpers import ensure_pinned_hub_post, ensure_project_tag, setup_forum_tags
from src.domain.enums import TaskStatus
from src.domain.models import Project, Team
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.views.project_menu")


def build_project_draft_embed(
    name: str,
    channel: discord.ForumChannel | discord.TextChannel | discord.Thread,
    prefix: str | None = None,
    description: str | None = None,
    category: str | None = None,
    role: discord.Role | None = None,
    lead: discord.Member | discord.User | None = None,
) -> discord.Embed:
    """Builds a live preview embed of the project currently being configured in the builder."""
    is_forum = isinstance(channel, discord.ForumChannel)
    chan_type = "Forum Post Board" if is_forum else "Text Channel"
    chan_name = getattr(channel, "name", str(getattr(channel, "id", "channel")))

    role_display = f"<@&{role.id}>" if role else "⚠️ **Required** — *Select a Squad Role below*"
    lead_display = f"<@{lead.id}>" if lead else "*Unassigned (Optional)*"
    prefix_display = f"`{prefix}`" if prefix else "*Auto-generated*"
    cat_display = category if category else "*None*"

    embed = discord.Embed(
        title=f"📁 Project Setup: {name[:90]}",
        description=(
            "Configure the contributor squad role and optional project lead using the pickers below, "
            "then click **`🚀 Create Project`** to initialize.\n\n"
            f"• **Bound Channel**: <#{channel.id}> (`#{chan_name}` • {chan_type})\n"
            f"• **Key Prefix**: {prefix_display}\n"
            f"• **Squad Role (Required)**: {role_display}\n"
            f"• **Project Lead (Optional)**: {lead_display}\n"
            f"• **Category**: {cat_display}"
        ),
        color=discord.Color.blurple(),
    )
    if description:
        embed.add_field(
            name="Description / Mission",
            value=description[:1000] + ("..." if len(description) > 1000 else ""),
            inline=False,
        )
    embed.set_footer(text="dgg-pm • Interactive Project Creation Builder")
    return embed


class ProjectCreateDraftView(discord.ui.View):
    """Interactive multi-step Project Creation Builder (Role & Lead picker).

    Allows users to select a required Squad Discord Role and an optional Project Lead
    prior to creating the project container and binding the channel/forum.
    """

    def __init__(
        self,
        project_service: ProjectService,
        channel: discord.ForumChannel | discord.TextChannel | discord.Thread,
        name: str,
        prefix: str | None = None,
        description: str | None = None,
        category: str | None = None,
        role: discord.Role | None = None,
        lead: discord.Member | discord.User | None = None,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
        user_service: Any = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=300)
        self.project_service = project_service
        self.channel = channel
        self.name = name
        self.prefix = prefix
        self.description = description
        self.category = category
        self.role = role
        self.lead = lead
        self.team_service = team_service
        self.task_service = task_service
        self.user_service = user_service
        self._initial_interaction = initial_interaction

        self._rebuild_items()

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

    def _rebuild_items(self) -> None:
        self.clear_items()

        # Row 0: Select Discord Role (Required)
        self.role_select = discord.ui.RoleSelect(
            placeholder="🎭 Select Squad Role (Required)...",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.role_select.callback = self._on_role_selected
        self.add_item(self.role_select)

        # Row 1: Select Project Lead User (Optional)
        self.lead_select = discord.ui.UserSelect(
            placeholder="👑 Select Project Lead (Optional)...",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.lead_select.callback = self._on_lead_selected
        self.add_item(self.lead_select)

        # Row 2: Action Buttons
        self.create_btn = discord.ui.Button(
            label="Create Project",
            emoji="🚀",
            style=discord.ButtonStyle.success,
            row=2,
        )
        self.create_btn.callback = self._on_confirm_clicked
        self.add_item(self.create_btn)

        if self.lead:
            self.clear_lead_btn = discord.ui.Button(
                label="Clear Lead",
                emoji="👑",
                style=discord.ButtonStyle.secondary,
                row=2,
            )
            self.clear_lead_btn.callback = self._on_clear_lead_clicked
            self.add_item(self.clear_lead_btn)

        self.edit_btn = discord.ui.Button(
            label="Edit Details",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        self.edit_btn.callback = self._on_edit_details_clicked
        self.add_item(self.edit_btn)

        self.cancel_btn = discord.ui.Button(
            label="Cancel",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            row=2,
        )
        self.cancel_btn.callback = self._on_cancel_clicked
        self.add_item(self.cancel_btn)

    async def _on_role_selected(self, interaction: discord.Interaction) -> None:
        self.role = self.role_select.values[0]
        self._rebuild_items()
        embed = build_project_draft_embed(
            name=self.name,
            channel=self.channel,
            prefix=self.prefix,
            description=self.description,
            category=self.category,
            role=self.role,
            lead=self.lead,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_lead_selected(self, interaction: discord.Interaction) -> None:
        self.lead = self.lead_select.values[0]
        self._rebuild_items()
        embed = build_project_draft_embed(
            name=self.name,
            channel=self.channel,
            prefix=self.prefix,
            description=self.description,
            category=self.category,
            role=self.role,
            lead=self.lead,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_clear_lead_clicked(self, interaction: discord.Interaction) -> None:
        self.lead = None
        self._rebuild_items()
        embed = build_project_draft_embed(
            name=self.name,
            channel=self.channel,
            prefix=self.prefix,
            description=self.description,
            category=self.category,
            role=self.role,
            lead=self.lead,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_edit_details_clicked(self, interaction: discord.Interaction) -> None:
        modal = ProjectCreateModal(
            project_service=self.project_service,
            channel=self.channel,
            team_service=self.team_service,
            task_service=self.task_service,
            user_service=self.user_service,
            draft_view=self,
            initial_name=self.name,
            initial_prefix=self.prefix or "",
            initial_desc=self.description or "",
            initial_cat=self.category or "",
        )
        await interaction.response.send_modal(modal)

    async def _on_cancel_clicked(self, interaction: discord.Interaction) -> None:
        try:
            embed = discord.Embed(
                title="🚫 Project Creation Cancelled",
                description="Project draft was discarded.",
                color=discord.Color.dark_grey(),
            )
            await interaction.response.edit_message(embed=embed, view=None)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=3.0)
        except Exception as e:
            logger.debug("Error cancelling project draft: %s", e)

    async def _on_confirm_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This action must be run in a Discord server.", ephemeral=True)
            return

        if not self.role:
            await interaction.response.send_message(
                "❌ **Squad Role Required**: Please select a contributor Discord role "
                "from the dropdown before creating the project.",
                ephemeral=True,
            )
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        try:
            project = await self.project_service.create_project(
                guild_id=interaction.guild.id,
                name=self.name,
                prefix=self.prefix,
                description=self.description,
                discord_channel_id=self.channel.id,
                discord_role_id=self.role.id,
                lead_discord_id=self.lead.id if self.lead else None,
                category=self.category,
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
                proj_tag_err = await ensure_project_tag(self.channel, project.name)
                if proj_tag_err:
                    tag_note += f" • ⚠️ {proj_tag_err}"

            hub_ok, _hub_status = await ensure_pinned_hub_post(
                channel=self.channel,
                project_service=self.project_service,
                team_service=self.team_service,
                task_service=self.task_service,
                user_service=self.user_service,
                project_name=project.name,
            )
            if hub_ok:
                tag_note += " • 📌 Pinned Control Hub created"

            lead_str = f"<@{project.lead_discord_id}>" if project.lead_discord_id else "*Unassigned*"
            role_str = f"<@&{project.discord_role_id}>" if project.discord_role_id else "*None*"

            embed = discord.Embed(
                title=f"✅ Project Created: {project.name} (`{project.prefix}`)",
                description=project.description or "No description provided.",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Bound Channel",
                value=f"<#{project.discord_channel_id}> ({chan_type_label}{tag_note})",
                inline=False,
            )
            embed.add_field(name="Squad Role", value=role_str, inline=True)
            embed.add_field(name="Project Lead", value=lead_str, inline=True)
            if project.category:
                embed.add_field(name="Category", value=project.category, inline=True)
            embed.set_footer(text=f"Project ID: {project.id}")

            await interaction.response.edit_message(embed=embed, view=None)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
        except Exception as e:
            await send_interaction_error(interaction, e, f"creating project '{self.name}'", logger, ephemeral=True)


class ProjectCreateModal(discord.ui.Modal):
    def __init__(
        self,
        project_service: ProjectService,
        channel: discord.ForumChannel | discord.TextChannel | discord.Thread,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
        user_service: Any = None,
        draft_view: ProjectCreateDraftView | None = None,
        initial_name: str = "",
        initial_prefix: str = "",
        initial_desc: str = "",
        initial_cat: str = "",
    ):
        self.project_service = project_service
        self.channel = channel
        self.team_service = team_service
        self.task_service = task_service
        self.user_service = user_service
        self.draft_view = draft_view

        raw_name = getattr(channel, "name", None)
        if isinstance(raw_name, str) and raw_name.strip():
            chan_name = raw_name.strip()
        elif hasattr(channel, "id"):
            chan_name = str(channel.id)
        else:
            chan_name = "channel"

        is_forum = isinstance(channel, discord.ForumChannel)
        type_prefix = "Forum" if is_forum else "Channel"

        if draft_view:
            title_str = "Edit Project Details"
        else:
            title_str = f"New Project in #{chan_name}"

        # Max title length in Discord modal is 45 characters
        if len(title_str) > 45:
            title_str = title_str[:42] + "..."

        super().__init__(title=title_str)

        name_label = f"Project Name ({type_prefix} #{chan_name})"
        if len(name_label) > 45:
            name_label = name_label[:42] + "..."

        name_placeholder = f"e.g. Mobile Redesign (bound to #{chan_name})"
        if len(name_placeholder) > 100:
            name_placeholder = name_placeholder[:97] + "..."

        self.name_input = discord.ui.TextInput(
            label=name_label,
            placeholder=name_placeholder,
            default=initial_name,
            required=True,
            max_length=100,
        )
        self.add_item(self.name_input)

        self.prefix_input = discord.ui.TextInput(
            label="Key Prefix (Optional, 2-5 uppercase chars)",
            placeholder="e.g. MOB, INF (Leave empty for auto-generated)",
            default=initial_prefix,
            required=False,
            max_length=10,
        )
        self.add_item(self.prefix_input)

        self.desc_input = discord.ui.TextInput(
            label="Description (Optional)",
            style=discord.TextStyle.paragraph,
            placeholder="Mission statement, architecture goals, or deliverables...",
            default=initial_desc,
            required=False,
            max_length=1000,
        )
        self.add_item(self.desc_input)

        self.cat_input = discord.ui.TextInput(
            label="Category (Optional)",
            placeholder="e.g. Engineering, Marketing, Operations",
            default=initial_cat,
            required=False,
            max_length=50,
        )
        self.add_item(self.cat_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This action must be run in a Discord server.", ephemeral=True)
            return

        name = self.name_input.value.strip()
        if not name:
            await interaction.response.send_message("❌ Project name cannot be empty.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        prefix = self.prefix_input.value.strip() or None
        desc = self.desc_input.value.strip() or None
        cat = self.cat_input.value.strip() or None

        if self.draft_view:
            self.draft_view.name = name
            self.draft_view.prefix = prefix
            self.draft_view.description = desc
            self.draft_view.category = cat
            self.draft_view._rebuild_items()
            embed = build_project_draft_embed(
                name=name,
                channel=self.channel,
                prefix=prefix,
                description=desc,
                category=cat,
                role=self.draft_view.role,
                lead=self.draft_view.lead,
            )
            await interaction.response.edit_message(embed=embed, view=self.draft_view)
        else:
            draft_view = ProjectCreateDraftView(
                project_service=self.project_service,
                channel=self.channel,
                name=name,
                prefix=prefix,
                description=desc,
                category=cat,
                team_service=self.team_service,
                task_service=self.task_service,
                user_service=self.user_service,
                initial_interaction=interaction,
            )
            embed = build_project_draft_embed(
                name=name,
                channel=self.channel,
                prefix=prefix,
                description=desc,
                category=cat,
                role=None,
                lead=None,
            )
            await interaction.response.send_message(embed=embed, view=draft_view, ephemeral=True)


class ProjectChannelSelectView(discord.ui.View):
    """Interactive view allowing the user to select any Forum or Text channel for a new project."""

    def __init__(
        self,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

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

    async def _on_channel_selected(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        selected = self.channel_select.values[0]
        chan = interaction.guild.get_channel(selected.id) if hasattr(selected, "id") else selected
        if not chan or not isinstance(chan, (discord.ForumChannel, discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("❌ Invalid channel selected.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        modal = ProjectCreateModal(
            self.project_service,
            channel=chan,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        await interaction.response.send_modal(modal)

    async def _on_current_channel_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(
            interaction.channel, (discord.ForumChannel, discord.TextChannel, discord.Thread)
        ):
            await interaction.response.send_message(
                "❌ Current channel must be a Forum or Text channel.", ephemeral=True
            )
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        modal = ProjectCreateModal(
            self.project_service,
            channel=interaction.channel,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        await interaction.response.send_modal(modal)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
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
        role_str = f"<@&{p.discord_role_id}>" if p.discord_role_id else "*Public / All Members*"
        lead_str = f"<@{p.lead_discord_id}>" if p.lead_discord_id else "*Unassigned*"
        desc_str = p.description or "No description"
        cat_str = f" • [{p.category}]" if p.category else ""
        embed.add_field(
            name=f"{p.name} (`{p.prefix}`){cat_str}",
            value=(
                f"• Channel: {chan_str}\n"
                f"• Squad: {role_str} | Lead: {lead_str}\n"
                f"• Next Task: #{p.next_task_number}\n"
                f"• {desc_str}"
            ),
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
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.all_projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.current_page = current_page
        self.query = query
        self.page_size = page_size
        self._initial_interaction = initial_interaction
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()

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
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectArchiveConfirmView(discord.ui.View):
    """Interactive confirmation view prior to archiving a project and active tasks."""

    def __init__(
        self,
        project: Project,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.project = project
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

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

            view = ProjectMenuView(
                self.project_service,
                self.team_service,
                self.task_service,
                initial_interaction=interaction,
            )
            embed = build_project_menu_embed(view.is_server_manager)
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
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectRestoreConfirmView(discord.ui.View):
    """Interactive confirmation view prior to restoring an archived project."""

    def __init__(
        self,
        project: Project,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.project = project
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

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

            view = ProjectMenuView(
                self.project_service,
                self.team_service,
                self.task_service,
                initial_interaction=interaction,
            )
            embed = build_project_menu_embed(view.is_server_manager)
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
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
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
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.all_projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.current_page = current_page
        self.query = query
        self._initial_interaction = initial_interaction
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()

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
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
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
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.all_projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.current_page = current_page
        self.query = query
        self._initial_interaction = initial_interaction
        self._filtered_projects = self._filter_projects()
        self._rebuild_items()

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
            initial_interaction=interaction,
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
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
            view = ProjectMenuView(
                self.project_service,
                self.team_service,
                self.task_service,
                initial_interaction=interaction,
            )
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
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.projects = projects
        self.teams = teams
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

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
            view = ProjectMenuView(
                self.project_service,
                self.team_service,
                self.task_service,
                initial_interaction=interaction,
            )
            embed = build_project_menu_embed(view.is_server_manager)
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
        view = ProjectMenuView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = build_project_menu_embed(view.is_server_manager)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectRoleSelectView(discord.ui.View):
    """Interactive view to map or clear a contributor Discord role for a project."""

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

        self.selected_project_id: UUID = projects[0].id
        self.selected_role: discord.Role | None = None

        # Row 0: Select Project
        proj_options = [
            discord.SelectOption(
                label=f"{p.name} ({p.prefix})"[:100],
                value=str(p.id),
                description=(f"Role: @{p.discord_role_id}" if p.discord_role_id else "Public (No role)")[:50],
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

        # Row 1: Select Discord Role
        self.role_select = discord.ui.RoleSelect(
            placeholder="🎭 Select Squad Discord Role...",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.role_select.callback = self._on_role_selected
        self.add_item(self.role_select)

        # Row 2: Action Buttons
        self.assign_btn = discord.ui.Button(
            label="Map Squad Role",
            emoji="🎭",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        self.assign_btn.callback = self._on_assign_clicked
        self.add_item(self.assign_btn)

        self.clear_btn = discord.ui.Button(
            label="Clear Role (Make Public)",
            emoji="🌐",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        self.clear_btn.callback = self._on_clear_clicked
        self.add_item(self.clear_btn)

        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=2,
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

    def _get_selected_project(self) -> Project | None:
        return next((p for p in self.projects if p.id == self.selected_project_id), None)

    async def _on_project_changed(self, interaction: discord.Interaction) -> None:
        self.selected_project_id = UUID(self.proj_select.values[0])
        for opt in self.proj_select.options:
            opt.default = opt.value == str(self.selected_project_id)
        await interaction.response.defer()

    async def _on_role_selected(self, interaction: discord.Interaction) -> None:
        self.selected_role = self.role_select.values[0]
        await interaction.response.defer()

    async def _on_assign_clicked(self, interaction: discord.Interaction) -> None:
        proj = self._get_selected_project()
        if not proj:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        if not self.selected_role:
            if self.role_select.values:
                self.selected_role = self.role_select.values[0]
            else:
                await interaction.response.send_message(
                    "❌ Please select a Discord role to map to this project.", ephemeral=True
                )
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
                return

        try:
            await self.project_service.set_project_role(proj.id, self.selected_role.id)
            embed = discord.Embed(
                title="✅ Squad Role Mapped to Project",
                description=(
                    f"Mapped Discord role <@&{self.selected_role.id}> as the contributor squad for "
                    f"project **{proj.name}** (`{proj.prefix}`)."
                ),
                color=discord.Color.green(),
            )
            view = ProjectMenuView(
                self.project_service, self.team_service, self.task_service, initial_interaction=interaction
            )
            embed = build_project_menu_embed(view.is_server_manager)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"mapping role for project '{proj.name}'", logger, ephemeral=True
            )

    async def _on_clear_clicked(self, interaction: discord.Interaction) -> None:
        proj = self._get_selected_project()
        if not proj:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        try:
            await self.project_service.set_project_role(proj.id, None)
            embed = discord.Embed(
                title="🌐 Project Role Cleared",
                description=(
                    f"Project **{proj.name}** (`{proj.prefix}`) is now **Public** (open to all server members)."
                ),
                color=discord.Color.blue(),
            )
            view = ProjectMenuView(
                self.project_service, self.team_service, self.task_service, initial_interaction=interaction
            )
            embed = build_project_menu_embed(view.is_server_manager)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"clearing role for project '{proj.name}'", logger, ephemeral=True
            )

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(
            self.project_service, self.team_service, self.task_service, initial_interaction=interaction
        )
        embed = build_project_menu_embed(view.is_server_manager)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectLeadSelectView(discord.ui.View):
    """Interactive view to designate or clear a Project Lead for a project."""

    def __init__(
        self,
        projects: list[Project],
        project_service: ProjectService,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
    ):
        super().__init__(timeout=180)
        self.projects = projects
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

        self.selected_project_id: UUID = projects[0].id
        self.selected_user: discord.Member | discord.User | None = None

        # Row 0: Select Project
        proj_options = [
            discord.SelectOption(
                label=f"{p.name} ({p.prefix})"[:100],
                value=str(p.id),
                description=(f"Lead: @{p.lead_discord_id}" if p.lead_discord_id else "Unassigned")[:50],
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

        # Row 1: Select Lead Member
        self.user_select = discord.ui.UserSelect(
            placeholder="👑 Select Project Lead...",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.user_select.callback = self._on_user_selected
        self.add_item(self.user_select)

        # Row 2: Action Buttons
        self.assign_btn = discord.ui.Button(
            label="Designate Lead",
            emoji="👑",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        self.assign_btn.callback = self._on_assign_clicked
        self.add_item(self.assign_btn)

        self.clear_btn = discord.ui.Button(
            label="Clear Lead",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        self.clear_btn.callback = self._on_clear_clicked
        self.add_item(self.clear_btn)

        self.back_btn = discord.ui.Button(
            label="Back to Project Menu",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=2,
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

    def _get_selected_project(self) -> Project | None:
        return next((p for p in self.projects if p.id == self.selected_project_id), None)

    async def _on_project_changed(self, interaction: discord.Interaction) -> None:
        self.selected_project_id = UUID(self.proj_select.values[0])
        for opt in self.proj_select.options:
            opt.default = opt.value == str(self.selected_project_id)
        await interaction.response.defer()

    async def _on_user_selected(self, interaction: discord.Interaction) -> None:
        self.selected_user = self.user_select.values[0]
        await interaction.response.defer()

    async def _on_assign_clicked(self, interaction: discord.Interaction) -> None:
        proj = self._get_selected_project()
        if not proj:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        if not self.selected_user:
            if self.user_select.values:
                self.selected_user = self.user_select.values[0]
            else:
                await interaction.response.send_message(
                    "❌ Please select a Discord member to designate as Lead.", ephemeral=True
                )
                from src.adapters.discord_bot.menu_manager import menu_manager

                menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
                return

        try:
            await self.project_service.set_project_lead(proj.id, self.selected_user.id)
            embed = discord.Embed(
                title="👑 Project Lead Designated",
                description=(
                    f"Designated <@{self.selected_user.id}> as the **Project Lead** for "
                    f"project **{proj.name}** (`{proj.prefix}`)."
                ),
                color=discord.Color.green(),
            )
            view = ProjectMenuView(
                self.project_service, self.team_service, self.task_service, initial_interaction=interaction
            )
            embed = build_project_menu_embed(view.is_server_manager)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"designating lead for project '{proj.name}'", logger, ephemeral=True
            )

    async def _on_clear_clicked(self, interaction: discord.Interaction) -> None:
        proj = self._get_selected_project()
        if not proj:
            await interaction.response.send_message("❌ Project not found.", ephemeral=True)
            return

        try:
            await self.project_service.set_project_lead(proj.id, None)
            embed = discord.Embed(
                title="❌ Project Lead Cleared",
                description=f"Project **{proj.name}** (`{proj.prefix}`) has no designated Project Lead.",
                color=discord.Color.dark_grey(),
            )
            view = ProjectMenuView(
                self.project_service, self.team_service, self.task_service, initial_interaction=interaction
            )
            embed = build_project_menu_embed(view.is_server_manager)
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        except Exception as e:
            await send_interaction_error(
                interaction, e, f"clearing lead for project '{proj.name}'", logger, ephemeral=True
            )

    async def _on_back_clicked(self, interaction: discord.Interaction) -> None:
        view = ProjectMenuView(
            self.project_service, self.team_service, self.task_service, initial_interaction=interaction
        )
        embed = build_project_menu_embed(view.is_server_manager)
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class ProjectMenuView(discord.ui.View):
    """Control Center View for Project Operations."""

    def __init__(
        self,
        project_service: ProjectService,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
        initial_interaction: discord.Interaction | None = None,
        user: discord.Member | discord.User | None = None,
        is_server_manager: bool | None = None,
    ):
        super().__init__(timeout=180)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self._initial_interaction = initial_interaction

        effective_user = user or (initial_interaction.user if initial_interaction else None)
        if is_server_manager is not None:
            self.is_server_manager = is_server_manager
        elif effective_user is not None:
            from src.services.auth_service import AuthService

            self.is_server_manager = AuthService.is_server_manager(effective_user)
        else:
            self.is_server_manager = True

        self._rebuild_items()

    def _rebuild_items(self) -> None:
        self.clear_items()

        if self.is_server_manager:
            self.new_project_btn = discord.ui.Button(
                label="New Project",
                emoji="➕",
                style=discord.ButtonStyle.primary,
                row=0,
            )
            self.new_project_btn.callback = self._on_new_project_clicked
            self.add_item(self.new_project_btn)
        else:
            self.new_project_btn = None

        # Row 0: Active Projects (Always visible)
        self.list_projects_btn = discord.ui.Button(
            label="Active Projects",
            emoji="📋",
            style=discord.ButtonStyle.secondary if self.is_server_manager else discord.ButtonStyle.primary,
            row=0,
        )
        self.list_projects_btn.callback = self._on_list_projects_clicked
        self.add_item(self.list_projects_btn)

        if self.is_server_manager:
            self.set_role_btn = discord.ui.Button(
                label="Set Squad Role",
                emoji="🎭",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            self.set_role_btn.callback = self._on_set_role_clicked
            self.add_item(self.set_role_btn)

            self.set_lead_btn = discord.ui.Button(
                label="Set Project Lead",
                emoji="👑",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            self.set_lead_btn.callback = self._on_set_lead_clicked
            self.add_item(self.set_lead_btn)

            self.archive_btn = discord.ui.Button(
                label="Archive Project",
                emoji="📦",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            self.archive_btn.callback = self._on_archive_clicked
            self.add_item(self.archive_btn)

            self.restore_btn = discord.ui.Button(
                label="Restore Project",
                emoji="♻️",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            self.restore_btn.callback = self._on_restore_clicked
            self.add_item(self.restore_btn)
        else:
            self.set_role_btn = None
            self.set_lead_btn = None
            self.archive_btn = None
            self.restore_btn = None

        if self.task_service:
            self.tech_tree_btn = discord.ui.Button(
                label="Tech Tree",
                emoji="🌲",
                style=discord.ButtonStyle.secondary,
                row=1 if self.is_server_manager else 0,
            )
            self.tech_tree_btn.callback = self._on_tech_tree_clicked
            self.add_item(self.tech_tree_btn)

            self.hub_btn = discord.ui.Button(
                label="PM Main Menu",
                emoji="🏠",
                style=discord.ButtonStyle.secondary,
                row=1 if self.is_server_manager else 0,
            )
            self.hub_btn.callback = self._on_hub_clicked
            self.add_item(self.hub_btn)
        else:
            self.tech_tree_btn = None
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

    async def _on_tech_tree_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not self.task_service:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message("ℹ️ No active projects found in this server.", ephemeral=True)
            return

        if len(projects) == 1:
            await interaction.response.defer(ephemeral=True)
            buf = await self.task_service.render_project_tree(
                guild_id=interaction.guild.id,
                project_id=projects[0].id,
                orientation="lr",
                member_resolver=interaction.guild,
            )
            file = discord.File(fp=buf, filename="tech_tree.png")
            embed = discord.Embed(
                title=f"🌲 Tech Tree: [{projects[0].prefix}] {projects[0].name}",
                description="Showing dependency graph in **Horizontal (Left to Right)** layout.",
                color=discord.Color.from_rgb(16, 152, 247),
            )
            embed.set_image(url="attachment://tech_tree.png")
            from src.adapters.discord_bot.views.tree_view import TechTreeViewer

            view = TechTreeViewer(self.task_service, projects[0], current_orientation="lr")
            await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
            return

        from src.adapters.discord_bot.views.tree_view import TechTreeProjectSelectView

        view = TechTreeProjectSelectView(self.task_service, self.project_service, projects, orientation="lr")
        await interaction.response.send_message(
            "🌲 Choose a project to view its Tech Tree visualization:",
            view=view,
            ephemeral=True,
        )

    async def _on_hub_clicked(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed

        if self.task_service:
            view = PmHubView(self.project_service, self.team_service, self.task_service)
            embed = build_hub_welcome_embed()
            await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def _on_new_project_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be run in a Discord server.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        view = ProjectChannelSelectView(
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
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

    async def _on_list_projects_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message("📁 No active projects found in this server.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return

        embed = build_active_projects_embed(projects, page=0, total_count=len(projects))
        view = ProjectActiveListView(
            projects,
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_set_role_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message(
                "📁 No active projects found. Create a project first!", ephemeral=True
            )
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        view = ProjectRoleSelectView(
            projects,
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = discord.Embed(
            title="🎭 Map Squad Discord Role to Project",
            description="Select a project and choose a Discord role as its dedicated contributor squad:",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_set_lead_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message(
                "📁 No active projects found. Create a project first!", ephemeral=True
            )
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        view = ProjectLeadSelectView(
            projects,
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        embed = discord.Embed(
            title="👑 Designate Project Lead",
            description="Select a project and designate a member as the Project Lead with management permissions:",
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_archive_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        if not projects:
            await interaction.response.send_message("📁 No active projects available to archive.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        view = ProjectArchiveSelectView(
            projects,
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        total_pages = max(1, math.ceil(len(projects) / ProjectArchiveSelectView.PAGE_SIZE))
        embed = build_archive_select_embed(len(projects), 0, total_pages)
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_restore_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        all_proj = await self.project_service.list_projects(interaction.guild.id, include_archived=True)
        archived = [p for p in all_proj if p.is_archived]
        if not archived:
            await interaction.response.send_message("📁 No archived projects to restore.", ephemeral=True)
            from src.adapters.discord_bot.menu_manager import menu_manager

            menu_manager.schedule_toast_dismissal(interaction, delay=8.0)
            return
        view = ProjectRestoreSelectView(
            archived,
            self.project_service,
            self.team_service,
            self.task_service,
            initial_interaction=interaction,
        )
        total_pages = max(1, math.ceil(len(archived) / ProjectRestoreSelectView.PAGE_SIZE))
        embed = build_restore_select_embed(len(archived), 0, total_pages)
        await interaction.response.edit_message(embed=embed, view=view)


def build_project_menu_embed(is_server_manager: bool = True) -> discord.Embed:
    embed = discord.Embed(
        title="📁 Project Management Control Center",
        color=discord.Color.blurple(),
    )
    if is_server_manager:
        embed.description = (
            "Manage project containers, channel bindings, squad roles, and project leads without typing commands.\n\n"
            "• **`➕ New Project`**: Create a project container bound to any Forum or Text channel\n"
            "• **`📋 Active Projects`**: View all running projects, squad roles, and designated leads\n"
            "• **`🎭 Set Squad Role`**: Map a Discord role as the project's contributor squad\n"
            "• **`👑 Set Project Lead`**: Designate the project owner / lead with elevated permissions\n"
            "• **`📦 Archive Project`**: Soft-delete a completed project\n"
            "• **`♻️ Restore Project`**: Bring back an archived project"
        )
    else:
        embed.description = (
            "Browse active project containers, bound channels, and designated squad roles.\n\n"
            "• **`📋 Active Projects`**: View all running projects, squad roles, and designated leads"
        )
    embed.set_footer(text="dgg-pm • Zero-typing project management")
    return embed
