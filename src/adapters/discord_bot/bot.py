import logging
from uuid import UUID

import discord
from discord.ext import commands

from src.adapters.discord_bot.cogs.help_cog import HelpCog
from src.adapters.discord_bot.cogs.project_cog import ProjectCog
from src.adapters.discord_bot.cogs.task_cog import TaskCog
from src.adapters.discord_bot.cogs.team_cog import TeamCog
from src.adapters.discord_bot.views.task_buttons import TaskActionView
from src.adapters.discord_bot.views.task_embed import build_task_embed
from src.adapters.discord_bot.views.task_modals import TaskNoteModal
from src.config import settings
from src.domain.enums import TaskStatus
from src.services.project_service import ProjectService
from src.services.task_service import StaleVersionError, TaskService
from src.services.team_service import TeamService

logger = logging.getLogger("dgg_pm.bot")


class DggPmBot(commands.Bot):
    def __init__(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        team_service: TeamService,
    ):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        # Note: MessageContent intent is explicitly NOT required

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )
        self.task_service = task_service
        self.project_service = project_service
        self.team_service = team_service

    async def setup_hook(self) -> None:
        """Invoked when bot is starting up before login."""
        # Load cogs
        await self.add_cog(ProjectCog(self, self.project_service, self.team_service))
        await self.add_cog(TeamCog(self, self.team_service))
        await self.add_cog(TaskCog(self, self.task_service, self.project_service))
        await self.add_cog(HelpCog(self))
        logger.info("Loaded Discord cogs: ProjectCog, TeamCog, TaskCog, HelpCog")

        # Sync application slash commands
        if settings.DISCORD_GUILD_ID:
            guild = discord.Object(id=settings.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced slash commands to development guild %s", settings.DISCORD_GUILD_ID)
        else:
            await self.tree.sync()
            logger.info("Synced slash commands globally.")

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (ID: %s) across %d guilds",
            self.user,
            self.user.id if self.user else "N/A",
            len(self.guilds),
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="tasks with /help-pm",
            )
        )

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Global interaction dispatcher handling dynamic persistent task buttons across restarts."""
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get("custom_id", "")
            if custom_id.startswith("task:"):
                # Format: task:{action}:{task_uuid}
                parts = custom_id.split(":")
                if len(parts) == 3:
                    action, task_uuid_str = parts[1], parts[2]
                    try:
                        task_uuid = UUID(task_uuid_str)
                        await self._handle_dynamic_task_button(interaction, action, task_uuid)
                        return
                    except ValueError:
                        pass
        await super().on_interaction(interaction)

    async def _handle_dynamic_task_button(
        self,
        interaction: discord.Interaction,
        action: str,
        task_id: UUID,
    ) -> None:
        task = await self.task_service.get_by_id(task_id)
        if not task:
            await interaction.response.send_message("❌ Task not found in database.", ephemeral=True)
            return

        if action == "note":
            modal = TaskNoteModal(task_id=task_id, short_id=task.short_id, task_service=self.task_service)
            await interaction.response.send_modal(modal)
            return

        target_status = TaskStatus.IN_PROGRESS if action == "start" else TaskStatus.COMPLETED
        try:
            updated_task = await self.task_service.update_status(
                task_id=task_id,
                new_status=target_status,
                expected_version=task.version,
                actor_discord_id=interaction.user.id,
                notes=f"Status updated to {target_status.value} via button",
            )
            new_embed = build_task_embed(updated_task)
            new_view = TaskActionView(
                task_id=task_id,
                current_status=updated_task.status,
                task_service=self.task_service,
            )
            await interaction.response.edit_message(embed=new_embed, view=new_view)

        except StaleVersionError:
            latest_task = await self.task_service.get_by_id(task_id)
            if latest_task:
                new_embed = build_task_embed(latest_task)
                new_view = TaskActionView(
                    task_id=task_id,
                    current_status=latest_task.status,
                    task_service=self.task_service,
                )
                await interaction.response.edit_message(embed=new_embed, view=new_view)
                await interaction.followup.send(
                    "⚠️ This task was already updated by another team member. The card has been refreshed.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message("❌ Task no longer exists.", ephemeral=True)
        except Exception as e:
            logger.exception("Error handling dynamic task button: %s", e)
            await interaction.response.send_message(f"❌ Failed to process button action: {e}", ephemeral=True)
