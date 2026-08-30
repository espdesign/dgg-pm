from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.adapters.discord_bot.views.project_menu import ProjectMenuView, build_project_menu_embed
from src.adapters.discord_bot.views.task_menu import TaskCreateModal, TaskMenuView, build_task_board_embed
from src.adapters.discord_bot.views.team_menu import TeamMenuView, build_team_menu_embed
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

if TYPE_CHECKING:
    from src.services.user_service import UserService

logger = logging.getLogger("dgg_pm.views.hub_menu")


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
        matched_proj = channel_projects[0] if channel_projects else (projects[0] if len(projects) == 1 else None)

        from src.services.auth_service import AuthService

        auth_srv = AuthService(self.project_service, self.team_service)
        modal = TaskCreateModal(
            task_service=self.task_service,
            project=matched_proj,
            target_channel=interaction.channel,
            auth_service=auth_srv,
        )
        await interaction.response.send_modal(modal)

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


def build_hub_welcome_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎛️ Project Management Control Hub",
        description=(
            "Welcome to **dgg-pm**! Manage your entire workflow with interactive dashboards.\n"
            "Click any button below to launch a private interactive workspace without modifying this hub for others."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="➕ New Task",
        value="Open the task creation form for this project.",
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
