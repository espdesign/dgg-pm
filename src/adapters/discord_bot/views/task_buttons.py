import logging
from uuid import UUID

import discord

from src.adapters.discord_bot.views.task_embed import build_task_embed
from src.adapters.discord_bot.views.task_modals import TaskNoteModal
from src.domain.enums import TaskStatus
from src.services.task_service import StaleVersionError, TaskService

logger = logging.getLogger("dgg_pm.views.task_buttons")


class TaskActionView(discord.ui.View):
    """Persistent interactive view for task embed action buttons."""

    def __init__(
        self,
        task_id: UUID,
        current_status: TaskStatus,
        task_service: TaskService,
    ):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.task_service = task_service

        # Start / In Progress button
        self.start_btn = discord.ui.Button(
            label="In Progress",
            emoji="🟡",
            style=discord.ButtonStyle.primary,
            custom_id=f"task:start:{task_id}",
            disabled=(current_status == TaskStatus.IN_PROGRESS or current_status == TaskStatus.COMPLETED),
        )
        self.start_btn.callback = self._on_start_clicked
        self.add_item(self.start_btn)

        # Complete button
        self.complete_btn = discord.ui.Button(
            label="Complete",
            emoji="🟢",
            style=discord.ButtonStyle.success,
            custom_id=f"task:complete:{task_id}",
            disabled=(current_status == TaskStatus.COMPLETED),
        )
        self.complete_btn.callback = self._on_complete_clicked
        self.add_item(self.complete_btn)

        # Add Note button
        self.note_btn = discord.ui.Button(
            label="Add Note",
            emoji="📝",
            style=discord.ButtonStyle.secondary,
            custom_id=f"task:note:{task_id}",
        )
        self.note_btn.callback = self._on_note_clicked
        self.add_item(self.note_btn)

    async def _on_start_clicked(self, interaction: discord.Interaction) -> None:
        await self._handle_status_transition(interaction, TaskStatus.IN_PROGRESS)

    async def _on_complete_clicked(self, interaction: discord.Interaction) -> None:
        await self._handle_status_transition(interaction, TaskStatus.COMPLETED)

    async def _on_note_clicked(self, interaction: discord.Interaction) -> None:
        task = await self.task_service.get_by_id(self.task_id)
        short_id = task.short_id if task else str(self.task_id)[:8]
        modal = TaskNoteModal(task_id=self.task_id, short_id=short_id, task_service=self.task_service)
        await interaction.response.send_modal(modal)

    async def _handle_status_transition(
        self,
        interaction: discord.Interaction,
        new_status: TaskStatus,
    ) -> None:
        task = await self.task_service.get_by_id(self.task_id)
        if not task:
            await interaction.response.send_message("❌ Task not found.", ephemeral=True)
            return

        try:
            updated_task = await self.task_service.update_status(
                task_id=self.task_id,
                new_status=new_status,
                expected_version=task.version,
                actor_discord_id=interaction.user.id,
                notes=f"Status set to {new_status.value} via Discord button",
            )

            # Re-render message embed and buttons
            new_embed = build_task_embed(updated_task)
            new_view = TaskActionView(
                task_id=self.task_id,
                current_status=updated_task.status,
                task_service=self.task_service,
            )
            await interaction.response.edit_message(embed=new_embed, view=new_view)

        except StaleVersionError:
            # Graceful CAS Conflict UX: Inform user and re-render card with current state
            latest_task = await self.task_service.get_by_id(self.task_id)
            if latest_task:
                new_embed = build_task_embed(latest_task)
                new_view = TaskActionView(
                    task_id=self.task_id,
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
            logger.exception("Error handling button status transition: %s", e)
            await interaction.response.send_message(f"❌ Failed to update status: {e}", ephemeral=True)
