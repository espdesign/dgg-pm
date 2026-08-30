import logging
from uuid import UUID

import discord

from src.adapters.discord_bot.views.task_embed import build_task_embed
from src.adapters.discord_bot.views.task_modals import TaskEditModal, TaskNoteModal
from src.domain.enums import PriorityLevel, TaskStatus
from src.services.task_service import StaleVersionError, TaskService
from src.utils.date_parser import get_due_date_from_preset

logger = logging.getLogger("dgg_pm.views.task_buttons")


class TaskActionView(discord.ui.View):
    """Persistent interactive view for task embed action buttons and select menus."""

    def __init__(
        self,
        task_id: UUID,
        current_status: TaskStatus,
        task_service: TaskService,
        current_priority: PriorityLevel = PriorityLevel.NORMAL,
    ):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.task_service = task_service
        self.current_status = current_status
        self.current_priority = current_priority

        # Row 0: Primary Action Buttons
        self.start_btn = discord.ui.Button(
            label="In Progress",
            emoji="🟡",
            style=discord.ButtonStyle.primary,
            custom_id=f"task:start:{task_id}",
            disabled=(current_status == TaskStatus.IN_PROGRESS or current_status == TaskStatus.COMPLETED),
            row=0,
        )
        self.start_btn.callback = self._on_start_clicked
        self.add_item(self.start_btn)

        self.complete_btn = discord.ui.Button(
            label="Complete",
            emoji="🟢",
            style=discord.ButtonStyle.success,
            custom_id=f"task:complete:{task_id}",
            disabled=(current_status == TaskStatus.COMPLETED),
            row=0,
        )
        self.complete_btn.callback = self._on_complete_clicked
        self.add_item(self.complete_btn)

        self.note_btn = discord.ui.Button(
            label="Add Note",
            emoji="📝",
            style=discord.ButtonStyle.secondary,
            custom_id=f"task:note:{task_id}",
            row=0,
        )
        self.note_btn.callback = self._on_note_clicked
        self.add_item(self.note_btn)

        self.edit_btn = discord.ui.Button(
            label="Edit Details",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"task:edit:{task_id}",
            row=0,
        )
        self.edit_btn.callback = self._on_edit_clicked
        self.add_item(self.edit_btn)

        # Row 1: Priority Dropdown
        priority_options = [
            discord.SelectOption(
                label="High Priority",
                value="high",
                emoji="🔴",
                default=(current_priority == PriorityLevel.HIGH),
            ),
            discord.SelectOption(
                label="Normal Priority",
                value="normal",
                emoji="🔵",
                default=(current_priority == PriorityLevel.NORMAL),
            ),
            discord.SelectOption(
                label="Low Priority",
                value="low",
                emoji="⚪",
                default=(current_priority == PriorityLevel.LOW),
            ),
        ]
        self.priority_select = discord.ui.Select(
            placeholder="⚡ Change Priority...",
            options=priority_options,
            custom_id=f"task:priority:{task_id}",
            row=1,
        )
        self.priority_select.callback = self._on_priority_selected
        self.add_item(self.priority_select)

        # Row 2: Assignee User Select Picker
        self.assignee_select = discord.ui.UserSelect(
            placeholder="👤 Reassign Member...",
            custom_id=f"task:assignee:{task_id}",
            row=2,
            min_values=1,
            max_values=1,
        )
        self.assignee_select.callback = self._on_assignee_selected
        self.add_item(self.assignee_select)

        # Row 3: Due Date Quick Presets Dropdown
        due_options = [
            discord.SelectOption(label="Today (EOD 5:00 PM)", value="today", emoji="⏰"),
            discord.SelectOption(label="Tomorrow (EOD 5:00 PM)", value="tomorrow", emoji="⏰"),
            discord.SelectOption(label="In 2 Days", value="2days", emoji="📅"),
            discord.SelectOption(label="In 3 Days", value="3days", emoji="📅"),
            discord.SelectOption(label="In 1 Week", value="1week", emoji="📅"),
            discord.SelectOption(label="In 2 Weeks", value="2weeks", emoji="📅"),
            discord.SelectOption(label="In 1 Month", value="1month", emoji="📅"),
            discord.SelectOption(label="Clear Due Date", value="clear", emoji="❌"),
        ]
        self.due_select = discord.ui.Select(
            placeholder="📅 Set Due Date (Quick Presets)...",
            options=due_options,
            custom_id=f"task:due:{task_id}",
            row=3,
        )
        self.due_select.callback = self._on_due_selected
        self.add_item(self.due_select)

    async def _on_start_clicked(self, interaction: discord.Interaction) -> None:
        await self._handle_status_transition(interaction, TaskStatus.IN_PROGRESS)

    async def _on_complete_clicked(self, interaction: discord.Interaction) -> None:
        await self._handle_status_transition(interaction, TaskStatus.COMPLETED)

    async def _on_note_clicked(self, interaction: discord.Interaction) -> None:
        task = await self.task_service.get_by_id(self.task_id)
        if not task:
            await interaction.response.send_message("❌ Task not found.", ephemeral=True)
            return
        modal = TaskNoteModal(task_id=self.task_id, short_id=task.short_id, task_service=self.task_service)
        await interaction.response.send_modal(modal)

    async def _on_edit_clicked(self, interaction: discord.Interaction) -> None:
        task = await self.task_service.get_by_id(self.task_id)
        if not task:
            await interaction.response.send_message("❌ Task not found.", ephemeral=True)
            return
        modal = TaskEditModal(task=task, task_service=self.task_service)
        await interaction.response.send_modal(modal)

    async def _on_priority_selected(self, interaction: discord.Interaction) -> None:
        selected_val = self.priority_select.values[0]
        new_priority = PriorityLevel(selected_val)
        try:
            updated_task = await self.task_service.update_priority(
                task_id=self.task_id,
                new_priority=new_priority,
                actor_discord_id=interaction.user.id,
            )
            new_embed = build_task_embed(updated_task)
            new_view = TaskActionView(
                task_id=self.task_id,
                current_status=updated_task.status,
                current_priority=updated_task.priority,
                task_service=self.task_service,
            )
            await interaction.response.edit_message(embed=new_embed, view=new_view)
        except Exception as e:
            logger.exception("Error changing task priority: %s", e)
            await interaction.response.send_message(f"❌ Failed to update priority: {e}", ephemeral=True)

    async def _on_assignee_selected(self, interaction: discord.Interaction) -> None:
        selected_user = self.assignee_select.values[0]
        new_assignee_id = selected_user.id
        try:
            updated_task = await self.task_service.update_assignee(
                task_id=self.task_id,
                new_assignee_id=new_assignee_id,
                actor_discord_id=interaction.user.id,
            )
            new_embed = build_task_embed(updated_task)
            new_view = TaskActionView(
                task_id=self.task_id,
                current_status=updated_task.status,
                current_priority=updated_task.priority,
                task_service=self.task_service,
            )
            await interaction.response.edit_message(embed=new_embed, view=new_view)
        except Exception as e:
            logger.exception("Error changing task assignee: %s", e)
            await interaction.response.send_message(f"❌ Failed to reassign task: {e}", ephemeral=True)

    async def _on_due_selected(self, interaction: discord.Interaction) -> None:
        selected_val = self.due_select.values[0]
        due_at, is_clear = get_due_date_from_preset(selected_val)
        try:
            updated_task = await self.task_service.update_details(
                task_id=self.task_id,
                actor_discord_id=interaction.user.id,
                due_at=due_at,
                clear_due_at=is_clear,
            )
            new_embed = build_task_embed(updated_task)
            new_view = TaskActionView(
                task_id=self.task_id,
                current_status=updated_task.status,
                current_priority=updated_task.priority,
                task_service=self.task_service,
            )
            await interaction.response.edit_message(embed=new_embed, view=new_view)
        except Exception as e:
            logger.exception("Error changing task due date: %s", e)
            await interaction.response.send_message(f"❌ Failed to update due date: {e}", ephemeral=True)

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
                current_priority=updated_task.priority,
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
                    current_priority=latest_task.priority,
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
