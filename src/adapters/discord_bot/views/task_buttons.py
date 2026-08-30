import logging
from uuid import UUID

import discord

from src.domain.enums import PriorityLevel, TaskStatus
from src.services.task_service import TaskService

logger = logging.getLogger("dgg_pm.views.task_buttons")


class TaskActionView(discord.ui.View):
    """Persistent interactive view for task embed action buttons and select menus.

    All interactions are centrally handled by DggPmBot._handle_dynamic_task_button
    via on_interaction to prevent double-acknowledgment race conditions and ensure
    persistent functionality across bot restarts.
    """

    def __init__(
        self,
        task_id: UUID,
        current_status: TaskStatus,
        task_service: TaskService | None = None,
        current_priority: PriorityLevel = PriorityLevel.NORMAL,
    ):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.task_service = task_service
        self.current_status = current_status
        self.current_priority = current_priority

        # Row 0: Primary Action Buttons
        if current_status == TaskStatus.COMPLETED:
            self.reopen_btn = discord.ui.Button(
                label="Reopen / Undo",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                custom_id=f"task:reopen:{task_id}",
                row=0,
            )
            self.add_item(self.reopen_btn)
        else:
            self.start_btn = discord.ui.Button(
                label="In Progress",
                emoji="🟡",
                style=discord.ButtonStyle.primary,
                custom_id=f"task:start:{task_id}",
                disabled=(current_status == TaskStatus.IN_PROGRESS),
                row=0,
            )
            self.add_item(self.start_btn)

            self.complete_btn = discord.ui.Button(
                label="Complete",
                emoji="🟢",
                style=discord.ButtonStyle.success,
                custom_id=f"task:complete:{task_id}",
                row=0,
            )
            self.add_item(self.complete_btn)

        self.note_btn = discord.ui.Button(
            label="Add Note",
            emoji="📝",
            style=discord.ButtonStyle.secondary,
            custom_id=f"task:note:{task_id}",
            row=0,
        )
        self.add_item(self.note_btn)

        self.edit_btn = discord.ui.Button(
            label="Edit Details",
            emoji="✏️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"task:edit:{task_id}",
            row=0,
        )
        self.add_item(self.edit_btn)

        self.unassign_btn = discord.ui.Button(
            label="Unassign",
            emoji="🚫",
            style=discord.ButtonStyle.secondary,
            custom_id=f"task:unassign:{task_id}",
            row=0,
        )
        self.add_item(self.unassign_btn)

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
        self.add_item(self.priority_select)

        # Row 2: Assignee User Select Picker
        self.assignee_select = discord.ui.UserSelect(
            placeholder="👤 Reassign Member...",
            custom_id=f"task:assignee:{task_id}",
            row=2,
            min_values=1,
            max_values=1,
        )
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
        self.add_item(self.due_select)

        # Row 4: Watchers User Select Picker (Multi-Select)
        self.watchers_select = discord.ui.UserSelect(
            placeholder="👀 Manage Watchers / CC (Pick up to 10)...",
            custom_id=f"task:watchers:{task_id}",
            row=4,
            min_values=1,
            max_values=10,
        )
        self.add_item(self.watchers_select)
