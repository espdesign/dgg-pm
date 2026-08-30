from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.adapters.discord_bot.views.settings_menu import UserSettingsView, build_settings_embed
from src.domain.enums import NotificationPreference

if TYPE_CHECKING:
    from src.services.project_service import ProjectService
    from src.services.task_service import TaskService
    from src.services.team_service import TeamService
    from src.services.user_service import UserService

logger = logging.getLogger("dgg_pm.cogs.settings")


class SettingsCog(commands.Cog):
    """Slash commands for managing personal preferences and notifications."""

    def __init__(
        self,
        bot: commands.Bot,
        user_service: UserService,
        project_service: ProjectService | None = None,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
    ):
        self.bot = bot
        self.user_service = user_service
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

    @app_commands.command(
        name="my-settings",
        description="Configure your personal notification delivery (DM, Channel Mention, Both, Silent).",
    )
    @app_commands.describe(notify="Choose your preferred notification delivery method in this server")
    @app_commands.choices(
        notify=[
            app_commands.Choice(name="💬 Direct Messages (DM Only)", value="dm"),
            app_commands.Choice(name="📢 Channel Mention (In-Thread)", value="channel"),
            app_commands.Choice(name="🔔 Both (DM + Channel Mention)", value="both"),
            app_commands.Choice(name="🔕 Silent / None (No pings)", value="none"),
        ]
    )
    async def my_settings(
        self,
        interaction: discord.Interaction,
        notify: app_commands.Choice[str] | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used in a Discord server.", ephemeral=True)
            return

        current_pref = await self.user_service.get_preference(interaction.guild.id, interaction.user.id)

        # If user passed a choice parameter directly, update it immediately
        if notify:
            new_pref = NotificationPreference(notify.value)
            await self.user_service.set_preference(interaction.guild.id, interaction.user.id, new_pref)
            current_pref = new_pref

        view = UserSettingsView(
            user_service=self.user_service,
            current_pref=current_pref,
            project_service=self.project_service,
            team_service=self.team_service,
            task_service=self.task_service,
        )
        from src.adapters.discord_bot.menu_manager import menu_manager

        embed = build_settings_embed(interaction.user, current_pref)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await menu_manager.register_menu(interaction)
