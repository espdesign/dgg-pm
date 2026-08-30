from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import discord

from src.adapters.discord_bot.views.project_menu import ProjectMenuView, build_project_menu_embed
from src.adapters.discord_bot.views.task_menu import (
    TaskCreateModal,
    TaskMenuView,
    TaskSelectProjectView,
    build_task_board_embed,
)
from src.adapters.discord_bot.views.team_menu import TeamMenuView, build_team_menu_embed
from src.domain.models import Project
from src.services.auth_service import AuthService
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

if TYPE_CHECKING:
    from src.services.user_service import UserService

logger = logging.getLogger("dgg_pm.views.hub_menu")


class HubTaskProjectSelectView(discord.ui.View):
    """Ephemeral project selector displayed when clicking 'New Task' in a multi-project forum."""

    def __init__(
        self,
        task_service: TaskService,
        channel_projects: list[Project],
        target_channel: discord.ForumChannel | discord.TextChannel | discord.Thread | None,
        auth_service: AuthService | None = None,
    ):
        super().__init__(timeout=120)
        self.task_service = task_service
        self.channel_projects = channel_projects
        self.target_channel = target_channel
        self.auth_service = auth_service

        options = []
        for p in channel_projects[:24]:
            options.append(
                discord.SelectOption(
                    label=f"[{p.prefix}] {p.name}"[:100],
                    value=str(p.id),
                    description=(p.description[:90] if p.description else f"Prefix: {p.prefix}"),
                    emoji="📁",
                )
            )
        options.append(
            discord.SelectOption(
                label="Standalone Task (No Project)",
                value="standalone",
                description="Create an ad-hoc unlinked chore/task",
                emoji="📌",
            )
        )

        self.select = discord.ui.Select(
            placeholder="📁 Select Project for New Task...",
            options=options,
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        val = self.select.values[0]
        if val == "standalone":
            modal = TaskCreateModal(
                task_service=self.task_service,
                project=None,
                target_channel=self.target_channel,
                auth_service=self.auth_service,
            )
        else:
            selected_proj = next((p for p in self.channel_projects if str(p.id) == val), None)
            modal = TaskCreateModal(
                task_service=self.task_service,
                project=selected_proj,
                target_channel=self.target_channel,
                auth_service=self.auth_service,
            )
        await interaction.response.send_modal(modal)


class HubBoardProjectSelectView(discord.ui.View):
    """Ephemeral project scope selector displayed when clicking 'Task Board' in a multi-project forum."""

    def __init__(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        team_service: TeamService | None,
        projects: list[Project],
        channel_projects: list[Project],
        current_channel_id: int | None = None,
        parent_channel_id: int | None = None,
    ):
        super().__init__(timeout=120)
        self.task_service = task_service
        self.project_service = project_service
        self.team_service = team_service
        self.projects = projects
        self.channel_projects = channel_projects
        self.current_channel_id = current_channel_id
        self.parent_channel_id = parent_channel_id

        options = [
            discord.SelectOption(
                label="All Projects (Global Scope)",
                value="all",
                description="View tasks across all projects",
                emoji="🌐",
            )
        ]
        for p in channel_projects[:24]:
            options.append(
                discord.SelectOption(
                    label=f"[{p.prefix}] {p.name}"[:100],
                    value=str(p.id),
                    description=(p.description[:90] if p.description else f"Prefix: {p.prefix}"),
                    emoji="📁",
                )
            )

        self.select = discord.ui.Select(
            placeholder="📁 Select Project Scope for Task Board...",
            options=options,
            row=0,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        val = self.select.values[0]
        selected_id = None if val == "all" else UUID(val)

        tasks, total = await self.task_service.list_tasks(
            guild_id=interaction.guild.id,
            project_id=selected_id,
            exclude_completed=True,
            limit=15,
        )

        project_label = "All Projects (Global Scope)"
        if selected_id:
            match = next((p for p in self.projects if p.id == selected_id), None)
            if match:
                project_label = f"[{match.prefix}] {match.name} (This Channel)"

        view = TaskMenuView(
            self.task_service,
            self.project_service,
            self.team_service,
            projects=self.projects,
            current_channel_id=self.current_channel_id,
            parent_channel_id=self.parent_channel_id,
            initial_project_id=selected_id,
        )
        embed = build_task_board_embed(
            tasks=tasks,
            total_count=total,
            project_label=project_label,
            status_label="Active Tasks (In Progress & Not Started)",
            assignee_label="All Members",
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class PmHubView(discord.ui.View):
    """Master Hub View allowing seamless opening of private interactive sessions for each user.

    All button interactions respond ephemerally or open modals, ensuring the public pinned
    control post in the forum/channel is never modified or disrupted by individual user clicks.
    """

    def __init__(
        self,
        project_service: ProjectService,
        team_service: TeamService,
        task_service: TaskService,
        user_service: UserService | None = None,
    ):
        super().__init__(timeout=None)
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service
        self.user_service = user_service

    @discord.ui.button(
        label="New Task",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=0,
        custom_id="pm_hub:new_task",
    )
    async def new_task_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        channel_id = interaction.channel.id if interaction.channel else None
        parent_id = getattr(interaction.channel, "parent_id", None)
        channel_ids = {cid for cid in (channel_id, parent_id) if cid}
        channel_projects = [p for p in projects if p.discord_channel_id and p.discord_channel_id in channel_ids]

        target_channel = interaction.channel
        if isinstance(target_channel, discord.Thread):
            parent = getattr(target_channel, "parent", None)
            if not parent and getattr(target_channel, "parent_id", None):
                parent = interaction.guild.get_channel(target_channel.parent_id)
            if isinstance(parent, discord.ForumChannel):
                target_channel = parent

        auth_srv = AuthService(self.project_service, self.team_service) if self.team_service else None

        if len(channel_projects) == 1:
            matched_proj = channel_projects[0]
            if matched_proj.discord_channel_id and not isinstance(target_channel, discord.ForumChannel):
                proj_chan = interaction.guild.get_channel(matched_proj.discord_channel_id)
                if proj_chan:
                    target_channel = proj_chan
            modal = TaskCreateModal(
                task_service=self.task_service,
                project=matched_proj,
                target_channel=target_channel,
                auth_service=auth_srv,
            )
            await interaction.response.send_modal(modal)
        elif len(channel_projects) > 1:
            picker_view = HubTaskProjectSelectView(
                task_service=self.task_service,
                channel_projects=channel_projects,
                target_channel=target_channel,
                auth_service=auth_srv,
            )
            embed = discord.Embed(
                title="➕ New Task: Select Project",
                description="Choose which active project in this channel to create the task under:",
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, view=picker_view, ephemeral=True)
        else:
            # 0 channel projects
            if len(projects) == 1:
                matched_proj = projects[0]
                if matched_proj.discord_channel_id and not isinstance(target_channel, discord.ForumChannel):
                    proj_chan = interaction.guild.get_channel(matched_proj.discord_channel_id)
                    if proj_chan:
                        target_channel = proj_chan
                modal = TaskCreateModal(
                    task_service=self.task_service,
                    project=matched_proj,
                    target_channel=target_channel,
                    auth_service=auth_srv,
                )
                await interaction.response.send_modal(modal)
            elif len(projects) == 0:
                modal = TaskCreateModal(
                    task_service=self.task_service,
                    project=None,
                    target_channel=target_channel,
                    auth_service=auth_srv,
                )
                await interaction.response.send_modal(modal)
            else:
                view = TaskSelectProjectView(
                    projects=projects,
                    task_service=self.task_service,
                    project_service=self.project_service,
                    team_service=self.team_service,
                    current_channel_id=channel_id,
                    parent_channel_id=parent_id,
                    auth_service=auth_srv,
                )
                embed = discord.Embed(
                    title="📁 Select Project Container",
                    description=(
                        "Choose which active project to create the task inside:\n"
                        "• Use **`🔍 Search Projects`** to quickly filter across all projects."
                    ),
                    color=discord.Color.blurple(),
                )
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Task Board",
        emoji="⚡",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="pm_hub:task_board",
    )
    async def tasks_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        projects = await self.project_service.list_projects(interaction.guild.id, include_archived=False)
        channel_id = interaction.channel.id if interaction.channel else None
        parent_id = getattr(interaction.channel, "parent_id", None)

        channel_ids = {cid for cid in (channel_id, parent_id) if cid}
        channel_projects = [p for p in projects if p.discord_channel_id and p.discord_channel_id in channel_ids]

        if len(channel_projects) > 1:
            picker_view = HubBoardProjectSelectView(
                task_service=self.task_service,
                project_service=self.project_service,
                team_service=self.team_service,
                projects=projects,
                channel_projects=channel_projects,
                current_channel_id=channel_id,
                parent_channel_id=parent_id,
            )
            embed = discord.Embed(
                title="⚡ Task Board: Select Project Scope",
                description="Choose which project board to view for this forum, or view all projects combined:",
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=embed, view=picker_view, ephemeral=True)
            return

        selected_project_id = channel_projects[0].id if channel_projects else None
        tasks, total = await self.task_service.list_tasks(
            guild_id=interaction.guild.id,
            project_id=selected_project_id,
            exclude_completed=True,
            limit=15,
        )

        project_label = "All Projects (Global Scope)"
        if selected_project_id:
            match = channel_projects[0]
            project_label = f"[{match.prefix}] {match.name} (This Channel)"

        view = TaskMenuView(
            self.task_service,
            self.project_service,
            self.team_service,
            projects=projects,
            current_channel_id=channel_id,
            parent_channel_id=parent_id,
            initial_project_id=selected_project_id,
        )
        embed = build_task_board_embed(
            tasks=tasks,
            total_count=total,
            project_label=project_label,
            status_label="Active Tasks (In Progress & Not Started)",
            assignee_label="All Members",
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Projects Hub",
        emoji="📁",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="pm_hub:projects",
    )
    async def projects_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_project_menu_embed()
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Teams Hub",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="pm_hub:teams",
    )
    async def teams_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_team_menu_embed()
        view = TeamMenuView(self.team_service, self.project_service, self.task_service)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="My Settings",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="pm_hub:settings",
    )
    async def settings_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from src.adapters.discord_bot.views.settings_menu import UserSettingsView, build_settings_embed

        if not self.user_service or not interaction.guild:
            await interaction.response.send_message("❌ Settings service not available.", ephemeral=True)
            return
        current_pref = await self.user_service.get_preference(interaction.guild.id, interaction.user.id)
        view = UserSettingsView(
            user_service=self.user_service,
            current_pref=current_pref,
            project_service=self.project_service,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        embed = build_settings_embed(interaction.user, current_pref)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="Guides",
        emoji="📖",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="pm_hub:guides",
    )
    async def guide_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_hub_welcome_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)


def build_hub_welcome_embed(
    channel_name: str | None = None,
    bound_projects: list[Project] | None = None,
) -> discord.Embed:
    if channel_name:
        title = f"🎛️ #{channel_name} • Control Hub"
    else:
        title = "🎛️ Project Management Control Hub"

    embed = discord.Embed(
        title=title,
        color=discord.Color.blurple(),
    )

    if bound_projects:
        if len(bound_projects) == 1:
            p = bound_projects[0]
            desc = (
                f"Interactive management workspace for **{p.name}** (`[{p.prefix}]`).\n"
                "Click any button below to perform operations without typing commands."
            )
        else:
            projects_summary = "\n".join(
                f"• **{p.name}** (`[{p.prefix}]`)" + (f" — *{p.description}*" if p.description else "")
                for p in bound_projects
            )
            desc = (
                f"Interactive management workspace for projects in this channel:\n"
                f"{projects_summary}\n\n"
                "Click any button below to perform operations without typing commands."
            )
    else:
        desc = (
            "Welcome to **dgg-pm**! Manage your entire workflow with interactive dashboards.\n"
            "Click any button below to launch a private interactive workspace without modifying this hub for others."
        )

    embed.description = desc
    embed.add_field(
        name="➕ New Task",
        value="Create a new task within a project in this forum.",
        inline=False,
    )
    embed.add_field(
        name="⚡ Task Board",
        value="Launch private interactive task board with filters and pagination.",
        inline=False,
    )
    embed.add_field(
        name="📁 Projects Hub",
        value="View project containers, bound channels, and mapped squads.",
        inline=False,
    )
    embed.add_field(
        name="👥 Teams Hub",
        value="Inspect squad rosters, Discord roles, and team leads.",
        inline=False,
    )
    embed.add_field(
        name="⚙️ My Settings",
        value="Configure your personal notification delivery (DM, Channel Ping, Both, Silent).",
        inline=False,
    )
    embed.set_footer(text="dgg-pm • Zero-clutter Discord-native project management")
    return embed
