import logging

import discord

from src.domain.enums import EventType
from src.domain.models import OutboxEvent
from src.ports.notifier import INotificationDispatcher

logger = logging.getLogger("dgg_pm.discord_notifier")


class DiscordNotifier(INotificationDispatcher):
    def __init__(self, bot: discord.Client):
        self.bot = bot

    async def _send_dm(self, user_id: int, embed: discord.Embed) -> bool:
        """Helper to send a Direct Message to a Discord user."""
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            if user:
                await user.send(embed=embed)
                return True
        except discord.Forbidden:
            logger.warning("Cannot send DM to user %s (DMs closed or user blocked bot).", user_id)
        except Exception as e:
            logger.exception("Failed to send DM to user %s: %s", user_id, e)
        return False

    async def dispatch_event(self, event: OutboxEvent) -> None:
        p = event.payload
        logger.info("Dispatching outbox event %s of type %s", event.id, event.event_type)

        if event.event_type == EventType.TASK_DUE_REMINDER:
            await self._handle_due_reminder(p)
        elif event.event_type == EventType.TASK_STATUS_CHANGED:
            await self._handle_status_changed(p)
        elif event.event_type == EventType.TASK_NOTE_ADDED:
            await self._handle_note_added(p)
        elif event.event_type == EventType.TASK_CREATED:
            await self._handle_task_created(p)

    async def _handle_due_reminder(self, payload: dict) -> None:
        assignee_id = payload.get("assignee_discord_id")
        if not assignee_id:
            return

        reminder_type = payload.get("reminder_type", "due")
        short_id = payload.get("short_id", "")
        title = payload.get("title", "")

        reminder_labels = {
            "24h": "due in 24 hours",
            "1h": "due in 1 hour",
            "due": "due right now",
        }
        label = reminder_labels.get(reminder_type, "approaching deadline")

        embed = discord.Embed(
            title=f"⏰ Task Deadline Reminder: [{short_id}]",
            description=f"Your assigned task **[{short_id}] {title}** is **{label}**.",
            color=discord.Color.red() if reminder_type == "due" else discord.Color.gold(),
        )
        embed.add_field(name="Task Title", value=title, inline=True)
        if payload.get("due_at"):
            embed.add_field(name="Due Timestamp", value=payload["due_at"], inline=True)

        await self._send_dm(assignee_id, embed)

    async def _handle_status_changed(self, payload: dict) -> None:
        short_id = payload.get("short_id", "")
        title = payload.get("title", "")
        old_status = payload.get("old_status", "")
        new_status = payload.get("new_status", "")
        actor_id = payload.get("actor_discord_id")
        notes = payload.get("notes")
        thread_id = payload.get("discord_thread_id")
        watchers: list[int] = payload.get("watchers", [])
        assignee_id = payload.get("assignee_discord_id")

        # Post update in Discord thread if available and update root starter message
        message_id = payload.get("discord_message_id")
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)
                if isinstance(thread, discord.Thread):
                    msg = f"🔄 **Status Updated:** `{old_status}` ➔ **`{new_status}`** by <@{actor_id}>"
                    if notes:
                        msg += f"\n> {notes}"
                    await thread.send(msg)

                    # Keep the root starter message in the parent channel up-to-date
                    if message_id and thread.parent:
                        try:
                            root_msg = await thread.parent.fetch_message(message_id)
                            if root_msg and root_msg.embeds:
                                embed = root_msg.embeds[0]
                                for i, field in enumerate(embed.fields):
                                    if field.name and "Status" in field.name:
                                        embed.set_field_at(
                                            i,
                                            name=field.name,
                                            value=f"`{new_status.upper()}`",
                                            inline=field.inline,
                                        )
                                        break
                                embed.color = (
                                    discord.Color.green()
                                    if new_status == "completed"
                                    else discord.Color.gold()
                                    if new_status == "inProgress"
                                    else discord.Color.blue()
                                )
                                await root_msg.edit(embed=embed)
                        except Exception as edit_err:
                            logger.debug("Could not edit root starter message: %s", edit_err)
            except Exception as e:
                logger.warning("Failed to post status update into thread %s: %s", thread_id, e)

        # Notify watchers and assignee via DM
        recipients = set(watchers)
        if assignee_id and assignee_id != actor_id:
            recipients.add(assignee_id)
        recipients.discard(actor_id)  # Don't notify the person who triggered the change

        if recipients:
            embed = discord.Embed(
                title=f"🔔 Task Update: [{short_id}] {title}",
                description=f"Status changed from `{old_status}` to **`{new_status}`** by <@{actor_id}>.",
                color=discord.Color.green() if new_status == "completed" else discord.Color.blue(),
            )
            if notes:
                embed.add_field(name="Notes", value=notes, inline=False)

            for uid in recipients:
                await self._send_dm(uid, embed)

    async def _handle_note_added(self, payload: dict) -> None:
        short_id = payload.get("short_id", "")
        title = payload.get("title", "")
        actor_id = payload.get("actor_discord_id")
        note = payload.get("note", "")
        thread_id = payload.get("discord_thread_id")
        watchers: list[int] = payload.get("watchers", [])
        assignee_id = payload.get("assignee_discord_id")

        # Post into thread
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id) or await self.bot.fetch_channel(thread_id)
                if isinstance(thread, discord.Thread):
                    await thread.send(f"📝 **Note added by <@{actor_id}>:**\n> {note}")
            except Exception as e:
                logger.warning("Failed to post note to thread %s: %s", thread_id, e)

        # Notify assignee & watchers via DM
        recipients = set(watchers)
        if assignee_id and assignee_id != actor_id:
            recipients.add(assignee_id)
        recipients.discard(actor_id)

        if recipients:
            embed = discord.Embed(
                title=f"💬 New Note: [{short_id}] {title}",
                description=f"<@{actor_id}> added a note:\n> {note}",
                color=discord.Color.blue(),
            )
            for uid in recipients:
                await self._send_dm(uid, embed)

    async def _handle_task_created(self, payload: dict) -> None:
        assignee_id = payload.get("assignee_discord_id")
        creator_id = payload.get("creator_discord_id")
        if assignee_id and assignee_id != creator_id:
            short_id = payload.get("short_id", "")
            title = payload.get("title", "")
            embed = discord.Embed(
                title=f"📥 New Task Assigned: [{short_id}]",
                description=f"<@{creator_id}> assigned you a new task: **{title}**",
                color=discord.Color.blue(),
            )
            await self._send_dm(assignee_id, embed)
