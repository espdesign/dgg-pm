from uuid import UUID

import discord

from src.services.task_service import TaskService


class TaskNoteModal(discord.ui.Modal):
    def __init__(self, task_id: UUID, short_id: str, task_service: TaskService):
        super().__init__(title=f"Add Progress Note: {short_id}")
        self.task_id = task_id
        self.short_id = short_id
        self.task_service = task_service

        self.note_input = discord.ui.TextInput(
            label="Progress Update / Note",
            style=discord.TextStyle.paragraph,
            placeholder="Type your notes, blockers, or execution updates here...",
            required=True,
            max_length=1500,
        )
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        note_text = self.note_input.value.strip()
        if not note_text:
            await interaction.response.send_message("❌ Note cannot be empty.", ephemeral=True)
            return

        try:
            await self.task_service.add_note(
                task_id=self.task_id,
                actor_discord_id=interaction.user.id,
                note_text=note_text,
            )
            await interaction.response.send_message(
                f"✅ Note added to **{self.short_id}** by <@{interaction.user.id}>:\n> {note_text}",
                ephemeral=False,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add note: {e}", ephemeral=True)
