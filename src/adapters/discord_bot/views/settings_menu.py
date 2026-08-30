from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from src.domain.enums import NotificationPreference

if TYPE_CHECKING:
    from src.services.project_service import ProjectService
    from src.services.task_service import TaskService
    from src.services.team_service import TeamService
    from src.services.user_service import UserService

logger = logging.getLogger("dgg_pm.views.settings_menu")


def build_settings_embed(user: discord.User | discord.Member, current_pref: NotificationPreference) -> discord.Embed:
    pref_labels = {
        NotificationPreference.DM: "💬 Direct Messages (DM Only)",
        NotificationPreference.CHANNEL: "📢 Channel Ping (In-Thread @mention)",
        NotificationPreference.BOTH: "🔔 Both (DM + Channel @mention)",
        NotificationPreference.NONE: "🔕 Silent / None (No direct pings)",
    }

    embed = discord.Embed(
        title=f"⚙️ Notification Preferences for @{user.display_name}",
        description=(
            f"**Current Preference:** `{pref_labels.get(current_pref, current_pref.value)}`\n\n"
            "Choose how you want to receive task assignments, updates, and deadline reminders in this server:\n\n"
            "• **`💬 DM Only`**: Private notifications delivered to your direct messages.\n"
            "• **`📢 Channel Ping`**: An `@mention` inside the task's thread/forum post (great if DMs are closed).\n"
            "• **`🔔 Both`**: Sends both a DM and an in-thread mention for maximum visibility.\n"
            "• **`🔕 Silent`**: No direct pings (track tasks manually on the task board)."
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="dgg-pm • Personal notification controls")
    return embed


class UserSettingsView(discord.ui.View):
    """Interactive view allowing a member to toggle their personal notification preferences."""

    def __init__(
        self,
        user_service: UserService,
        current_pref: NotificationPreference,
        project_service: ProjectService | None = None,
        team_service: TeamService | None = None,
        task_service: TaskService | None = None,
    ):
        super().__init__(timeout=120)
        self.user_service = user_service
        self.current_pref = current_pref
        self.project_service = project_service
        self.team_service = team_service
        self.task_service = task_service

        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.clear_items()

        # Row 0: Preference Buttons
        dm_btn = discord.ui.Button(
            label="DM Only",
            emoji="💬",
            style=discord.ButtonStyle.primary
            if self.current_pref == NotificationPreference.DM
            else discord.ButtonStyle.secondary,
            row=0,
        )
        dm_btn.callback = lambda i: self._on_pref_clicked(i, NotificationPreference.DM)
        self.add_item(dm_btn)

        chan_btn = discord.ui.Button(
            label="Channel Ping",
            emoji="📢",
            style=discord.ButtonStyle.primary
            if self.current_pref == NotificationPreference.CHANNEL
            else discord.ButtonStyle.secondary,
            row=0,
        )
        chan_btn.callback = lambda i: self._on_pref_clicked(i, NotificationPreference.CHANNEL)
        self.add_item(chan_btn)

        both_btn = discord.ui.Button(
            label="Both (DM + Ping)",
            emoji="🔔",
            style=discord.ButtonStyle.primary
            if self.current_pref == NotificationPreference.BOTH
            else discord.ButtonStyle.secondary,
            row=0,
        )
        both_btn.callback = lambda i: self._on_pref_clicked(i, NotificationPreference.BOTH)
        self.add_item(both_btn)

        none_btn = discord.ui.Button(
            label="Silent",
            emoji="🔕",
            style=discord.ButtonStyle.primary
            if self.current_pref == NotificationPreference.NONE
            else discord.ButtonStyle.secondary,
            row=0,
        )
        none_btn.callback = lambda i: self._on_pref_clicked(i, NotificationPreference.NONE)
        self.add_item(none_btn)

        # Row 1: Test & Back to Hub
        test_btn = discord.ui.Button(
            label="Test Notification",
            emoji="🧪",
            style=discord.ButtonStyle.success,
            row=1,
        )
        test_btn.callback = self._on_test_clicked
        self.add_item(test_btn)

        if self.project_service and self.team_service and self.task_service:
            back_btn = discord.ui.Button(
                label="PM Main Menu",
                emoji="🏠",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            back_btn.callback = self._on_hub_clicked
            self.add_item(back_btn)

    async def _on_test_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be run in a Discord server.", ephemeral=True)
            return

        pref = self.current_pref
        if pref == NotificationPreference.NONE:
            await interaction.response.send_message(
                "🔕 **Your notification preference is set to Silent / None.**\nNo test notification was sent.",
                ephemeral=True,
            )
            return

        test_embed = discord.Embed(
            title="🧪 dgg-pm Notification Test",
            description=(
                f"Hello <@{interaction.user.id}>! This is a test notification from **{interaction.guild.name}**.\n\n"
                f"• **Delivery Mode**: `{pref.value.upper()}`\n"
                "• Your task assignments, status updates, and deadline reminders will arrive via this method."
            ),
            color=discord.Color.green(),
        )
        test_embed.set_footer(text="dgg-pm • Notification Diagnostics")

        results: list[str] = []

        # Test DM delivery
        if pref in (NotificationPreference.DM, NotificationPreference.BOTH):
            try:
                await interaction.user.send(embed=test_embed)
                results.append(
                    "✅ **Direct Message (DM):** Successfully delivered to your DM inbox! Check your direct messages."
                )
            except discord.Forbidden:
                results.append(
                    "❌ **Direct Message (DM):** Delivery failed! DMs are blocked by your Discord privacy settings.\n"
                    "   *(Tip: Enable 'Allow direct messages' in Server Privacy Settings or switch to Channel Ping.)*"
                )
            except Exception as e:
                results.append(f"⚠️ **Direct Message (DM):** Unexpected error sending DM: {e}")

        # Test Channel delivery
        if pref in (NotificationPreference.CHANNEL, NotificationPreference.BOTH):
            results.append(
                f"📢 **Channel Ping:** Mentions (`<@{interaction.user.id}>`) will ping you inside task threads."
            )

        status_msg = "\n\n".join(results)
        await interaction.response.send_message(status_msg, ephemeral=True)

    async def _on_pref_clicked(self, interaction: discord.Interaction, new_pref: NotificationPreference) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Must be run in a Discord server.", ephemeral=True)
            return

        try:
            await self.user_service.set_preference(
                guild_id=interaction.guild.id,
                user_discord_id=interaction.user.id,
                notify_preference=new_pref,
            )
            self.current_pref = new_pref
            self._refresh_buttons()
            embed = build_settings_embed(interaction.user, self.current_pref)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.exception("Failed to update user preference: %s", e)
            await interaction.response.send_message(f"❌ Failed to save preference: {e}", ephemeral=True)

    async def _on_hub_clicked(self, interaction: discord.Interaction) -> None:
        from src.adapters.discord_bot.views.hub_menu import PmHubView, build_hub_welcome_embed

        if self.project_service and self.team_service and self.task_service:
            view = PmHubView(
                self.project_service,
                self.team_service,
                self.task_service,
                self.user_service,
            )
            embed = build_hub_welcome_embed()
            await interaction.response.edit_message(content=None, embed=embed, view=view)
