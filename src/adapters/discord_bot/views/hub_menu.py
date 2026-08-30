from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.adapters.discord_bot.views.project_menu import ProjectMenuView, build_project_menu_embed
from src.adapters.discord_bot.views.task_menu import TaskMenuView, build_task_menu_embed
from src.adapters.discord_bot.views.team_menu import TeamMenuView, build_team_menu_embed
from src.services.project_service import ProjectService
from src.services.task_service import TaskService
from src.services.team_service import TeamService

if TYPE_CHECKING:
    from src.services.user_service import UserService

logger = logging.getLogger("dgg_pm.views.hub_menu")


class PmHubView(discord.ui.View):
    """Master Hub View allowing seamless switching between Project, Team, Task, and Guide centers."""

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

    @discord.ui.button(label="Projects Hub", emoji="📁", style=discord.ButtonStyle.primary, row=0)
    async def projects_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_project_menu_embed()
        view = ProjectMenuView(self.project_service, self.team_service, self.task_service)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Teams Hub", emoji="👥", style=discord.ButtonStyle.primary, row=0)
    async def teams_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_team_menu_embed()
        view = TeamMenuView(self.team_service, self.project_service, self.task_service)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Tasks Hub", emoji="⚡", style=discord.ButtonStyle.primary, row=0)
    async def tasks_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_task_menu_embed()
        projects = (
            await self.project_service.list_projects(interaction.guild.id, include_archived=False)
            if interaction.guild
            else []
        )
        view = TaskMenuView(self.task_service, self.project_service, self.team_service, projects=projects)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="My Settings", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
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
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Guides", emoji="📖", style=discord.ButtonStyle.secondary, row=0)
    async def guide_tab(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = build_hub_welcome_embed()
        await interaction.response.edit_message(embed=embed, view=self)


def build_hub_welcome_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎛️ Project Management Control Hub",
        description=(
            "Welcome to **dgg-pm**! Manage your entire workflow with interactive dashboards.\n"
            "Click any of the hub tabs below to access dedicated management controls without typing CLI commands."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="📁 Projects Hub (`/project-menu`)",
        value="Create project containers, bind channels, and map squads.",
        inline=False,
    )
    embed.add_field(
        name="👥 Teams Hub (`/team-menu`)",
        value="Create squads, map Discord roles, and assign team leads/members.",
        inline=False,
    )
    embed.add_field(
        name="⚡ Tasks Hub (`/task-menu`)",
        value="Create tasks, filter active boards, and update execution status.",
        inline=False,
    )
    embed.add_field(
        name="⚙️ My Settings (`/my-settings`)",
        value="Customize your personal notification delivery (DM, Channel Ping, Both, Silent).",
        inline=False,
    )
    embed.set_footer(text="dgg-pm • Zero-typing project management")
    return embed
