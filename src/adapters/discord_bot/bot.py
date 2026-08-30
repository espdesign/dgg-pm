import logging
from uuid import UUID

import discord
from discord.ext import commands

from src.adapters.discord_bot.cogs.help_cog import HelpCog
from src.adapters.discord_bot.cogs.project_cog import ProjectCog
from src.adapters.discord_bot.cogs.settings_cog import SettingsCog
from src.adapters.discord_bot.cogs.task_cog import TaskCog
from src.adapters.discord_bot.cogs.team_cog import TeamCog
from src.adapters.discord_bot.error_handler import send_interaction_error
from src.adapters.discord_bot.views.forum_helpers import resolve_forum_tags
from src.adapters.discord_bot.views.task_buttons import TaskActionView
from src.adapters.discord_bot.views.task_embed import build_task_embed, build_thread_workspace_content
from src.adapters.discord_bot.views.task_modals import TaskEditModal, TaskNoteModal
from src.config import settings
from src.domain.enums import PriorityLevel, TaskStatus
from src.domain.models import Task
from src.services.project_service import ProjectService
from src.services.task_service import StaleVersionError, TaskService
from src.services.team_service import TeamService
from src.services.user_service import UserService
from src.utils.date_parser import get_due_date_from_preset

logger = logging.getLogger("dgg_pm.bot")


class DggPmBot(commands.Bot):
    def __init__(
        self,
        task_service: TaskService,
        project_service: ProjectService,
        team_service: TeamService,
        user_service: UserService | None = None,
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
        self.user_service = user_service

    async def setup_hook(self) -> None:
        """Invoked when bot is starting up before login."""
        # Load cogs
        await self.add_cog(ProjectCog(self, self.project_service, self.team_service, self.task_service))
        await self.add_cog(TeamCog(self, self.team_service, self.project_service, self.task_service))
        await self.add_cog(TaskCog(self, self.task_service, self.project_service, self.team_service))
        await self.add_cog(HelpCog(self, self.project_service, self.team_service, self.task_service))
        if self.user_service:
            await self.add_cog(
                SettingsCog(
                    self,
                    self.user_service,
                    self.project_service,
                    self.team_service,
                    self.task_service,
                )
            )
            logger.info("Loaded Discord cogs: ProjectCog, TeamCog, TaskCog, HelpCog, SettingsCog")
        else:
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
                # If interaction was already acknowledged (e.g. by in-memory View callback), skip
                if interaction.response.is_done():
                    return
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

    async def sync_root_task_message(self, task: Task) -> None:
        """Syncs the latest task embed to the original root starter message in the parent channel or forum post."""
        if not task.discord_thread_id or not task.discord_message_id:
            return
        try:
            thread = self.get_channel(task.discord_thread_id) or await self.fetch_channel(task.discord_thread_id)
            if isinstance(thread, discord.Thread):
                root_msg = None
                if isinstance(thread.parent, discord.ForumChannel):
                    try:
                        root_msg = thread.starter_message or await thread.fetch_message(task.discord_message_id)
                    except Exception:
                        pass
                elif thread.parent:
                    try:
                        root_msg = await thread.parent.fetch_message(task.discord_message_id)
                    except Exception:
                        pass

                if root_msg:
                    project_name = None
                    if task.project_id:
                        p = await self.project_service.get_by_id(task.project_id)
                        if p:
                            project_name = p.name
                    fresh_embed = build_task_embed(task, project_name=project_name)
                    await root_msg.edit(embed=fresh_embed)
        except Exception as e:
            logger.debug("Failed to sync root starter message for task %s: %s", task.short_id, e)

    async def sync_task_thread(
        self,
        task: Task,
        action: str | None = None,
        sync_title: bool = False,
    ) -> None:
        """Syncs the Discord thread state (applied tags, archive/unarchive, rename) for a task."""
        if not task.discord_thread_id:
            return
        try:
            thread = self.get_channel(task.discord_thread_id) or await self.fetch_channel(task.discord_thread_id)
            if not isinstance(thread, discord.Thread):
                return

            edit_kwargs = {}

            # Sync forum tags if thread is a post inside a ForumChannel
            if isinstance(thread.parent, discord.ForumChannel):
                tags_to_apply = resolve_forum_tags(
                    thread.parent,
                    task,
                    existing_tags=getattr(thread, "applied_tags", None),
                )
                edit_kwargs["applied_tags"] = tags_to_apply

            # Sync title if requested and task title changed
            if sync_title:
                expected_name = f"[{task.short_id}] {task.title}"
                if len(expected_name) > 100:
                    expected_name = expected_name[:97] + "..."
                if thread.name != expected_name:
                    edit_kwargs["name"] = expected_name

            # Archive / unarchive management
            should_archive = action == "archive" or task.status == TaskStatus.COMPLETED or task.is_archived
            should_unarchive = action == "unarchive" or (task.status != TaskStatus.COMPLETED and not task.is_archived)

            if should_archive and not thread.archived:
                edit_kwargs["archived"] = True
            elif should_unarchive and thread.archived:
                edit_kwargs["archived"] = False

            if edit_kwargs:
                await thread.edit(**edit_kwargs)
        except Exception as e:
            logger.warning("Failed to sync thread state for task %s (%s): %s", task.short_id, task.discord_thread_id, e)

    async def _update_interaction_view(
        self,
        interaction: discord.Interaction,
        updated_task: Task,
    ) -> None:
        """Updates the component view on interaction message without attaching a duplicate embed in threads."""
        new_view = TaskActionView(
            task_id=updated_task.id,
            current_status=updated_task.status,
            current_priority=updated_task.priority,
            task_service=self.task_service,
        )

        # If inside a discussion thread, keep the toolbar clean without attaching duplicate embed,
        # leading with the task description so the workspace stays readable.
        if isinstance(interaction.channel, discord.Thread):
            content = build_thread_workspace_content(updated_task)
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=content, embed=None, view=new_view)
        else:
            # Standalone task card in channel
            new_embed = build_task_embed(updated_task)
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=new_embed, view=new_view)

    async def _handle_dynamic_task_button(
        self,
        interaction: discord.Interaction,
        action: str,
        task_id: UUID,
    ) -> None:
        if interaction.response.is_done():
            return

        task = await self.task_service.get_by_id(task_id)
        if not task:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Task not found in database.", ephemeral=True)
            return

        # Prevent cross-guild access: only allow acting on tasks that belong to the
        # guild the interaction occurred in (if it occurred in a guild at all).
        if interaction.guild_id is not None and task.guild_id != interaction.guild_id:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ This task does not belong to this server.", ephemeral=True)
            return

        if action == "note":
            modal = TaskNoteModal(task_id=task_id, short_id=task.short_id, task_service=self.task_service)
            await interaction.response.send_modal(modal)
            return

        if action == "edit":
            modal = TaskEditModal(task=task, task_service=self.task_service)
            await interaction.response.send_modal(modal)
            return

        if action == "unassign":
            try:
                updated_task = await self.task_service.update_assignee(
                    task_id=task_id,
                    new_assignee_id=None,
                    actor_discord_id=interaction.user.id,
                )
                await self._update_interaction_view(interaction, updated_task)
                await self.sync_root_task_message(updated_task)
                await self.sync_task_thread(updated_task)
                return
            except Exception as e:
                await send_interaction_error(interaction, e, "unassigning task", logger, ephemeral=True)
                return

        if action == "priority":
            values = interaction.data.get("values", [])
            if values:
                try:
                    new_priority = PriorityLevel(values[0])
                    updated_task = await self.task_service.update_priority(
                        task_id=task_id,
                        new_priority=new_priority,
                        actor_discord_id=interaction.user.id,
                    )
                    await self._update_interaction_view(interaction, updated_task)
                    await self.sync_root_task_message(updated_task)
                    await self.sync_task_thread(updated_task)
                    return
                except Exception as e:
                    await send_interaction_error(interaction, e, "updating task priority", logger, ephemeral=True)
                    return

        if action == "assignee":
            values = interaction.data.get("values", [])
            if values:
                try:
                    new_assignee_id = int(values[0])
                    updated_task = await self.task_service.update_assignee(
                        task_id=task_id,
                        new_assignee_id=new_assignee_id,
                        actor_discord_id=interaction.user.id,
                    )
                    await self._update_interaction_view(interaction, updated_task)
                    await self.sync_root_task_message(updated_task)
                    await self.sync_task_thread(updated_task)
                    return
                except Exception as e:
                    await send_interaction_error(interaction, e, "updating task assignee", logger, ephemeral=True)
                    return

        if action == "due":
            values = interaction.data.get("values", [])
            if values:
                try:
                    due_at, is_clear = get_due_date_from_preset(values[0])
                    updated_task = await self.task_service.update_details(
                        task_id=task_id,
                        actor_discord_id=interaction.user.id,
                        due_at=due_at,
                        clear_due_at=is_clear,
                    )
                    await self._update_interaction_view(interaction, updated_task)
                    await self.sync_root_task_message(updated_task)
                    return
                except Exception as e:
                    await send_interaction_error(interaction, e, "updating task due date", logger, ephemeral=True)
                    return

        if action == "watchers":
            values = interaction.data.get("values", [])
            try:
                watchers = [int(uid) for uid in values]
                updated_task = await self.task_service.update_details(
                    task_id=task_id,
                    actor_discord_id=interaction.user.id,
                    watchers=watchers,
                )
                await self._update_interaction_view(interaction, updated_task)
                await self.sync_root_task_message(updated_task)
                return
            except Exception as e:
                await send_interaction_error(interaction, e, "updating task watchers", logger, ephemeral=True)
                return

        target_status = TaskStatus.IN_PROGRESS if action in ("start", "reopen") else TaskStatus.COMPLETED
        try:
            note_action = "reopened" if action == "reopen" else f"updated to {target_status.value}"
            updated_task = await self.task_service.update_status(
                task_id=task_id,
                new_status=target_status,
                expected_version=task.version,
                actor_discord_id=interaction.user.id,
                notes=f"Status {note_action} via button",
            )
            await self._update_interaction_view(interaction, updated_task)
            await self.sync_root_task_message(updated_task)
            await self.sync_task_thread(updated_task)

        except StaleVersionError:
            latest_task = await self.task_service.get_by_id(task_id)
            if latest_task:
                await self._update_interaction_view(interaction, latest_task)
                await self.sync_root_task_message(latest_task)
                await self.sync_task_thread(latest_task)
                await interaction.followup.send(
                    "⚠️ This task was already modified by another team member. The card has been refreshed.",
                    ephemeral=True,
                )
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Task no longer exists.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Task no longer exists.", ephemeral=True)
        except Exception as e:
            await send_interaction_error(interaction, e, "processing task button action", logger, ephemeral=True)
